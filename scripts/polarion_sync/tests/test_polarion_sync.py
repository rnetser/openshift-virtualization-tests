"""Unit tests for scripts.polarion_sync package."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.polarion_sync.injector import inject_polarion_ids
from scripts.polarion_sync.jira_linker import clear_caches as clear_jira_caches
from scripts.polarion_sync.polarion_client import (
    PolarionResult,
    _humanize_test_name,
    clear_sibling_cache,
    create_test_cases,
)
from scripts.polarion_sync.push_gate import _validate_changed_files, _validate_diff
from scripts.polarion_sync.scanner import UnlinkedTest, scan_file


@pytest.fixture(autouse=True)
def _clear_polarion_caches():
    """Clear module-level caches between tests to ensure isolation."""
    yield
    clear_jira_caches()
    clear_sibling_cache()


@pytest.fixture
def create_test_file(tmp_path):
    """Provide a factory that creates temporary test files with given content."""

    def _factory(source: str, filename: str = "test_example.py") -> Path:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(exist_ok=True)
        test_file = tests_dir / filename
        test_file.write_text(textwrap.dedent(source))
        return test_file

    return _factory


class TestScanFile:
    """Tests for the scanner module's scan_file function."""

    def test_scan_file_detects_test_without_polarion_id(self, tmp_path: Path, create_test_file):
        """Test that a test function without Polarion marker is detected."""
        source = """\
            def test_something():
                \"\"\"Test that something works.\"\"\"
                assert True
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 1
        assert results[0].test_name == "test_something"
        assert results[0].is_std_only is False

    def test_scan_file_detects_test_with_polarion_in_docstring_only(self, tmp_path: Path, create_test_file):
        """Test that a test with Polarion in docstring but no marker IS detected."""
        source = """\
            def test_something():
                \"\"\"Test that something works.

                Polarion: CNV-12345
                \"\"\"
                assert True
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 1
        assert results[0].test_name == "test_something"

    def test_scan_file_skips_test_with_polarion_marker(self, tmp_path: Path, create_test_file):
        """Test that a test with @pytest.mark.polarion marker is skipped."""
        source = """\
            import pytest

            @pytest.mark.polarion("CNV-12345")
            def test_something():
                \"\"\"Test that something works.\"\"\"
                assert True
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert results == []

    def test_scan_file_detects_class_method(self, tmp_path: Path, create_test_file):
        """Test that a test method inside a class is detected with correct node_id."""
        source = """\
            class TestMyFeature:
                def test_feature_works(self):
                    \"\"\"Test that the feature works.\"\"\"
                    assert True
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 1
        assert results[0].test_name == "test_feature_works"
        assert results[0].class_name == "TestMyFeature"
        assert results[0].node_id == "tests.test_example::TestMyFeature::test_feature_works"

    def test_scan_file_detects_std_only_class(self, tmp_path: Path, create_test_file):
        """Test that __test__ = False at class level marks methods as STD-only."""
        source = """\
            class TestPlaceholder:
                __test__ = False

                def test_future_feature(self):
                    \"\"\"Test that future feature works.

                    Preconditions:
                        - A running VM

                    Steps:
                        1. Do something

                    Expected:
                        Something happens
                    \"\"\"
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 1
        assert results[0].is_std_only is True

    def test_scan_file_detects_std_only_module(self, tmp_path: Path, create_test_file):
        """Test that module-level __test__ = False marks all tests as STD-only."""
        source = """\
            __test__ = False

            def test_alpha():
                \"\"\"Test alpha.\"\"\"

            def test_beta():
                \"\"\"Test beta.\"\"\"
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 2
        assert all(result.is_std_only for result in results)

    def test_scan_file_implemented_test_not_std_only(self, tmp_path: Path, create_test_file):
        """Test that a normal implemented test has is_std_only=False."""
        source = """\
            class TestImplemented:
                def test_real_test(self):
                    \"\"\"Test that works.\"\"\"
                    assert 1 + 1 == 2
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 1
        assert results[0].is_std_only is False

    def test_scan_file_no_tests(self, tmp_path: Path, create_test_file):
        """Test that a file with no test functions returns an empty list."""
        source = """\
            def helper_function():
                return 42

            class NotATest:
                pass
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert results == []

    def test_scan_file_detects_func_level_dunder_test_false(self, tmp_path: Path, create_test_file):
        """Test that func.__test__ = False at module level marks the function as STD-only."""
        source = """\
            def test_placeholder():
                \"\"\"Test placeholder.\"\"\"

            test_placeholder.__test__ = False

            def test_implemented():
                \"\"\"Test implemented.\"\"\"
                assert True
        """
        test_file = create_test_file(source=source)

        results = scan_file(file=test_file, repo_root=tmp_path)

        assert len(results) == 2
        placeholder = next(result for result in results if result.test_name == "test_placeholder")
        implemented = next(result for result in results if result.test_name == "test_implemented")
        assert placeholder.is_std_only is True
        assert implemented.is_std_only is False


