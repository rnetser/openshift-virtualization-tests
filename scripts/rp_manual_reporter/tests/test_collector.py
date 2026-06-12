"""Tests for scripts.rp_manual_reporter.collector module."""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from scripts.rp_manual_reporter.collector import (
    PlaceholderTestDetail,
    _extract_docstring,
    _extract_markers,
    _extract_module_markers,
    _extract_polarion_id,
    _extract_usefixtures,
    collect_placeholder_details,
    node_id_to_rp_name,
)


class TestNodeIdToRpName:
    def test_node_id_to_rp_name_basic(self) -> None:
        """Verify basic node ID with class and method converts to dotted name."""
        result = node_id_to_rp_name(node_id="tests/foo/test_bar.py::TestClass::test_method")
        assert result == "tests.foo.test_bar.TestClass.test_method"

    def test_node_id_to_rp_name_with_params(self) -> None:
        """Verify parametrize suffix is preserved in conversion."""
        result = node_id_to_rp_name(node_id="tests/foo/test_bar.py::TestClass::test_method[param]")
        assert result == "tests.foo.test_bar.TestClass.test_method[param]"

    def test_node_id_to_rp_name_standalone(self) -> None:
        """Verify standalone function (no class) converts correctly."""
        result = node_id_to_rp_name(node_id="tests/foo/test_bar.py::test_func")
        assert result == "tests.foo.test_bar.test_func"


class TestExtractDocstring:
    def test_extract_docstring(self) -> None:
        """Verify docstring is extracted from a function AST node."""
        source = textwrap.dedent('''\
            def test_example():
                """This is the docstring."""
                pass
        ''')
        tree = ast.parse(source=source)
        func_node = tree.body[0]
        result = _extract_docstring(node=func_node)
        assert result == "This is the docstring."

    def test_extract_docstring_no_docstring(self) -> None:
        """Verify None returned when function has no docstring."""
        source = textwrap.dedent("""\
            def test_example():
                pass
        """)
        tree = ast.parse(source=source)
        func_node = tree.body[0]
        result = _extract_docstring(node=func_node)
        assert result is None


class TestExtractMarkers:
    def test_extract_markers(self) -> None:
        """Verify bare pytest.mark decorators are extracted."""
        source = textwrap.dedent("""\
            import pytest

            @pytest.mark.smoke
            @pytest.mark.tier1
            def test_example():
                pass
        """)
        tree = ast.parse(source=source)
        func_node = tree.body[1]
        result = _extract_markers(decorators=func_node.decorator_list)
        assert result == ["smoke", "tier1"]

    def test_extract_markers_with_args(self) -> None:
        """Verify called markers include their arguments."""
        source = textwrap.dedent("""\
            import pytest

            @pytest.mark.parametrize("x", [1, 2])
            def test_example(x):
                pass
        """)
        tree = ast.parse(source=source)
        func_node = tree.body[1]
        result = _extract_markers(decorators=func_node.decorator_list)
        assert len(result) == 1
        assert result[0].startswith("parametrize(")


class TestExtractUsefixtures:
    def test_extract_usefixtures(self) -> None:
        """Verify fixture names extracted from usefixtures decorator."""
        source = textwrap.dedent("""\
            import pytest

            @pytest.mark.usefixtures("fix1", "fix2")
            class TestExample:
                pass
        """)
        tree = ast.parse(source=source)
        class_node = tree.body[1]
        result = _extract_usefixtures(decorators=class_node.decorator_list)
        assert result == ["fix1", "fix2"]


class TestExtractPolarionId:
    def test_extract_polarion_id(self) -> None:
        """Verify Polarion ID extracted from polarion marker."""
        source = textwrap.dedent("""\
            import pytest

            @pytest.mark.polarion("CNV-1234")
            def test_example():
                pass
        """)
        tree = ast.parse(source=source)
        func_node = tree.body[1]
        result = _extract_polarion_id(decorators=func_node.decorator_list)
        assert result == "CNV-1234"

    def test_extract_polarion_id_no_marker(self) -> None:
        """Verify None returned when no polarion marker present."""
        source = textwrap.dedent("""\
            import pytest

            @pytest.mark.smoke
            def test_example():
                pass
        """)
        tree = ast.parse(source=source)
        func_node = tree.body[1]
        result = _extract_polarion_id(decorators=func_node.decorator_list)
        assert result is None


class TestExtractModuleMarkers:
    def test_extract_module_markers(self) -> None:
        """Verify module-level pytestmark list markers are extracted."""
        source = textwrap.dedent("""\
            import pytest

            pytestmark = [pytest.mark.foo, pytest.mark.bar]
        """)
        tree = ast.parse(source=source)
        result = _extract_module_markers(tree=tree)
        assert result == ["foo", "bar"]


class TestCollectPlaceholderDetails:
    def test_collect_placeholder_details(self, tmp_path: Path) -> None:
        """Verify full placeholder detail collection from a temp test file."""
        # Create directory structure matching expected layout
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        sub_dir = tests_dir / "network"
        sub_dir.mkdir()

        test_file = sub_dir / "test_example.py"
        test_file.write_text(
            textwrap.dedent('''\
            """Module docstring for STP link."""

            import pytest

            __test__ = False

            pytestmark = [pytest.mark.tier1]

            class TestMyFeature:
                """Class docstring."""

                @pytest.mark.polarion("CNV-9999")
                def test_my_case(self):
                    """Test docstring with steps."""
                    pass
        ''')
        )

        # Build mock PlaceholderFile / PlaceholderClass
        @dataclass
        class MockPlaceholderClass:
            name: str
            test_methods: list[str] = field(default_factory=list)
            disabled_methods: list[str] = field(default_factory=list)

        @dataclass
        class MockPlaceholderFile:
            file_path: str
            classes: list[MockPlaceholderClass] = field(default_factory=list)
            standalone_tests: list[str] = field(default_factory=list)
            disabled_standalone_tests: list[str] = field(default_factory=list)

        mock_placeholder = MockPlaceholderFile(
            file_path="tests/network/test_example.py",
            classes=[
                MockPlaceholderClass(
                    name="TestMyFeature",
                    test_methods=["test_my_case"],
                ),
            ],
        )

        with patch(
            "scripts.std_placeholder_stats.std_placeholder_stats.scan_placeholder_tests",
            return_value=[mock_placeholder],
        ):
            details = collect_placeholder_details(tests_dir=tests_dir)

        assert len(details) == 1
        detail = details[0]
        assert isinstance(detail, PlaceholderTestDetail)
        assert detail.file_path == "tests/network/test_example.py"
        assert detail.class_name == "TestMyFeature"
        assert detail.method_name == "test_my_case"
        assert detail.module_docstring == "Module docstring for STP link."
        assert detail.class_docstring == "Class docstring."
        assert detail.test_docstring == "Test docstring with steps."
        assert detail.module_markers == ["tier1"]
        assert detail.polarion_id == "CNV-9999"
        assert detail.node_id == "tests/network/test_example.py::TestMyFeature::test_my_case"
        assert detail.rp_name == "tests.network.test_example.TestMyFeature.test_my_case"
