# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.rp_manual_reporter.collector module."""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from scripts.rp_manual_reporter.cluster_info import (
    ClusterAttributes,
    cluster_attributes_to_launch_attrs,
)
from scripts.rp_manual_reporter.collector import (
    PlaceholderTestDetail,
    _extract_docstring,
    _extract_markers,
    _extract_module_markers,
    _extract_polarion_id,
    _extract_usefixtures,
    _matches_keyword_filter,
    _matches_marker_filter,
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


def _make_detail(
    node_id: str = "tests/net/test_a.py::TestA::test_one",
    module_markers: list[str] | None = None,
    class_markers: list[str] | None = None,
    test_markers: list[str] | None = None,
) -> PlaceholderTestDetail:
    """Helper to create a PlaceholderTestDetail with minimal fields."""
    return PlaceholderTestDetail(
        file_path="tests/net/test_a.py",
        class_name="TestA",
        method_name="test_one",
        node_id=node_id,
        rp_name=node_id_to_rp_name(node_id=node_id),
        module_markers=module_markers or [],
        class_markers=class_markers or [],
        test_markers=test_markers or [],
    )


class TestMatchesMarkerFilter:
    def test_simple_marker_match(self) -> None:
        """Verify simple marker name matches."""
        detail = _make_detail(test_markers=["gating"])
        assert _matches_marker_filter(detail=detail, marker_filter="gating") is True

    def test_simple_marker_no_match(self) -> None:
        """Verify non-matching marker returns False."""
        detail = _make_detail(test_markers=["tier1"])
        assert _matches_marker_filter(detail=detail, marker_filter="gating") is False

    def test_marker_in_module_markers(self) -> None:
        """Verify marker found in module-level markers."""
        detail = _make_detail(module_markers=["gating"])
        assert _matches_marker_filter(detail=detail, marker_filter="gating") is True

    def test_marker_in_class_markers(self) -> None:
        """Verify marker found in class-level markers."""
        detail = _make_detail(class_markers=["smoke"])
        assert _matches_marker_filter(detail=detail, marker_filter="smoke") is True

    def test_boolean_and_expression(self) -> None:
        """Verify 'and' boolean expression matches when both markers present."""
        detail = _make_detail(test_markers=["gating", "tier1"])
        assert _matches_marker_filter(detail=detail, marker_filter="gating and tier1") is True

    def test_boolean_and_expression_partial(self) -> None:
        """Verify 'and' expression fails when only one marker present."""
        detail = _make_detail(test_markers=["gating"])
        assert _matches_marker_filter(detail=detail, marker_filter="gating and tier1") is False

    def test_boolean_not_expression(self) -> None:
        """Verify 'not' expression excludes tests with the marker."""
        detail = _make_detail(test_markers=["gating"])
        assert _matches_marker_filter(detail=detail, marker_filter="gating and not tier3") is True

    def test_marker_with_args_stripped(self) -> None:
        """Verify markers with args like 'parametrize(...)' are stripped to bare name."""
        detail = _make_detail(test_markers=["parametrize('x', [1, 2])"])
        assert _matches_marker_filter(detail=detail, marker_filter="parametrize") is True


class TestMatchesKeywordFilter:
    def test_keyword_match(self) -> None:
        """Verify keyword substring matches node ID."""
        detail = _make_detail(node_id="tests/network/test_bridge.py::TestBridge::test_connectivity")
        assert _matches_keyword_filter(detail=detail, keyword_filter="test_connectivity") is True

    def test_keyword_no_match(self) -> None:
        """Verify non-matching keyword returns False."""
        detail = _make_detail(node_id="tests/network/test_bridge.py::TestBridge::test_connectivity")
        assert _matches_keyword_filter(detail=detail, keyword_filter="test_migration") is False

    def test_keyword_case_insensitive(self) -> None:
        """Verify keyword matching is case-insensitive."""
        detail = _make_detail(node_id="tests/network/test_bridge.py::TestBridge::test_connectivity")
        assert _matches_keyword_filter(detail=detail, keyword_filter="TestBridge") is True

    def test_keyword_partial_match(self) -> None:
        """Verify partial keyword matches."""
        detail = _make_detail(node_id="tests/network/test_bridge.py::TestBridge::test_connectivity")
        assert _matches_keyword_filter(detail=detail, keyword_filter="bridge") is True


class TestClusterInfoKeyNames:
    def test_cluster_attributes_emit_long_keys(self) -> None:
        """Verify cluster_attributes_to_launch_attrs uses validation-matching keys."""
        attrs = ClusterAttributes(
            arch="amd64",
            ocp_version="4.22.0",
            cnv_xy_version="4.22",
            bundle="v4.22.0",
            cluster_name="bm15a",
            cluster_domain="bm15a.example.com",
            storage_class="ocs-storagecluster-ceph-rbd",
            channel="candidate",
        )

        launch_attrs = cluster_attributes_to_launch_attrs(cluster_attrs=attrs)
        keys = {attr["key"] for attr in launch_attrs}

        assert "ARCHITECTURE" in keys
        assert "OCP_VERSION" in keys
        assert "CNV_VERSION" in keys
        assert "STORAGE_CLASS" in keys
        assert "ARCH" not in keys
        assert "OCP" not in keys
        assert "CNV_XY_VER" not in keys
        assert "SC" not in keys