class TestInjector:
    """Tests for the injector module."""

    def test_inject_adds_polarion_marker_decorator(self, tmp_path: Path, create_test_file):
        """Test that a @pytest.mark.polarion decorator is injected before the def line."""
        source = textwrap.dedent("""\
            def test_something():
                \"\"\"Test that something works.\"\"\"
                assert True
        """)
        test_file = create_test_file(source=source)
        unlinked_test = UnlinkedTest(
            file=test_file,
            class_name=None,
            test_name="test_something",
            docstring="Test that something works.",
            node_id="tests.test_example::test_something",
            lineno=1,
        )
        polarion_result = PolarionResult(test=unlinked_test, polarion_id="CNV-99999")

        modified = inject_polarion_ids(results=[polarion_result])

        assert test_file in modified
        content = test_file.read_text()
        assert '@pytest.mark.polarion("CNV-99999")' in content
        lines = content.splitlines()
        marker_idx = next(idx for idx, line in enumerate(lines) if "polarion" in line)
        assert lines[marker_idx + 1].strip().startswith("def test_something")

    def test_inject_multiple_tests_same_file(self, tmp_path: Path, create_test_file):
        """Test that multiple test markers are injected into the same file."""
        source = textwrap.dedent("""\
            def test_alpha():
                \"\"\"Test alpha.\"\"\"
                assert True

            def test_beta():
                \"\"\"Test beta.\"\"\"
                assert True
        """)
        test_file = create_test_file(source=source)
        test_alpha = UnlinkedTest(
            file=test_file,
            class_name=None,
            test_name="test_alpha",
            docstring="Test alpha.",
            node_id="tests.test_example::test_alpha",
            lineno=1,
        )
        test_beta = UnlinkedTest(
            file=test_file,
            class_name=None,
            test_name="test_beta",
            docstring="Test beta.",
            node_id="tests.test_example::test_beta",
            lineno=5,
        )
        results = [
            PolarionResult(test=test_alpha, polarion_id="CNV-00001"),
            PolarionResult(test=test_beta, polarion_id="CNV-00002"),
        ]

        modified = inject_polarion_ids(results=results)

        assert test_file in modified
        content = test_file.read_text()
        assert '@pytest.mark.polarion("CNV-00001")' in content
        assert '@pytest.mark.polarion("CNV-00002")' in content

    def test_inject_preserves_existing_content(self, tmp_path: Path, create_test_file):
        """Test that existing docstring content is preserved after injection."""
        source = textwrap.dedent("""\
            def test_something():
                \"\"\"Test that something works.

                Preconditions:
                    - A running VM
                \"\"\"
                assert True
        """)
        test_file = create_test_file(source=source)
        unlinked_test = UnlinkedTest(
            file=test_file,
            class_name=None,
            test_name="test_something",
            docstring="Test that something works.\n\nPreconditions:\n    - A running VM",
            node_id="tests.test_example::test_something",
            lineno=1,
        )
        polarion_result = PolarionResult(test=unlinked_test, polarion_id="CNV-55555")

        inject_polarion_ids(results=[polarion_result])

        content = test_file.read_text()
        assert '@pytest.mark.polarion("CNV-55555")' in content
        assert "Preconditions:" in content
        assert "A running VM" in content

    def test_inject_class_method_has_correct_indentation(self, tmp_path: Path, create_test_file):
        """Test that a marker injected on a class method has correct indentation."""
        source = textwrap.dedent("""\
            class TestFeature:
                def test_works(self):
                    \"\"\"Test that it works.\"\"\"
                    assert True
        """)
        test_file = create_test_file(source=source)
        unlinked_test = UnlinkedTest(
            file=test_file,
            class_name="TestFeature",
            test_name="test_works",
            docstring="Test that it works.",
            node_id="tests.test_example::TestFeature::test_works",
            lineno=2,
        )
        polarion_result = PolarionResult(test=unlinked_test, polarion_id="CNV-77777")

        inject_polarion_ids(results=[polarion_result])

        content = test_file.read_text()
        lines = content.splitlines()
        marker_line = next(line for line in lines if "polarion" in line)
        def_line = next(line for line in lines if "def test_works" in line)
        # Both should have the same indentation
        marker_indent = len(marker_line) - len(marker_line.lstrip())
        def_indent = len(def_line) - len(def_line.lstrip())
        assert marker_indent == def_indent


