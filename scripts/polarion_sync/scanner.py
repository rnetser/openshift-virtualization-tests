"""Scan test files for new tests missing Polarion markers.

Detects test functions/methods that lack a ``@pytest.mark.polarion()``
marker.  Scope can be narrowed to files changed in the most recent
commit so the scanner runs fast on every merge.
"""

from __future__ import annotations

import ast
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from scripts.polarion_sync.jira_linker import extract_jira_ids

LOGGER = logging.getLogger(__name__)


@dataclass
class UnlinkedTest:
    """A test function that has no Polarion ID yet."""

    file: Path
    class_name: str | None
    test_name: str
    docstring: str
    node_id: str
    # Line number of the *def* statement (1-indexed) — needed by the injector
    lineno: int
    # Whether the test is STD-only (__test__ = False) — no implementation yet
    is_std_only: bool = False
    # Existing markers attached to the test (informational)
    markers: list[str] = field(default_factory=list)
    # Jira issue keys found in docstrings (test, class, module)
    jira_ids: list[str] = field(default_factory=list)
    # Polarion IDs from other tests in the same file (for requirement fallback)
    sibling_polarion_ids: list[str] = field(default_factory=list)
    # Human-readable parametrize info extracted from decorators
    parametrize_info: list[str] = field(default_factory=list)


def _changed_test_files(repo_root: Path) -> list[Path]:
    """Return ``test_*.py`` files added or modified in the last commit."""
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "--name-only", "--diff-filter=AM"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return [
        repo_root / path
        for path in result.stdout.splitlines()
        if path.startswith("tests/") and path.endswith(".py") and "/test_" in path
    ]


def _pr_changed_test_files(repo_root: Path, pr_number: int, gh_repo: str | None = None) -> list[Path]:
    """Return ``test_*.py`` files added or modified in a GitHub PR.

    Args:
        repo_root: path to the repository root.
        pr_number: GitHub PR number.
        gh_repo: GitHub repo in ``owner/name`` format (e.g. ``RedHatQE/openshift-virtualization-tests``).
            When None, ``gh`` auto-detects from the current repo.
    """
    cmd = ["gh", "pr", "diff", str(pr_number), "--name-only"]
    if gh_repo:
        cmd.extend(["--repo", gh_repo])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        LOGGER.warning(f"Failed to fetch PR #{pr_number} diff: {result.stderr}")
        return []
    return [
        repo_root / path
        for path in result.stdout.splitlines()
        if path.startswith("tests/") and path.endswith(".py") and "/test_" in path
    ]


