"""Collector for STD placeholder tests with full context.

Extends std_placeholder_stats test discovery to extract docstrings,
markers, fixtures, and Polarion IDs for each placeholder test.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

LOGGER = logging.getLogger(__name__)


@dataclass
class PlaceholderTestDetail:
    """Full context for an STD placeholder test.

    Attributes:
        file_path: Path to the test file relative to the repo root.
        class_name: Enclosing test class name, or None for standalone tests.
        method_name: Test method/function name.
        module_docstring: Module-level docstring (STP link, shared preconditions).
        class_docstring: Class-level docstring (class preconditions).
        test_docstring: Test function docstring (Steps, Expected).
        module_markers: Module-level pytestmark markers.
        class_markers: Markers on the class definition.
        class_fixtures: Fixtures from @pytest.mark.usefixtures on the class.
        test_markers: Markers on the test function.
        polarion_id: Polarion test case ID from @pytest.mark.polarion.
        node_id: Pytest-style node ID.
        rp_name: Dotted ReportPortal item name.
    """

    file_path: str
    class_name: str | None
    method_name: str
    module_docstring: str | None = None
    class_docstring: str | None = None
    test_docstring: str | None = None
    module_markers: list[str] = field(default_factory=list)
    class_markers: list[str] = field(default_factory=list)
    class_fixtures: list[str] = field(default_factory=list)
    test_markers: list[str] = field(default_factory=list)
    polarion_id: str | None = None
    node_id: str = ""
    rp_name: str = ""


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


def _extract_docstring(node: ast.AST) -> str | None:
    """Extract docstring from an AST node.

    Checks whether the first statement in the node's body is an
    ``ast.Expr`` containing a string ``ast.Constant``.

    Args:
        node: An AST module, class, or function definition node.

    Returns:
        The docstring text, or None if no docstring is present.
    """
    body = getattr(node, "body", None)
    if not body:
        return None

    first_stmt = body[0]
    if (
        isinstance(first_stmt, ast.Expr)
        and isinstance(first_stmt.value, ast.Constant)
        and isinstance(first_stmt.value.value, str)
    ):
        return first_stmt.value.value

    return None


def _is_pytest_mark_attr(node: ast.expr) -> tuple[bool, str | None]:
    """Check if an AST node represents ``pytest.mark.MARKER``.

    Args:
        node: An AST expression node (Attribute chain).

    Returns:
        A tuple of (is_pytest_mark, marker_name).
    """
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    ):
        return True, node.attr
    return False, None


def _safe_arg_repr(arg: ast.expr) -> str:
    """Convert a decorator argument AST node to its string representation.

    Uses ``ast.literal_eval`` for simple constant nodes and falls back
    to ``ast.dump`` for complex expressions that cannot be evaluated.

    Args:
        arg: An AST expression node from a decorator's arguments.

    Returns:
        String representation of the argument.
    """
    try:
        return str(ast.literal_eval(arg))
    except ValueError:
        return ast.dump(arg)


def _extract_markers(decorators: list[ast.expr]) -> list[str]:
    """Extract pytest marker names from decorator nodes.

    Handles both bare markers (``@pytest.mark.MARKER``) and called
    markers (``@pytest.mark.MARKER(args)``).

    Args:
        decorators: List of decorator AST expression nodes.

    Returns:
        List of marker strings, e.g. ``["smoke", "polarion(CNV-1234)"]``.
    """
    markers: list[str] = []

    for decorator in decorators:
        if isinstance(decorator, ast.Attribute):
            is_mark, marker_name = _is_pytest_mark_attr(node=decorator)
            if is_mark and marker_name is not None:
                markers.append(marker_name)

        elif isinstance(decorator, ast.Call):
            is_mark, marker_name = _is_pytest_mark_attr(node=decorator.func)
            if is_mark and marker_name is not None:
                args_repr = ", ".join(_safe_arg_repr(arg=arg) for arg in decorator.args)
                if args_repr:
                    markers.append(f"{marker_name}({args_repr})")
                else:
                    markers.append(marker_name)

    return markers


def _extract_usefixtures(decorators: list[ast.expr]) -> list[str]:
    """Extract fixture names from ``@pytest.mark.usefixtures(...)`` decorators.

    Args:
        decorators: List of decorator AST expression nodes.

    Returns:
        List of fixture name strings.
    """
    fixtures: list[str] = []

    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue

        is_mark, marker_name = _is_pytest_mark_attr(node=decorator.func)
        if is_mark and marker_name == "usefixtures":
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    fixtures.append(arg.value)

    return fixtures


def _extract_polarion_id(decorators: list[ast.expr]) -> str | None:
    """Extract Polarion test case ID from ``@pytest.mark.polarion("CNV-XXXXX")``.

    Args:
        decorators: List of decorator AST expression nodes.

    Returns:
        The Polarion ID string, or None if not found.
    """
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue

        is_mark, marker_name = _is_pytest_mark_attr(node=decorator.func)
        if is_mark and marker_name == "polarion":
            if (
                len(decorator.args) == 1
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                return decorator.args[0].value

    return None


def _extract_marker_name_from_element(element: ast.expr) -> str | None:
    """Extract a marker name from a single pytestmark list element.

    Handles both ``pytest.mark.MARKER`` (Attribute) and
    ``pytest.mark.MARKER(...)`` (Call) forms.

    Args:
        element: An AST expression node from the pytestmark list.

    Returns:
        The marker name string, or None if not a pytest marker.
    """
    if isinstance(element, ast.Attribute):
        is_mark, marker_name = _is_pytest_mark_attr(node=element)
        if is_mark:
            return marker_name

    elif isinstance(element, ast.Call):
        is_mark, marker_name = _is_pytest_mark_attr(node=element.func)
        if is_mark:
            return marker_name

    return None


def _extract_module_markers(tree: ast.Module) -> list[str]:
    """Extract module-level ``pytestmark`` markers from the AST module.

    Handles both single marker assignment and list of markers::

        pytestmark = pytest.mark.usefixtures("my_fixture")
        pytestmark = [pytest.mark.smoke, pytest.mark.tier1]

    Args:
        tree: The parsed AST module.

    Returns:
        List of marker name strings.
    """
    markers: list[str] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "pytestmark"):
                continue

            if isinstance(node.value, ast.List):
                for element in node.value.elts:
                    marker_name = _extract_marker_name_from_element(element=element)
                    if marker_name is not None:
                        markers.append(marker_name)
            else:
                marker_name = _extract_marker_name_from_element(element=node.value)
                if marker_name is not None:
                    markers.append(marker_name)

    return markers


def collect_placeholder_details(tests_dir: Path) -> list[PlaceholderTestDetail]:
    """Collect all placeholder tests with full context from a tests directory.

    Re-parses each file discovered by ``scan_placeholder_tests`` to extract
    docstrings, markers, fixtures, and Polarion IDs for every placeholder test.

    Args:
        tests_dir: Path to the tests directory to scan.

    Returns:
        List of ``PlaceholderTestDetail`` objects sorted by ``node_id``.
    """
    from scripts.std_placeholder_stats.std_placeholder_stats import scan_placeholder_tests  # noqa: PLC0415

    placeholder_files = scan_placeholder_tests(tests_dir=tests_dir)
    details: list[PlaceholderTestDetail] = []

    for placeholder_file in placeholder_files:
        file_path = Path(placeholder_file.file_path)
        full_path = tests_dir.parent / file_path

        try:
            source = full_path.read_text(encoding="utf-8")
            tree = ast.parse(source=source)
        except (OSError, SyntaxError) as exc:
            LOGGER.warning(f"Failed to parse {full_path}: {exc}")
            continue

        module_docstring = _extract_docstring(node=tree)
        module_markers = _extract_module_markers(tree=tree)

        # Build lookup of class nodes and standalone function nodes
        class_nodes: dict[str, ast.ClassDef] = {}
        standalone_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_nodes[node.name] = node
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                standalone_functions[node.name] = node

        # Process class-based placeholder tests
        for placeholder_class in placeholder_file.classes:
            class_node = class_nodes.get(placeholder_class.name)
            if class_node is None:
                continue

            class_docstring = _extract_docstring(node=class_node)
            class_markers = _extract_markers(decorators=class_node.decorator_list)
            class_fixtures = _extract_usefixtures(decorators=class_node.decorator_list)

            # Build method lookup for this class
            method_nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {
                method.name: method
                for method in class_node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            }

            for method_name in placeholder_class.test_methods:
                method_node = method_nodes.get(method_name)
                test_docstring = _extract_docstring(node=method_node) if method_node else None
                test_markers = _extract_markers(decorators=method_node.decorator_list) if method_node else []
                polarion_id = _extract_polarion_id(decorators=method_node.decorator_list) if method_node else None

                node_id = f"{placeholder_file.file_path}::{placeholder_class.name}::{method_name}"
                rp_name = node_id_to_rp_name(node_id=node_id)

                details.append(
                    PlaceholderTestDetail(
                        file_path=placeholder_file.file_path,
                        class_name=placeholder_class.name,
                        method_name=method_name,
                        module_docstring=module_docstring,
                        class_docstring=class_docstring,
                        test_docstring=test_docstring,
                        module_markers=module_markers,
                        class_markers=class_markers,
                        class_fixtures=class_fixtures,
                        test_markers=test_markers,
                        polarion_id=polarion_id,
                        node_id=node_id,
                        rp_name=rp_name,
                    )
                )

        # Process standalone placeholder tests
        for test_name in placeholder_file.standalone_tests:
            func_node = standalone_functions.get(test_name)
            test_docstring = _extract_docstring(node=func_node) if func_node else None
            test_markers = _extract_markers(decorators=func_node.decorator_list) if func_node else []
            polarion_id = _extract_polarion_id(decorators=func_node.decorator_list) if func_node else None

            node_id = f"{placeholder_file.file_path}::{test_name}"
            rp_name = node_id_to_rp_name(node_id=node_id)

            details.append(
                PlaceholderTestDetail(
                    file_path=placeholder_file.file_path,
                    class_name=None,
                    method_name=test_name,
                    module_docstring=module_docstring,
                    class_docstring=None,
                    test_docstring=test_docstring,
                    module_markers=module_markers,
                    class_markers=[],
                    class_fixtures=[],
                    test_markers=test_markers,
                    polarion_id=polarion_id,
                    node_id=node_id,
                    rp_name=rp_name,
                )
            )

    LOGGER.info(f"Collected {len(details)} placeholder tests from {tests_dir}")
    return sorted(details, key=lambda detail: detail.node_id)