class TestPolarionClient:
    """Tests for the polarion_client module."""

    def test_humanize_test_name(self):
        """Test conversion of test function name to human-readable title."""
        assert _humanize_test_name(test_name="test_vm_starts_with_bridge") == "Vm starts with bridge"

    def test_humanize_test_name_simple(self):
        """Test humanize with a simple test name."""
        assert _humanize_test_name(test_name="test_basic") == "Basic"

    def test_create_test_cases_dry_run(self):
        """Test that dry run produces fake IDs."""
        test = UnlinkedTest(
            file=Path("tests/test_example.py"),
            class_name=None,
            test_name="test_something",
            docstring="Test something.",
            node_id="tests.test_example::test_something",
            lineno=1,
        )

        results = create_test_cases(tests=[test], project_id="CNV", dry_run=True)

        assert len(results) == 1
        assert results[0].polarion_id == "CNV-DRY00001"
        assert results[0].test is test

    def test_create_test_cases_dry_run_empty(self):
        """Test that empty input returns empty output."""
        results = create_test_cases(tests=[], project_id="CNV", dry_run=True)

        assert results == []

    def test_create_test_cases_dry_run_std_only(self):
        """Test that dry run creates result with correct ID for STD-only test."""
        test = UnlinkedTest(
            file=Path("tests/test_example.py"),
            class_name=None,
            test_name="test_placeholder",
            docstring="Placeholder test.",
            node_id="tests.test_example::test_placeholder",
            lineno=1,
            is_std_only=True,
        )

        results = create_test_cases(tests=[test], project_id="CNV", dry_run=True)

        assert len(results) == 1
        assert results[0].test.is_std_only is True

    def test_create_test_cases_dry_run_automated(self):
        """Test that dry run creates result for implemented test."""
        test = UnlinkedTest(
            file=Path("tests/test_example.py"),
            class_name=None,
            test_name="test_real",
            docstring="Real test.",
            node_id="tests.test_example::test_real",
            lineno=1,
            is_std_only=False,
        )

        results = create_test_cases(tests=[test], project_id="CNV", dry_run=True)

        assert len(results) == 1
        assert results[0].test.is_std_only is False


class TestPushGate:
    """Tests for the push_gate module."""

    def test_validate_diff_polarion_marker_only(self):
        """Test that a diff with only Polarion marker additions passes validation."""
        diff = textwrap.dedent("""\
            diff --git a/tests/test_foo.py b/tests/test_foo.py
            --- a/tests/test_foo.py
            +++ b/tests/test_foo.py
            @@ -1,3 +1,4 @@
            +    @pytest.mark.polarion("CNV-12345")
                 def test_foo():
                     \"\"\"Test foo.\"\"\"
        """)

        is_safe, violations = _validate_diff(diff=diff)

        assert is_safe is True
        assert violations == []

    def test_validate_diff_rejects_code_changes(self):
        """Test that a diff with code additions fails validation."""
        diff = textwrap.dedent("""\
            diff --git a/tests/test_foo.py b/tests/test_foo.py
            --- a/tests/test_foo.py
            +++ b/tests/test_foo.py
            @@ -1,3 +1,4 @@
             def test_foo():
            +    x = 42
                 assert True
        """)

        is_safe, violations = _validate_diff(diff=diff)

        assert is_safe is False
        assert violations

    def test_validate_diff_rejects_removals(self):
        """Test that a diff with removed lines fails validation."""
        diff = textwrap.dedent("""\
            diff --git a/tests/test_foo.py b/tests/test_foo.py
            --- a/tests/test_foo.py
            +++ b/tests/test_foo.py
            @@ -1,4 +1,3 @@
             def test_foo():
            -    old_code = True
                 assert True
        """)

        is_safe, violations = _validate_diff(diff=diff)

        assert is_safe is False
        assert violations

    def test_validate_diff_allows_import_lines(self):
        """Test that added import lines are allowed in the diff."""
        diff = textwrap.dedent("""\
            diff --git a/tests/test_foo.py b/tests/test_foo.py
            --- a/tests/test_foo.py
            +++ b/tests/test_foo.py
            @@ -1,3 +1,5 @@
            +import pytest
            +    @pytest.mark.polarion("CNV-12345")
                 def test_foo():
                     \"\"\"Test foo.\"\"\"
        """)

        is_safe, violations = _validate_diff(diff=diff)

        assert is_safe is True
        assert violations == []

    def test_validate_changed_files_test_files_ok(self):
        """Test that only test files pass validation."""
        is_ok, violations = _validate_changed_files(changed_files=["tests/foo/test_bar.py"])

        assert is_ok is True
        assert violations == []

    def test_validate_changed_files_rejects_non_test(self):
        """Test that non-test files fail validation."""
        is_ok, violations = _validate_changed_files(changed_files=["utilities/foo.py"])

        assert is_ok is False
        assert violations