def _contains_polarion_call(node: ast.AST) -> bool:
    """Walk *node* looking for a ``pytest.mark.polarion(...)`` call anywhere."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if child.func.attr == "polarion":
                return True
    return False


def _has_polarion_marker(decorators: list[ast.expr]) -> bool:
    """Check whether any decorator is ``@pytest.mark.polarion(...)``.

    Also detects polarion markers nested inside ``pytest.mark.parametrize``
    arguments (e.g. ``pytest.param(..., marks=[pytest.mark.polarion(...)])``).
    """
    for decorator in decorators:
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
            if decorator.func.attr == "polarion":
                return True
            # Check inside parametrize args for nested pytest.mark.polarion
            if decorator.func.attr == "parametrize":
                for arg in decorator.args:
                    if _contains_polarion_call(arg):
                        return True
                for kw in decorator.keywords:
                    if _contains_polarion_call(kw.value):
                        return True
    return False


def _extract_polarion_id(decorators: list[ast.expr]) -> str | None:
    """Extract the Polarion ID from a ``@pytest.mark.polarion("CNV-XXXXX")`` decorator."""
    for decorator in decorators:
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
            if decorator.func.attr == "polarion" and decorator.args:
                arg = decorator.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return arg.value
    return None


def _extract_markers(decorators: list[ast.expr]) -> list[str]:
    """Extract pytest marker names from decorators."""
    markers: list[str] = []
    for decorator in decorators:
        if isinstance(decorator, ast.Attribute) and decorator.attr not in ("fixture",):
            markers.append(decorator.attr)
        elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
            markers.append(decorator.func.attr)
    return markers


def _extract_parametrize_info(decorators: list[ast.expr]) -> list[str]:
    """Extract human-readable parametrize info from test decorators.

    For each ``@pytest.mark.parametrize(...)`` decorator, builds a string
    like ``"Parametrized: param1, param2 [case1, case2]"``.

    Args:
        decorators: the decorator_list from an AST function node.

    Returns:
        One entry per parametrize decorator found.
    """
    results: list[str] = []
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not (isinstance(func, ast.Attribute) and func.attr == "parametrize"):
            continue
        if not decorator.args:
            continue

        # First arg is the parameter names string
        first_arg = decorator.args[0]
        if not (isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str)):
            continue
        param_names = first_arg.value

        # Second arg is the values list/tuple
        ids: list[str] = []
        if len(decorator.args) >= 2:
            values_arg = decorator.args[1]
            if isinstance(values_arg, (ast.List, ast.Tuple)):
                for elt in values_arg.elts:
                    # Check for pytest.param(..., id="...")
                    if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Attribute) and elt.func.attr == "param":
                        for kw in elt.keywords:
                            if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                                ids.append(str(kw.value.value))
                                break
                    elif isinstance(elt, ast.Constant):
                        ids.append(str(elt.value))

        if ids:
            results.append(f"Parametrized: {param_names} [{', '.join(ids)}]")
        else:
            results.append(f"Parametrized: {param_names}")
    return results


def _module_path(file: Path, repo_root: Path) -> str:
    """Convert a file path to a dotted module path relative to *repo_root*."""
    relative = file.relative_to(repo_root).with_suffix("")
    return str(relative).replace("/", ".")


def _is_dunder_test_false(node: ast.stmt) -> bool:
    """Check whether *node* is an ``__test__ = False`` assignment."""
    if not isinstance(node, ast.Assign):
        return False
    if len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Name) or target.id != "__test__":
        return False
    return isinstance(node.value, ast.Constant) and node.value.value is False


def _collect_jira_ids(
    test_docstring: str,
    class_docstring: str,
    module_docstring: str,
) -> list[str]:
    """Extract and deduplicate Jira IDs from all docstring levels.

    Args:
        test_docstring: the test function's docstring.
        class_docstring: the enclosing class's docstring (empty if none).
        module_docstring: the module-level docstring.

    Returns:
        Deduplicated list of Jira keys, preserving order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for docstring in (test_docstring, class_docstring, module_docstring):
        for jira_id in extract_jira_ids(docstring=docstring):
            if jira_id not in seen:
                seen.add(jira_id)
                result.append(jira_id)
    return result


def _extract_polarion_ids_from_parametrize(decorators: list[ast.expr]) -> list[str]:
    """Extract Polarion IDs from pytest.param(marks=[...]) inside parametrize decorators."""
    polarion_ids: list[str] = []
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not (isinstance(func, ast.Attribute) and func.attr == "parametrize"):
            continue
        for node in ast.walk(decorator):
            if not isinstance(node, ast.Call):
                continue
            call_func = node.func
            if isinstance(call_func, ast.Attribute) and call_func.attr == "polarion":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    polarion_ids.append(node.args[0].value)
    return polarion_ids


def _collect_sibling_polarion_ids(tree: ast.Module) -> list[str]:
    """Collect Polarion IDs from all tests in the AST that already have markers."""
    polarion_ids: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                    polarion_id = _extract_polarion_id(decorators=item.decorator_list)
                    if polarion_id:
                        polarion_ids.append(polarion_id)
                    else:
                        polarion_ids.extend(_extract_polarion_ids_from_parametrize(decorators=item.decorator_list))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            polarion_id = _extract_polarion_id(decorators=node.decorator_list)
            if polarion_id:
                polarion_ids.append(polarion_id)
            else:
                polarion_ids.extend(_extract_polarion_ids_from_parametrize(decorators=node.decorator_list))
    return polarion_ids


