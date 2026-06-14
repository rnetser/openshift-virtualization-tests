# Co-authored-by: Claude <noreply@anthropic.com>
"""Test collector for coverage gate.

Collects all tests from the repository — both automated (via pytest --collect-only)
and unautomated STD placeholders (via std_placeholder_stats).
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_CNV_JIRA_PATTERN = re.compile(pattern=r"CNV-\d+")


@dataclass
class QuarantinedTest:
    """A test that is quarantined (intentionally skipped).

    Attributes:
        node_id: Pytest-style node ID.
        reason: Human-readable quarantine reason.
        jira: Jira ticket ID extracted from reason or marker (e.g., ``CNV-62939``).
    """

    node_id: str
    reason: str
    jira: str | None


def _parse_pytest_collect_output(stdout: str) -> list[str]:
    """Parse pytest ``--collect-only -q`` output to extract test node IDs.

    Filters out non-test lines such as WARNING/ERROR/HINT messages from
    plugins (e.g., pytest-order) that may contain ``::`` separators.

    Args:
        stdout: Raw stdout from ``pytest --collect-only -q``.

    Returns:
        List of pytest node IDs.
    """
    node_ids: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("WARNING", "ERROR", "HINT")):
            continue
        if "::" not in stripped:
            continue
        # Real paths don't contain spaces before the first ::
        path_part = stripped.split("::")[0]
        if " " in path_part:
            continue
        node_ids.append(stripped)
    return node_ids


def collect_all_tests(tests_dir: Path) -> tuple[list[str], list[str], set[str]]:
    """Collect both automated and unautomated test node IDs.

    Automated tests are collected via ``pytest --collect-only``.
    Unautomated tests are collected via std_placeholder_stats AST scanning.
    Gating tests are collected via a second ``pytest --collect-only -m gating`` run.

    The OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH env var is set to 'amd64'
    to allow collection without a cluster connection.

    Args:
        tests_dir: Path to the tests directory to scan.

    Returns:
        Tuple of (automated_node_ids, unautomated_node_ids, gating_node_ids).
    """
    env = os.environ.copy()
    env["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = "amd64"

    result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q", str(tests_dir)],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        LOGGER.warning(f"pytest collection exited with code {result.returncode}")
        if result.stderr:
            LOGGER.warning(f"pytest stderr: {result.stderr[:500]}")
    automated_ids = _parse_pytest_collect_output(stdout=result.stdout)
    LOGGER.info(f"Collected {len(automated_ids)} automated tests via pytest")

    from scripts.std_placeholder_stats.std_placeholder_stats import scan_placeholder_tests  # noqa: PLC0415

    placeholder_files = scan_placeholder_tests(tests_dir=tests_dir)

    unautomated_ids: list[str] = []
    for pf in placeholder_files:
        for cls in pf.classes:
            for method in cls.test_methods:
                unautomated_ids.append(f"{pf.file_path}::{cls.name}::{method}")
        for test in pf.standalone_tests:
            unautomated_ids.append(f"{pf.file_path}::{test}")

    LOGGER.info(f"Collected {len(unautomated_ids)} unautomated placeholder tests")

    # Collect gating-marked tests
    gating_result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q", str(tests_dir), "-m", "gating"],
        capture_output=True,
        text=True,
        env=env,
    )
    if gating_result.returncode != 0:
        LOGGER.warning(f"pytest gating collection exited with code {gating_result.returncode}")
        if gating_result.stderr:
            LOGGER.warning(f"pytest gating stderr: {gating_result.stderr[:500]}")
    gating_ids = set(_parse_pytest_collect_output(stdout=gating_result.stdout))
    LOGGER.info(f"Collected {len(gating_ids)} gating-marked tests")

    return automated_ids, unautomated_ids, gating_ids


def _extract_string_from_node(node: ast.expr) -> str | None:
    """Extract a string value from an AST node.

    Handles constants, f-strings with a QUARANTINED variable, and
    joined string fragments.

    Args:
        node: AST expression node.

    Returns:
        Extracted string if determinable, None otherwise.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # f-string: concatenate constant parts and resolve Name references
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                # Resolve variable name (e.g., QUARANTINED -> "QUARANTINED")
                parts.append(value.value.id)
            else:
                parts.append("...")
        return "".join(parts)
    return None


