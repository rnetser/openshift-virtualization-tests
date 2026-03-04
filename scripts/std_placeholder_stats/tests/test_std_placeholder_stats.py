"""Unit tests for STD Placeholder Stats Generator.

Tests cover all public functions in std_placeholder_stats.py including
AST-based analysis functions and the directory scanner.

Generated-by: Claude
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import ClassVar

import pytest

from scripts.std_placeholder_stats.std_placeholder_stats import (
    PlaceholderClass,
    PlaceholderFile,
    _format_placeholder_lines,
    _statements_have_test_false,
    count_placeholder_tests,
    get_test_methods_from_class,
    output_json,
    output_text,
    scan_placeholder_tests,
    separator,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_FALSE_MARKER = "__test__ = False"

# ---------------------------------------------------------------------------
# Source code fragments for AST-based tests
# ---------------------------------------------------------------------------

SOURCE_MODULE_TEST_FALSE = f"""\
{TEST_FALSE_MARKER}

class TestFoo:
    def test_bar(self):
        pass
"""

SOURCE_NO_TEST_ASSIGNMENT = """\
class TestFoo:
    def test_bar(self):
        pass
"""

SOURCE_CLASS_TEST_FALSE = f"""\
class TestFoo:
    {TEST_FALSE_MARKER}

    def test_bar(self):
        pass

    def test_baz(self):
        pass
"""

SOURCE_FUNCTION_TEST_FALSE = f"""\
def test_standalone():
    pass

test_standalone.{TEST_FALSE_MARKER}
"""

SOURCE_FUNCTION_TEST_FALSE_DIFFERENT_NAME = f"""\
def test_alpha():
    pass

test_alpha.{TEST_FALSE_MARKER}

def test_beta():
    pass
"""

SOURCE_STANDALONE_FUNCTION = """\
def test_standalone():
    pass
"""

SOURCE_METHOD_TEST_FALSE = f"""\
class TestFoo:
    def test_alpha(self):
        pass

    test_alpha.{TEST_FALSE_MARKER}

    def test_beta(self):
        pass
"""

SOURCE_TWO_METHODS = """\
class TestFoo:
    def test_alpha(self):
        pass

    def test_beta(self):
        pass
"""

SOURCE_CLASS_WITH_MIXED_METHODS = f"""\
class TestFoo:
    {TEST_FALSE_MARKER}

    def __init__(self):
        pass

    def helper_method(self):
        pass

    def test_one(self):
        pass

    def test_two(self):
        pass

    def setup_method(self):
        pass
"""

SOURCE_CLASS_NO_TEST_METHODS = """\
class TestFoo:
    def __init__(self):
        pass

    def helper(self):
        pass