def scan_file(file: Path, repo_root: Path) -> list[UnlinkedTest]:
    """Parse *file* and return tests that lack a Polarion marker."""
    source = file.read_text()

    # Skip files that explicitly opt out of Polarion ID enforcement
    if "noqa: PID001" in source:
        LOGGER.info(f"  Skipping {file.relative_to(repo_root)} — has noqa: PID001")
        return []

    tree = ast.parse(source=source, filename=str(file))
    mod_path = _module_path(file=file, repo_root=repo_root)
    results: list[UnlinkedTest] = []
    module_docstring = ast.get_docstring(tree) or ""
    sibling_polarion_ids = _collect_sibling_polarion_ids(tree=tree)

    # Detect module-level __test__ = False
    module_std_only = any(_is_dunder_test_false(node=stmt) for stmt in tree.body)

    # Collect function-level func.__test__ = False assignments at module level
    func_std_only_names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "__test__"
                and isinstance(target.value, ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is False
            ):
                func_std_only_names.add(target.value.id)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            class_std_only = any(_is_dunder_test_false(node=stmt) for stmt in node.body)
            class_docstring = ast.get_docstring(node) or ""
            is_std_only = module_std_only or class_std_only

            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                    if _has_polarion_marker(decorators=item.decorator_list):
                        continue
                    docstring = ast.get_docstring(item)
                    node_id = f"{mod_path}::{class_name}::{item.name}"
                    jira_ids = _collect_jira_ids(
                        test_docstring=docstring or "",
                        class_docstring=class_docstring,
                        module_docstring=module_docstring,
                    )
                    results.append(
                        UnlinkedTest(
                            file=file,
                            class_name=class_name,
                            test_name=item.name,
                            docstring=docstring or "",
                            node_id=node_id,
                            lineno=item.lineno,
                            is_std_only=is_std_only,
                            markers=_extract_markers(decorators=item.decorator_list),
                            jira_ids=jira_ids,
                            sibling_polarion_ids=sibling_polarion_ids,
                            parametrize_info=_extract_parametrize_info(decorators=item.decorator_list),
                        )
                    )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            if _has_polarion_marker(decorators=node.decorator_list):
                continue
            docstring = ast.get_docstring(node)
            is_std_only = module_std_only or node.name in func_std_only_names
            node_id = f"{mod_path}::{node.name}"
            jira_ids = _collect_jira_ids(
                test_docstring=docstring or "",
                class_docstring="",
                module_docstring=module_docstring,
            )
            results.append(
                UnlinkedTest(
                    file=file,
                    class_name=None,
                    test_name=node.name,
                    docstring=docstring or "",
                    node_id=node_id,
                    lineno=node.lineno,
                    is_std_only=is_std_only,
                    markers=_extract_markers(decorators=node.decorator_list),
                    jira_ids=jira_ids,
                    sibling_polarion_ids=sibling_polarion_ids,
                    parametrize_info=_extract_parametrize_info(decorators=node.decorator_list),
                )
            )

    return results


def scan_changed(
    repo_root: Path,
    pr_number: int | None = None,
    gh_repo: str | None = None,
) -> list[UnlinkedTest]:
    """Scan files changed in the last commit or a specific PR for unlinked tests."""
    if pr_number:
        changed_files = _pr_changed_test_files(repo_root=repo_root, pr_number=pr_number, gh_repo=gh_repo)
        LOGGER.info(f"Scanning {len(changed_files)} changed test file(s) from PR #{pr_number}")
    else:
        changed_files = _changed_test_files(repo_root=repo_root)
        LOGGER.info(f"Scanning {len(changed_files)} changed test file(s)")
    unlinked: list[UnlinkedTest] = []
    for file in changed_files:
        if file.exists():
            found = scan_file(file=file, repo_root=repo_root)
            if found:
                LOGGER.info(f"  {file.relative_to(repo_root)}: {len(found)} test(s) without Polarion ID")
            unlinked.extend(found)
    return unlinked


def scan_all(repo_root: Path) -> list[UnlinkedTest]:
    """Scan the entire ``tests/`` tree for unlinked tests."""
    tests_dir = repo_root / "tests"
    unlinked: list[UnlinkedTest] = []
    for file in sorted(tests_dir.rglob("test_*.py")):
        found = scan_file(file=file, repo_root=repo_root)
        unlinked.extend(found)
    LOGGER.info(f"Found {len(unlinked)} test(s) without Polarion ID across all test files")
    return unlinked