def _is_quarantine_xfail(decorator: ast.expr) -> tuple[bool, str]:
    """Check if a decorator is a quarantine xfail marker.

    Looks for ``@pytest.mark.xfail(reason=..., run=False)`` where the
    reason string contains "quarantined" (case-insensitive).

    Args:
        decorator: AST decorator node.

    Returns:
        Tuple of (is_quarantine, reason_string).
    """
    if not isinstance(decorator, ast.Call):
        return False, ""

    func = decorator.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr == "xfail"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    ):
        return False, ""

    reason = ""
    has_run_false = False

    for keyword in decorator.keywords:
        if keyword.arg == "reason":
            reason = _extract_string_from_node(node=keyword.value) or ""
        if keyword.arg == "run" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
            has_run_false = True

    if has_run_false and "quarantined" in reason.lower():
        return True, reason
    return False, ""


def _is_jira_run_false(decorator: ast.expr) -> tuple[bool, str]:
    """Check if a decorator is a jira marker with run=False.

    Looks for ``@pytest.mark.jira("CNV-XXXXX", run=False)``.

    Args:
        decorator: AST decorator node.

    Returns:
        Tuple of (is_jira_quarantine, jira_id).
    """
    if not isinstance(decorator, ast.Call):
        return False, ""

    func = decorator.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr == "jira"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    ):
        return False, ""

    has_run_false = False
    jira_id = ""

    for keyword in decorator.keywords:
        if keyword.arg == "run" and isinstance(keyword.value, ast.Constant) and keyword.value.value is False:
            has_run_false = True

    if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
        jira_id = decorator.args[0].value

    if has_run_false and jira_id:
        return True, jira_id
    return False, ""


def _check_decorators(decorators: list[ast.expr]) -> tuple[bool, str, str | None]:
    """Check a list of decorators for quarantine markers.

    Args:
        decorators: List of AST decorator nodes.

    Returns:
        Tuple of (is_quarantined, reason, jira_id).
    """
    for decorator in decorators:
        is_xfail, reason = _is_quarantine_xfail(decorator=decorator)
        if is_xfail:
            jira_match = _CNV_JIRA_PATTERN.search(string=reason)
            return True, reason, jira_match.group() if jira_match else None

        is_jira, jira_id = _is_jira_run_false(decorator=decorator)
        if is_jira:
            return True, f"Jira {jira_id} (product bug, run=False)", jira_id

    return False, "", None


def scan_quarantined_tests(tests_dir: Path) -> list[QuarantinedTest]:
    """Scan test files for quarantined tests using AST analysis.

    Detects two quarantine patterns:
    - ``@pytest.mark.xfail(reason=f"{QUARANTINED}: ...", run=False)``
    - ``@pytest.mark.jira("CNV-XXXXX", run=False)``

    For class-level markers, generates entries for all test methods.

    Args:
        tests_dir: Root directory to scan for test files.

    Returns:
        List of QuarantinedTest entries.
    """
    quarantined: list[QuarantinedTest] = []

    for test_file in tests_dir.rglob("test_*.py"):
        try:
            source = test_file.read_text(encoding="utf-8")
            tree = ast.parse(source=source, filename=str(test_file))
        except SyntaxError, UnicodeDecodeError:
            LOGGER.warning(f"Could not parse {test_file}, skipping quarantine scan")
            continue

        rel_path = str(test_file)

        for node in ast.iter_child_nodes(tree):
            # Class-level quarantine
            if isinstance(node, ast.ClassDef):
                class_quarantined, class_reason, class_jira = _check_decorators(decorators=node.decorator_list)

                test_methods = [
                    item.name
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_")
                ]

                if class_quarantined:
                    for method_name in test_methods:
                        quarantined.append(
                            QuarantinedTest(
                                node_id=f"{rel_path}::{node.name}::{method_name}",
                                reason=class_reason,
                                jira=class_jira,
                            )
                        )
                else:
                    # Check individual methods
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                            is_q, reason, jira = _check_decorators(decorators=item.decorator_list)
                            if is_q:
                                quarantined.append(
                                    QuarantinedTest(
                                        node_id=f"{rel_path}::{node.name}::{item.name}",
                                        reason=reason,
                                        jira=jira,
                                    )
                                )

            # Standalone function-level quarantine
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                is_q, reason, jira = _check_decorators(decorators=node.decorator_list)
                if is_q:
                    quarantined.append(
                        QuarantinedTest(
                            node_id=f"{rel_path}::{node.name}",
                            reason=reason,
                            jira=jira,
                        )
                    )

    LOGGER.info(f"Found {len(quarantined)} quarantined tests")
    return quarantined