"""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_first_class_node(source: str) -> ast.ClassDef:
    """Parse source and return the first ClassDef node.

    Args:
        source: Python source code containing a class definition.

    Returns:
        The first ast.ClassDef found in the parsed source.
    """
    tree = ast.parse(source=source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            return node
    raise ValueError("No class definition found in source")


def _find_placeholder_file(result: list[PlaceholderFile], file_path: str) -> PlaceholderFile:
    """Find a PlaceholderFile by file_path in scan results.

    Args:
        result: List of PlaceholderFile objects from scan_placeholder_tests.
        file_path: The file path to search for.

    Returns:
        The matching PlaceholderFile.

    Raises:
        AssertionError: If no matching PlaceholderFile is found.
    """
    placeholder = next(
        (pf for pf in result if pf.file_path == file_path),
        None,
    )
    assert placeholder is not None, (
        f"Expected PlaceholderFile for '{file_path}', got file_paths: {[pf.file_path for pf in result]}"
    )
    return placeholder


def _find_placeholder_class(placeholder: PlaceholderFile, class_name: str) -> PlaceholderClass:
    """Find a PlaceholderClass by name in a PlaceholderFile.

    Args:
        placeholder: The PlaceholderFile to search in.
        class_name: The class name to search for.

    Returns:
        The matching PlaceholderClass.

    Raises:
        AssertionError: If no matching PlaceholderClass is found.
    """
    found = next(
        (cls for cls in placeholder.classes if cls.name == class_name),
        None,
    )
    assert found is not None, f"Expected class '{class_name}', got: {[cls.name for cls in placeholder.classes]}"
    return found


def _create_test_file(directory: Path, filename: str, content: str) -> Path:
    """Create a test file in the given directory.

    Args:
        directory: Parent directory for the file.
        filename: Name of the test file.
        content: Python source content for the file.

    Returns:
        Path to the created file.
    """
    file_path = directory / filename
    file_path.write_text(data=content, encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tests_dir(tmp_path: Path) -> Path:
    """Provide a temporary 'tests' directory for scan_placeholder_tests."""
    directory = tmp_path / "tests"
    directory.mkdir()
    return directory


# ===========================================================================
# Tests for _statements_have_test_false() — module-level patterns
# ===========================================================================


class TestStatementsHaveTestFalseModule:
    """Tests for _statements_have_test_false() with module-level statements."""

    def test_returns_true_when_module_has_test_false(self) -> None:
        """_statements_have_test_false() detects __test__ = False at module level."""
        tree = ast.parse(source=SOURCE_MODULE_TEST_FALSE)
        assert _statements_have_test_false(statements=tree.body) is True

    def test_returns_false_when_no_test_assignment(self) -> None:
        """_statements_have_test_false() returns False with no __test__ assignment."""
        tree = ast.parse(source=SOURCE_NO_TEST_ASSIGNMENT)
        assert _statements_have_test_false(statements=tree.body) is False

    def test_ignores_class_level_test_false(self) -> None:
        """_statements_have_test_false() ignores __test__ = False inside classes."""
        tree = ast.parse(source=SOURCE_CLASS_TEST_FALSE)
        assert _statements_have_test_false(statements=tree.body) is False


# ===========================================================================
# Tests for _statements_have_test_false() — class-level patterns
# ===========================================================================


class TestStatementsHaveTestFalseClass:
    """Tests for _statements_have_test_false() with class body statements."""

    def test_returns_true_when_class_has_test_false(self) -> None:
        """_statements_have_test_false() detects __test__ = False in class body."""
        class_node = _get_first_class_node(source=SOURCE_CLASS_TEST_FALSE)
        assert _statements_have_test_false(statements=class_node.body) is True

    def test_returns_false_when_no_test_assignment(self) -> None:
        """_statements_have_test_false() returns False with no __test__ assignment."""
        class_node = _get_first_class_node(source=SOURCE_NO_TEST_ASSIGNMENT)
        assert _statements_have_test_false(statements=class_node.body) is False

    def test_detects_test_false_in_class_with_mixed_methods(self) -> None:
        """_statements_have_test_false() detects __test__ = False even with non-test methods present."""
        class_node = _get_first_class_node(source=SOURCE_CLASS_WITH_MIXED_METHODS)
        assert _statements_have_test_false(statements=class_node.body) is True


# ===========================================================================
# Tests for _statements_have_test_false() — function-level patterns
# ===========================================================================


class TestStatementsHaveTestFalseFunction:
    """Tests for _statements_have_test_false() with function-level attribute assignments."""

    def test_returns_true_when_function_has_test_false(self) -> None:
        """_statements_have_test_false() detects func.__test__ = False at module level."""
        tree = ast.parse(source=SOURCE_FUNCTION_TEST_FALSE)
        assert _statements_have_test_false(statements=tree.body, target_name="test_standalone") is True

    def test_returns_false_for_non_matching_function_name(self) -> None:
        """_statements_have_test_false() returns False for a different function name."""
        tree = ast.parse(source=SOURCE_FUNCTION_TEST_FALSE)
        assert _statements_have_test_false(statements=tree.body, target_name="test_other") is False

    def test_returns_false_when_no_test_assignment_exists(self) -> None:
        """_statements_have_test_false() returns False with no __test__ assignment."""
        tree = ast.parse(source=SOURCE_STANDALONE_FUNCTION)
        assert _statements_have_test_false(statements=tree.body, target_name="test_standalone") is False

    def test_matches_correct_function_among_multiple(self) -> None:
        """_statements_have_test_false() only matches the specific function name."""
        tree = ast.parse(source=SOURCE_FUNCTION_TEST_FALSE_DIFFERENT_NAME)
        assert _statements_have_test_false(statements=tree.body, target_name="test_alpha") is True
        assert _statements_have_test_false(statements=tree.body, target_name="test_beta") is False


# ===========================================================================
# Tests for _statements_have_test_false() — method-level patterns
# ===========================================================================


class TestStatementsHaveTestFalseMethod:
    """Tests for _statements_have_test_false() with method-level attribute assignments."""

    def test_returns_true_when_method_has_test_false(self) -> None:
        """_statements_have_test_false() detects method.__test__ = False in class body."""
        class_node = _get_first_class_node(source=SOURCE_METHOD_TEST_FALSE)
        assert _statements_have_test_false(statements=class_node.body, target_name="test_alpha") is True

    def test_returns_false_for_non_matching_method_name(self) -> None:
        """_statements_have_test_false() returns False for a different method name."""
        class_node = _get_first_class_node(source=SOURCE_METHOD_TEST_FALSE)
        assert _statements_have_test_false(statements=class_node.body, target_name="test_beta") is False

    def test_returns_false_when_no_test_assignment_exists(self) -> None:
        """_statements_have_test_false() returns False with no __test__ assignment."""
        class_node = _get_first_class_node(source=SOURCE_TWO_METHODS)
        assert _statements_have_test_false(statements=class_node.body, target_name="test_alpha") is False


# ===========================================================================
# Tests for get_test_methods_from_class()
# ===========================================================================


class TestGetTestMethodsFromClass:
    """Tests for the get_test_methods_from_class() function."""

    def test_returns_raw_test_method_names(self) -> None:
        """get_test_methods_from_class() returns raw test method names."""
        class_node = _get_first_class_node(source=SOURCE_CLASS_TEST_FALSE)
        result = get_test_methods_from_class(class_node=class_node)
        assert result == ["test_bar", "test_baz"], f"Expected ['test_bar', 'test_baz'], got: {result}"

    def test_excludes_non_test_methods(self) -> None:
        """get_test_methods_from_class() excludes helper methods, __init__, etc."""
        class_node = _get_first_class_node(source=SOURCE_CLASS_WITH_MIXED_METHODS)
        result = get_test_methods_from_class(class_node=class_node)
        assert result == ["test_one", "test_two"], f"Expected ['test_one', 'test_two'], got: {result}"

    def test_returns_empty_list_for_no_test_methods(self) -> None:
        """get_test_methods_from_class() returns empty list when no test_ methods."""
        class_node = _get_first_class_node(source=SOURCE_CLASS_NO_TEST_METHODS)
        result = get_test_methods_from_class(class_node=class_node)
        assert result == [], f"Expected empty list, got: {result}"


# ===========================================================================
# Tests for scan_placeholder_tests()
# ===========================================================================


class TestScanPlaceholderTests:
    """Tests for the scan_placeholder_tests() function."""

    def test_module_level_test_false_reports_all_classes_and_functions(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() reports all classes and functions when module has __test__ = False."""
        _create_test_file(
            directory=tests_dir,
            filename="test_example.py",
            content=(
                f"{TEST_FALSE_MARKER}\n\n"
                "class TestFoo:\n"
                "    def test_bar(self):\n"
                "        pass\n\n"
                "class TestBaz:\n"
                "    def test_qux(self):\n"
                "        pass\n"
            ),
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result, "Expected non-empty result list"
        placeholder = _find_placeholder_file(result=result, file_path="tests/test_example.py")
        class_names = [cls.name for cls in placeholder.classes]
        assert "TestFoo" in class_names, f"Expected 'TestFoo' in class names, got: {class_names}"
        assert "TestBaz" in class_names, f"Expected 'TestBaz' in class names, got: {class_names}"
        foo_class = _find_placeholder_class(placeholder=placeholder, class_name="TestFoo")
        assert "test_bar" in foo_class.test_methods, (
            f"Expected 'test_bar' in TestFoo methods, got: {foo_class.test_methods}"
        )
        baz_class = _find_placeholder_class(placeholder=placeholder, class_name="TestBaz")
        assert "test_qux" in baz_class.test_methods, (
            f"Expected 'test_qux' in TestBaz methods, got: {baz_class.test_methods}"
        )

    def test_module_level_test_false_reports_standalone_functions(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() reports standalone test functions under module-level __test__ = False."""
        _create_test_file(
            directory=tests_dir,
            filename="test_funcs.py",
            content=f"{TEST_FALSE_MARKER}\n\ndef test_alpha():\n    pass\n\ndef test_beta():\n    pass\n",
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result, "Expected non-empty result list"
        placeholder = _find_placeholder_file(result=result, file_path="tests/test_funcs.py")
        assert "test_alpha" in placeholder.standalone_tests, (
            f"Expected 'test_alpha' in standalone_tests, got: {placeholder.standalone_tests}"
        )
        assert "test_beta" in placeholder.standalone_tests, (
            f"Expected 'test_beta' in standalone_tests, got: {placeholder.standalone_tests}"
        )

    def test_class_level_test_false_reports_class_and_methods(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() reports class and its methods when class has __test__ = False."""
        _create_test_file(
            directory=tests_dir,
            filename="test_cls.py",
            content=(
                "class TestFoo:\n"
                f"    {TEST_FALSE_MARKER}\n\n"
                "    def test_bar(self):\n"
                "        pass\n\n"
                "    def test_baz(self):\n"
                "        pass\n"
            ),
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result, "Expected non-empty result list"
        placeholder = _find_placeholder_file(result=result, file_path="tests/test_cls.py")
        assert placeholder.classes, "Expected at least one PlaceholderClass"
        foo_class = _find_placeholder_class(placeholder=placeholder, class_name="TestFoo")
        assert "test_bar" in foo_class.test_methods, (
            f"Expected 'test_bar' in TestFoo methods, got: {foo_class.test_methods}"
        )
        assert "test_baz" in foo_class.test_methods, (
            f"Expected 'test_baz' in TestFoo methods, got: {foo_class.test_methods}"
        )

    def test_method_level_test_false_reports_only_that_method(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() reports only the specific method with __test__ = False."""
        _create_test_file(
            directory=tests_dir,
            filename="test_meth.py",
            content=(
                "class TestFoo:\n"
                "    def test_alpha(self):\n"
                "        pass\n\n"
                f"    test_alpha.{TEST_FALSE_MARKER}\n\n"
                "    def test_beta(self):\n"
                "        pass\n"
            ),
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result, "Expected non-empty result list"
        placeholder = _find_placeholder_file(result=result, file_path="tests/test_meth.py")
        foo_class = _find_placeholder_class(placeholder=placeholder, class_name="TestFoo")
        assert "test_alpha" in foo_class.test_methods, (
            f"Expected 'test_alpha' in TestFoo methods, got: {foo_class.test_methods}"
        )
        assert "test_beta" not in foo_class.test_methods, (
            f"Unexpected 'test_beta' found in TestFoo methods: {foo_class.test_methods}"
        )

    def test_function_level_test_false_reports_only_that_function(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() reports only the function with func.__test__ = False."""
        _create_test_file(
            directory=tests_dir,
            filename="test_func.py",
            content=f"def test_alpha():\n    pass\n\ntest_alpha.{TEST_FALSE_MARKER}\n\ndef test_beta():\n    pass\n",
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result, "Expected non-empty result list"
        placeholder = _find_placeholder_file(result=result, file_path="tests/test_func.py")
        assert "test_alpha" in placeholder.standalone_tests, (
            f"Expected 'test_alpha' in standalone_tests, got: {placeholder.standalone_tests}"
        )
        assert "test_beta" not in placeholder.standalone_tests, (
            f"Unexpected 'test_beta' found in standalone_tests: {placeholder.standalone_tests}"
        )

    def test_skips_files_without_test_false(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() skips files that do not contain __test__ = False."""
        _create_test_file(
            directory=tests_dir,
            filename="test_normal.py",
            content="class TestFoo:\n    def test_bar(self):\n        assert True\n",
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result == []

    def test_handles_syntax_errors_gracefully(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() logs warning and continues on syntax errors."""
        _create_test_file(
            directory=tests_dir,
            filename="test_broken.py",
            content=f"{TEST_FALSE_MARKER}\n\ndef this is not valid python:\n",
        )
        _create_test_file(
            directory=tests_dir,
            filename="test_valid.py",
            content=f"{TEST_FALSE_MARKER}\n\nclass TestGood:\n    def test_pass(self):\n        pass\n",
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        file_paths = [pf.file_path for pf in result]
        assert "tests/test_broken.py" not in file_paths, f"Unexpected 'tests/test_broken.py' in result: {file_paths}"
        assert "tests/test_valid.py" in file_paths, f"Expected 'tests/test_valid.py' in result, got: {file_paths}"

    def test_returns_empty_list_when_no_test_files(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() returns empty list when no test files exist."""
        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result == []

    def test_scans_subdirectories_recursively(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() finds test files in nested subdirectories."""
        sub_dir = tests_dir / "network" / "ipv6"
        sub_dir.mkdir(parents=True)
        _create_test_file(
            directory=sub_dir,
            filename="test_deep.py",
            content=f"{TEST_FALSE_MARKER}\n\nclass TestDeep:\n    def test_nested(self):\n        pass\n",
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result, "Expected at least one entry from nested test file"
        file_paths = [pf.file_path for pf in result]
        assert any("test_deep.py" in path for path in file_paths), (
            f"Expected a file_path containing 'test_deep.py' in results, got: {file_paths}"
        )

    def test_ignores_non_test_files(self, tests_dir: Path) -> None:
        """scan_placeholder_tests() only processes files matching test_*.py pattern."""
        _create_test_file(
            directory=tests_dir,
            filename="conftest.py",
            content=f"{TEST_FALSE_MARKER}\n\ndef fixture():\n    pass\n",
        )
        _create_test_file(
            directory=tests_dir,
            filename="helper.py",
            content=f"{TEST_FALSE_MARKER}\n\ndef helper():\n    pass\n",
        )

        result = scan_placeholder_tests(tests_dir=tests_dir)

        assert result == []


# ===========================================================================
# Tests for output_text() and output_json()
# ===========================================================================


class TestOutputFunctions:
    """Tests for output_text() and output_json() functions."""

    SAMPLE_PLACEHOLDER_FILES: ClassVar[list[PlaceholderFile]] = [
        PlaceholderFile(
            file_path="tests/test_foo.py",
            classes=[PlaceholderClass(name="TestFoo", test_methods=["test_bar", "test_baz"])],
        ),
        PlaceholderFile(
            file_path="tests/test_standalone.py",
            standalone_tests=["test_alpha"],
        ),
    ]

    def test_output_json_structure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """output_json() produces valid JSON with correct totals and file entries."""
        output_json(placeholder_files=self.SAMPLE_PLACEHOLDER_FILES)
        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert result["total_tests"] == 3, f"Expected 3 total tests, got {result['total_tests']}"
        assert result["total_files"] == 2, f"Expected 2 total files, got {result['total_files']}"
        assert "tests/test_foo.py" in result["files"], (
            f"Missing tests/test_foo.py in files, got keys: {list(result['files'].keys())}"
        )
        assert result["files"]["tests/test_foo.py"] == ["TestFoo::test_bar", "TestFoo::test_baz"], (
            f"Expected ['TestFoo::test_bar', 'TestFoo::test_baz'], got {result['files']['tests/test_foo.py']}"
        )
        assert result["files"]["tests/test_standalone.py"] == ["test_alpha"], (
            f"Expected ['test_alpha'], got {result['files']['tests/test_standalone.py']}"
        )

    def test_output_json_empty_input(self, capsys: pytest.CaptureFixture[str]) -> None:
        """output_json() produces correct JSON for empty input."""
        output_json(placeholder_files=[])
        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert result["total_tests"] == 0, f"Expected 0 total tests, got {result['total_tests']}"
        assert result["total_files"] == 0, f"Expected 0 total files, got {result['total_files']}"
        assert result["files"] == {}, f"Expected empty files dict, got: {result['files']}"

    def test_output_text_counts_only_files_with_tests(self, caplog: pytest.LogCaptureFixture) -> None:
        """output_text() counts only files that have test entries in the total."""
        placeholder_files: list[PlaceholderFile] = [
            PlaceholderFile(
                file_path="tests/test_foo.py",
                classes=[PlaceholderClass(name="TestFoo", test_methods=["test_bar"])],
            ),
        ]
        logger = logging.getLogger(name="scripts.std_placeholder_stats.std_placeholder_stats")
        logger.propagate = True
        try:
            with caplog.at_level(logging.INFO, logger="scripts.std_placeholder_stats.std_placeholder_stats"):
                output_text(placeholder_files=placeholder_files)
        finally:
            logger.propagate = False

        summary_line = [line for line in caplog.messages if "Total:" in line]
        assert summary_line, f"Expected 'Total:' summary line in log output, got: {caplog.messages}"
        assert "1 placeholder test in 1 file" in summary_line[0], (
            f"Expected '1 placeholder test in 1 file', got: {summary_line[0]}"
        )

    def test_output_text_empty_input(self, caplog: pytest.LogCaptureFixture) -> None:
        """output_text() logs 'no placeholder tests found' for empty input."""
        logger = logging.getLogger(name="scripts.std_placeholder_stats.std_placeholder_stats")
        logger.propagate = True
        try:
            with caplog.at_level(logging.INFO, logger="scripts.std_placeholder_stats.std_placeholder_stats"):
                output_text(placeholder_files=[])
        finally:
            logger.propagate = False

        assert any("No STD placeholder tests found" in msg for msg in caplog.messages), (
            f"Expected 'No STD placeholder tests found' in log output, got: {caplog.messages}"
        )


# ===========================================================================
# Tests for separator()
# ===========================================================================


class TestSeparator:
    """Tests for the separator() function."""

    def test_plain_separator(self) -> None:
        """separator() creates a line of repeated symbols."""
        result = separator(symbol="=")
        assert result == "=" * 120, f"Expected 120 '=' chars, got length {len(result)}"

    def test_separator_with_title(self) -> None:
        """separator() centers title text in the separator line."""
        result = separator(symbol="=", title="HELLO")
        assert "HELLO" in result, f"Expected 'HELLO' in separator, got: {result}"
        assert result.startswith("="), f"Expected separator to start with '=', got: {result}"
        assert result.endswith("="), f"Expected separator to end with '=', got: {result}"

    def test_separator_with_different_symbol(self) -> None:
        """separator() works with different symbol characters."""
        result = separator(symbol="-")
        assert result == "-" * 120, f"Expected 120 '-' chars, got length {len(result)}"


# ===========================================================================
# Tests for count_placeholder_tests()
# ===========================================================================


class TestCountPlaceholderTests:
    """Tests for the count_placeholder_tests() function."""

    def test_counts_tests_and_files(self) -> None:
        """count_placeholder_tests() returns correct totals."""
        placeholder_files = [
            PlaceholderFile(
                file_path="tests/test_a.py",
                classes=[PlaceholderClass(name="TestA", test_methods=["test_one", "test_two"])],
            ),
            PlaceholderFile(
                file_path="tests/test_b.py",
                standalone_tests=["test_three"],
            ),
        ]
        total_tests, total_files = count_placeholder_tests(placeholder_files=placeholder_files)
        assert total_tests == 3, f"Expected 3 total tests, got {total_tests}"
        assert total_files == 2, f"Expected 2 total files, got {total_files}"

    def test_empty_input(self) -> None:
        """count_placeholder_tests() returns zeros for empty input."""
        total_tests, total_files = count_placeholder_tests(placeholder_files=[])
        assert total_tests == 0, f"Expected 0 total tests, got {total_tests}"
        assert total_files == 0, f"Expected 0 total files, got {total_files}"


# ===========================================================================
# Tests for _format_placeholder_lines()
# ===========================================================================


class TestFormatPlaceholderLines:
    """Tests for the _format_placeholder_lines() function."""

    def test_formats_class_entries(self) -> None:
        """_format_placeholder_lines() formats class entries with file path prefix."""
        placeholder = PlaceholderFile(
            file_path="tests/test_foo.py",
            classes=[PlaceholderClass(name="TestFoo", test_methods=["test_bar", "test_baz"])],
        )
        lines = _format_placeholder_lines(placeholder_file=placeholder)
        assert lines[0] == "tests/test_foo.py::TestFoo", f"Expected class header, got: {lines[0]}"
        assert "  - test_bar" in lines, f"Expected '  - test_bar' in lines, got: {lines}"
        assert "  - test_baz" in lines, f"Expected '  - test_baz' in lines, got: {lines}"

    def test_formats_standalone_entries(self) -> None:
        """_format_placeholder_lines() formats standalone tests with <standalone> label."""
        placeholder = PlaceholderFile(
            file_path="tests/test_foo.py",
            standalone_tests=["test_alpha"],
        )
        lines = _format_placeholder_lines(placeholder_file=placeholder)
        assert lines[0] == "tests/test_foo.py::<standalone>", f"Expected standalone header, got: {lines[0]}"
        assert "  - test_alpha" in lines, f"Expected '  - test_alpha' in lines, got: {lines}"
