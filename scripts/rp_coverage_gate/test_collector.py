"""Test collector for coverage gate.

Collects all tests from the repository — both automated (via pytest --collect-only)
and unautomated STD placeholders (via std_placeholder_stats).
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def node_id_to_rp_name(node_id: str) -> str:
    """Convert a pytest node ID to ReportPortal dotted name format.

    Transforms path separators and pytest delimiters into dots while
    preserving parametrize suffixes.

    Args:
        node_id: Pytest-style node ID, e.g.
            ``tests/foo/test_bar.py::TestClass::test_method[param]``.

    Returns:
        Dotted ReportPortal name, e.g.
            ``tests.foo.test_bar.TestClass.test_method[param]``.
    """
    param_suffix = ""
    base = node_id
    bracket_index = node_id.find("[")
    if bracket_index != -1:
        param_suffix = node_id[bracket_index:]
        base = node_id[:bracket_index]

    base = base.replace(".py", "")
    base = base.replace("/", ".")
    base = base.replace("::", ".")

    return base + param_suffix


def _parse_pytest_collect_output(stdout: str) -> list[str]:
    """Parse pytest ``--collect-only -q`` output to extract test node IDs.

    Each line containing ``::`` is treated as a test node ID. Summary lines
    (e.g., ``X tests collected in Ys``) and empty lines are skipped.

    Args:
        stdout: Raw stdout from ``pytest --collect-only -q``.

    Returns:
        List of pytest node IDs.
    """
    node_ids: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if "::" in stripped:
            node_ids.append(stripped)
    return node_ids


def collect_all_tests(tests_dir: Path) -> tuple[list[str], list[str]]:
    """Collect both automated and unautomated test node IDs.

    Automated tests are collected via ``pytest --collect-only``.
    Unautomated tests are collected via std_placeholder_stats AST scanning.

    The OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH env var is set to 'amd64'
    to allow collection without a cluster connection.

    Args:
        tests_dir: Path to the tests directory to scan.

    Returns:
        Tuple of (automated_node_ids, unautomated_node_ids).
    """
    env = os.environ.copy()
    env["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = "amd64"

    result = subprocess.run(
        ["uv", "run", "pytest", "--collect-only", "-q", str(tests_dir)],
        capture_output=True,
        text=True,
        env=env,
    )
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

    return automated_ids, unautomated_ids
