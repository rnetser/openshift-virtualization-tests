"""
Unit tests for pytest_marker_analyzer hierarchical symbol analysis.

Co-authored-by: Claude <noreply@anthropic.com>
"""

import argparse
import ast
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.tests_analyzer.pytest_marker_analyzer import (
    AttributeAccessCollector,
    Fixture,
    MarkedTest,
    SymbolClassification,
    _build_intra_class_call_graph,
    _build_line_to_symbol_map,
    _check_conftest_pathway,
    _collect_test_attribute_accesses,
    _collect_test_function_calls,
    _expand_modified_members_transitively,
    _extract_modified_items_from_conftest,
    _extract_modified_symbols,
    _get_modified_function_names,
    _is_fixture_decorator_standalone,
    _parse_diff_for_functions,
    run_github_mode,
)


class TestBuildLineToSymbolMap:
    def test_top_level_function(self):
        source = textwrap.dedent("""\
            def hello():
                pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        names = [entry[2] for entry in symbol_map.top_level]
        assert "hello" in names

    def test_async_function(self):
        source = textwrap.dedent("""\
            async def async_hello():
                pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        names = [entry[2] for entry in symbol_map.top_level]
        assert "async_hello" in names

    def test_class_with_methods(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    pass
                def method_b(self):
                    pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        top_level_names = [entry[2] for entry in symbol_map.top_level]
        assert "MyClass" in top_level_names
        assert "MyClass" in symbol_map.class_members
        member_info = symbol_map.class_members["MyClass"]
        assert "method_a" in member_info.members
        assert "method_b" in member_info.members

    def test_class_member_line_ranges(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    x = 1
                    return x
                def method_b(self):
                    pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        member_info = symbol_map.class_members["MyClass"]
        start_a, end_a = member_info.members["method_a"]
        start_b, end_b = member_info.members["method_b"]
        assert start_a < end_a, "method_a should span multiple lines"
        assert start_b <= end_b, "method_b should have valid range"
        assert start_a < start_b, "method_a should come before method_b"

    def test_class_intra_call_graph(self):
        source = textwrap.dedent("""\
            class MyClass:
                def caller(self):
                    self.helper()
                def helper(self):
                    pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        member_info = symbol_map.class_members["MyClass"]
        assert "helper" in member_info.internal_calls["caller"]

    def test_module_level_assignment(self):
        source = "FOO = 42\n"
        symbol_map = _build_line_to_symbol_map(source=source)
        names = [entry[2] for entry in symbol_map.top_level]
        assert "FOO" in names

    def test_annotated_assignment(self):
        source = "FOO: int = 42\n"
        symbol_map = _build_line_to_symbol_map(source=source)
        names = [entry[2] for entry in symbol_map.top_level]
        assert "FOO" in names

    def test_empty_source(self):
        symbol_map = _build_line_to_symbol_map(source="")
        assert symbol_map.top_level == []
        assert symbol_map.class_members == {}

    def test_mixed_definitions(self):
        source = textwrap.dedent("""\
            FOO = 1

            def my_func():
                pass

            class MyClass:
                def method(self):
                    pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        names = [entry[2] for entry in symbol_map.top_level]
        assert "FOO" in names
        assert "my_func" in names
        assert "MyClass" in names
        assert "MyClass" in symbol_map.class_members

    def test_sorted_by_start_line(self):
        source = textwrap.dedent("""\
            def second_func():
                pass

            FOO = 1

            class MyClass:
                pass
        """)
        symbol_map = _build_line_to_symbol_map(source=source)
        start_lines = [entry[0] for entry in symbol_map.top_level]
        assert start_lines == sorted(start_lines), "top_level should be sorted by start line"


class TestBuildIntraClassCallGraph:
    def test_simple_self_call(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    self.helper()
                def helper(self):
                    pass
        """)
        tree = ast.parse(source)
        class_node = tree.body[0]
        graph = _build_intra_class_call_graph(class_node=class_node)
        assert "helper" in graph["method_a"]

    def test_no_self_calls(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    print("hello")
        """)
        tree = ast.parse(source)
        class_node = tree.body[0]
        graph = _build_intra_class_call_graph(class_node=class_node)
        assert graph["method_a"] == set()

    def test_multiple_callees(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    self.helper_one()
                    self.helper_two()
                def helper_one(self):
                    pass
                def helper_two(self):
                    pass
        """)
        tree = ast.parse(source)
        class_node = tree.body[0]
        graph = _build_intra_class_call_graph(class_node=class_node)
        assert graph["method_a"] == {"helper_one", "helper_two"}

    def test_nested_self_call(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    if True:
                        for i in range(10):
                            self.helper()
                def helper(self):
                    pass
        """)
        tree = ast.parse(source)
        class_node = tree.body[0]
        graph = _build_intra_class_call_graph(class_node=class_node)
        assert "helper" in graph["method_a"]

    def test_non_self_call_ignored(self):
        source = textwrap.dedent("""\
            class MyClass:
                def method_a(self):
                    other.method()
                    obj.do_thing()
        """)
        tree = ast.parse(source)
        class_node = tree.body[0]
        graph = _build_intra_class_call_graph(class_node=class_node)
        assert graph["method_a"] == set()


class TestExpandModifiedMembersTransitively:
    def test_no_expansion_needed(self):
        directly_modified = {"lonely_method"}
        internal_calls = {
            "other_method": {"unrelated"},
        }
        result = _expand_modified_members_transitively(
            directly_modified=directly_modified,
            internal_calls=internal_calls,
        )
        assert result == {"lonely_method"}

    def test_single_transitive_caller(self):
        directly_modified = {"helper"}
        internal_calls = {
            "caller": {"helper"},
            "helper": set(),
        }
        result = _expand_modified_members_transitively(
            directly_modified=directly_modified,
            internal_calls=internal_calls,
        )
        assert result == {"caller", "helper"}

    def test_chain_expansion(self):
        directly_modified = {"leaf"}
        internal_calls = {
            "top": {"middle"},
            "middle": {"leaf"},
            "leaf": set(),
        }
        result = _expand_modified_members_transitively(
            directly_modified=directly_modified,
            internal_calls=internal_calls,
        )
        assert result == {"top", "middle", "leaf"}

    def test_diamond_expansion(self):
        directly_modified = {"target"}
        internal_calls = {
            "caller_a": {"target"},
            "caller_b": {"target"},
            "target": set(),
        }
        result = _expand_modified_members_transitively(
            directly_modified=directly_modified,
            internal_calls=internal_calls,
        )
        assert result == {"caller_a", "caller_b", "target"}

    def test_empty_modified(self):
        internal_calls = {
            "method_a": {"method_b"},
            "method_b": set(),
        }
        result = _expand_modified_members_transitively(
            directly_modified=set(),
            internal_calls=internal_calls,
        )
        assert result == set()

    def test_cycle_handling(self):
        directly_modified = {"method_a"}
        internal_calls = {
            "method_a": {"method_b"},
            "method_b": {"method_a"},
        }
        result = _expand_modified_members_transitively(
            directly_modified=directly_modified,
            internal_calls=internal_calls,
        )
        assert result == {"method_a", "method_b"}


class TestAttributeAccessCollector:
    def test_simple_attribute(self):
        source = "obj.attr"
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert "attr" in collector.accessed_attrs

    def test_multiple_attributes(self):
        source = textwrap.dedent("""\
            obj.x
            obj.y
        """)
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert collector.accessed_attrs == {"x", "y"}

    def test_getattr_sets_dynamic(self):
        source = 'getattr(obj, "x")'
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert collector.has_dynamic_access is True

    def test_setattr_sets_dynamic(self):
        source = 'setattr(obj, "x", value)'
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert collector.has_dynamic_access is True

    def test_delattr_sets_dynamic(self):
        source = 'delattr(obj, "x")'
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert collector.has_dynamic_access is True

    def test_no_dynamic_access(self):
        source = "obj.normal_attr"
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert collector.has_dynamic_access is False

    def test_method_call_attribute(self):
        source = "obj.method()"
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert "method" in collector.accessed_attrs

    def test_chained_attribute(self):
        source = "obj.a.b.c"
        tree = ast.parse(source)
        collector = AttributeAccessCollector()
        collector.visit(node=tree)
        assert {"a", "b", "c"} == collector.accessed_attrs


class TestCollectTestAttributeAccesses:
    def test_simple_test_function(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_foo(vm):
                vm.start()
                vm.stop()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="test_foo",
        )
        assert result is not None
        assert "start" in result
        assert "stop" in result

    def test_class_based_test(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            class TestVM:
                def test_boot(self, vm):
                    vm.start()

            class TestOther:
                def test_boot(self, svc):
                    svc.restart()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="TestVM::test_boot",
        )
        assert result is not None
        assert "start" in result
        assert "restart" not in result

    def test_parametrized_name_stripped(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_foo(vm):
                vm.migrate()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="test_foo[param1]",
        )
        assert result is not None
        assert "migrate" in result

    def test_class_parametrized_stripped(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            class TestVM:
                def test_boot(self, vm):
                    vm.start()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="TestVM::test_boot[linux-fedora]",
        )
        assert result is not None
        assert "start" in result

    def test_dynamic_access_returns_none(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_dynamic(vm):
                getattr(vm, "start")()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="test_dynamic",
        )
        assert result is None

    def test_constructor_adds_init(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_create(ns):
                vm = VirtualMachine()
                vm.start()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="test_create",
        )
        assert result is not None
        assert "__init__" in result

    def test_nonexistent_test_returns_none(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_existing(vm):
                vm.start()
        """)
        )
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="test_nonexistent",
        )
        assert result is None

    def test_invalid_syntax_returns_none(self, tmp_path: Path):
        test_file = tmp_path / "test_bad.py"
        test_file.write_text("def broken(:\n")
        result = _collect_test_attribute_accesses(
            test_file=test_file,
            test_name="broken",
        )
        assert result is None


class TestCollectTestFunctionCalls:
    def test_simple_function_call(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_calls():
                foo()
        """)
        )
        result = _collect_test_function_calls(
            test_file=test_file,
            test_name="test_calls",
        )
        assert result is not None
        assert "foo" in result

    def test_method_call(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_method(obj):
                obj.bar()
        """)
        )
        result = _collect_test_function_calls(
            test_file=test_file,
            test_name="test_method",
        )
        assert result is not None
        assert "bar" in result

    def test_class_based_test(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            class TestSuite:
                def test_inner(self):
                    helper()

            def test_inner():
                other_func()
        """)
        )
        result = _collect_test_function_calls(
            test_file=test_file,
            test_name="TestSuite::test_inner",
        )
        assert result is not None
        assert "helper" in result
        assert "other_func" not in result

    def test_parametrized_name_stripped(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_param():
                do_work()
        """)
        )
        result = _collect_test_function_calls(
            test_file=test_file,
            test_name="test_param[case-1]",
        )
        assert result is not None
        assert "do_work" in result

    def test_nonexistent_returns_none(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_real():
                pass
        """)
        )
        result = _collect_test_function_calls(
            test_file=test_file,
            test_name="test_ghost",
        )
        assert result is None

    def test_multiple_calls(self, tmp_path: Path):
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""\
            def test_multi():
                alpha()
                beta()
                obj.gamma()
        """)
        )
        result = _collect_test_function_calls(
            test_file=test_file,
            test_name="test_multi",
        )
        assert result is not None
        assert {"alpha", "beta", "gamma"}.issubset(result)


class TestIsFixtureDecoratorStandalone:
    def test_bare_fixture(self):
        source = textwrap.dedent("""\
            @fixture
            def my_fixture():
                pass
        """)
        tree = ast.parse(source)
        func_node = tree.body[0]
        decorator = func_node.decorator_list[0]
        assert _is_fixture_decorator_standalone(decorator=decorator) is True

    def test_pytest_fixture(self):
        source = textwrap.dedent("""\
            @pytest.fixture
            def my_fixture():
                pass
        """)
        tree = ast.parse(source)
        func_node = tree.body[0]
        decorator = func_node.decorator_list[0]
        assert _is_fixture_decorator_standalone(decorator=decorator) is True

    def test_pytest_fixture_with_params(self):
        source = textwrap.dedent("""\
            @pytest.fixture(scope="session")
            def my_fixture():
                pass
        """)
        tree = ast.parse(source)
        func_node = tree.body[0]
        decorator = func_node.decorator_list[0]
        assert _is_fixture_decorator_standalone(decorator=decorator) is True

    def test_non_fixture_decorator(self):
        source = textwrap.dedent("""\
            @pytest.mark.smoke
            def my_test():
                pass
        """)
        tree = ast.parse(source)
        func_node = tree.body[0]
        decorator = func_node.decorator_list[0]
        assert _is_fixture_decorator_standalone(decorator=decorator) is False

    def test_random_decorator(self):
        source = textwrap.dedent("""\
            @my_decorator
            def my_func():
                pass
        """)
        tree = ast.parse(source)
        func_node = tree.body[0]
        decorator = func_node.decorator_list[0]
        assert _is_fixture_decorator_standalone(decorator=decorator) is False


class TestParseDiffForFunctions:
    def test_single_function_modified(self):
        diff_content = textwrap.dedent("""\
            @@ -10,6 +10,7 @@ def my_function(arg):
                 existing_code()
            +    new_code()
                 more_code()
        """)
        result = _parse_diff_for_functions(diff_content=diff_content)
        assert result == {"my_function"}

    def test_multiple_functions_modified(self):
        diff_content = textwrap.dedent("""\
            @@ -10,6 +10,7 @@ def func_one():
                 existing()
            +    added()
            @@ -30,6 +31,7 @@ def func_two():
                 existing()
            +    also_added()
        """)
        result = _parse_diff_for_functions(diff_content=diff_content)
        assert result == {"func_one", "func_two"}

    def test_no_functions_modified(self):
        diff_content = textwrap.dedent("""\
            @@ -1,3 +1,4 @@
             import os
            +import sys
             import re
        """)
        result = _parse_diff_for_functions(diff_content=diff_content)
        assert result == set()

    def test_async_function_modified(self):
        diff_content = textwrap.dedent("""\
            @@ -10,6 +10,7 @@ async def async_handler(request):
                 data = await fetch()
            +    log(data)
                 return data
        """)
        result = _parse_diff_for_functions(diff_content=diff_content)
        assert result == {"async_handler"}

    def test_comment_only_changes_ignored(self):
        diff_content = textwrap.dedent("""\
            @@ -10,6 +10,7 @@ def my_function():
                 code()
            +    # this is just a comment
                 more_code()
        """)
        result = _parse_diff_for_functions(diff_content=diff_content)
        assert result == set()

    def test_whitespace_only_changes_ignored(self):
        diff_content = textwrap.dedent("""\
            @@ -10,6 +10,7 @@ def my_function():
                 code()
            +
                 more_code()
        """)
        result = _parse_diff_for_functions(diff_content=diff_content)
        assert result == set()


class TestSymbolClassificationModifiedMembers:
    def test_default_empty_dict(self):
        classification = SymbolClassification(
            modified_symbols=set(),
            new_symbols=set(),
        )
        assert classification.modified_members == {}

    def test_with_modified_members(self):
        members = {"MyClass": {"method_a", "method_b"}}
        classification = SymbolClassification(
            modified_symbols={"MyClass"},
            new_symbols=set(),
            modified_members=members,
        )
        assert classification.modified_members == members
        assert "method_a" in classification.modified_members["MyClass"]


class TestGetModifiedFunctionNames:
    """Tests for _get_modified_function_names return type semantics."""

    def test_returns_none_when_github_api_returns_no_diff(self, tmp_path: Path) -> None:
        """When GitHub API returns empty/None diff_content, function returns None."""
        file_path = tmp_path / "conftest.py"
        file_path.write_text("def my_func(): pass\n")
        github_pr_info = {"repo": "org/repo", "pr_number": 1, "token": "fake"}

        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.get_pr_file_diff",
            return_value="",
        ):
            result = _get_modified_function_names(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=github_pr_info,
            )

        assert result is None

    def test_returns_set_when_github_api_returns_valid_diff(self, tmp_path: Path) -> None:
        """When GitHub API returns valid diff with no function changes, returns empty set."""
        file_path = tmp_path / "conftest.py"
        file_path.write_text("import os\n")
        github_pr_info = {"repo": "org/repo", "pr_number": 1, "token": "fake"}
        diff_content = "--- a/conftest.py\n+++ b/conftest.py\n@@ -1 +1 @@\n-import sys\n+import os\n"

        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.get_pr_file_diff",
            return_value=diff_content,
        ):
            result = _get_modified_function_names(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=github_pr_info,
            )

        assert result is not None
        assert result == set()

    def test_returns_none_when_git_diff_fails(self, tmp_path: Path) -> None:
        """When local git diff subprocess fails, returns None."""
        file_path = tmp_path / "conftest.py"
        file_path.write_text("def my_func(): pass\n")

        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            result = _get_modified_function_names(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is None

    def test_returns_none_when_git_diff_nonzero_returncode(self, tmp_path: Path) -> None:
        """When local git diff returns non-zero exit code, returns None."""
        file_path = tmp_path / "conftest.py"
        file_path.write_text("def my_func(): pass\n")

        mock_result = type("Result", (), {"returncode": 128, "stdout": "", "stderr": "fatal: bad revision"})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _get_modified_function_names(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is None

    def test_returns_empty_set_for_module_level_only_diff(self, tmp_path: Path) -> None:
        """When git diff succeeds but only module-level lines changed, returns empty set."""
        file_path = tmp_path / "conftest.py"
        file_path.write_text("import os\n")
        diff_content = "--- a/conftest.py\n+++ b/conftest.py\n@@ -1 +1 @@\n-import sys\n+import os\n"

        mock_result = type("Result", (), {"returncode": 0, "stdout": diff_content, "stderr": ""})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _get_modified_function_names(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is not None
        assert result == set()

    def test_returns_function_names_from_cache(self, tmp_path: Path) -> None:
        """When diff is in pr_diffs_cache, returns parsed function names."""
        file_path = tmp_path / "conftest.py"
        file_path.write_text("def my_fixture(): pass\n")
        diff_content = (
            "--- a/conftest.py\n"
            "+++ b/conftest.py\n"
            "@@ -1,3 +1,3 @@ def my_fixture\n"
            " def my_fixture():\n"
            "-    pass\n"
            "+    return 42\n"
        )

        result = _get_modified_function_names(
            file_path=file_path,
            base_branch="main",
            repo_root=tmp_path,
            github_pr_info=None,
            pr_diffs_cache={"conftest.py": diff_content},
        )

        assert result == {"my_fixture"}


class TestExtractModifiedItemsFromConftestDiffFailure:
    """Tests that _extract_modified_items_from_conftest handles diff failure vs empty diff correctly."""

    def test_module_level_changes_do_not_flag_all_fixtures(self, tmp_path: Path) -> None:
        """When only module-level imports change, no fixtures should be flagged.

        This is the core bug: module-level changes produce an empty set (not None)
        from _get_modified_function_names, meaning no functions were modified.
        The conftest should NOT return all fixtures as modified.
        """
        conftest = tmp_path / "conftest.py"
        conftest.write_text(
            textwrap.dedent("""\
            import pytest
            import os

            @pytest.fixture()
            def my_fixture():
                return 42

            @pytest.fixture()
            def another_fixture():
                return "hello"
        """)
        )

        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer._get_modified_function_names",
            return_value=set(),
        ):
            modified_fixtures, modified_functions = _extract_modified_items_from_conftest(
                changed_file=conftest,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert modified_fixtures == set()
        assert modified_functions == set()

    def test_diff_failure_returns_all_fixtures_conservatively(self, tmp_path: Path) -> None:
        """When diff retrieval fails (returns None), all fixtures returned conservatively."""
        conftest = tmp_path / "conftest.py"
        conftest.write_text(
            textwrap.dedent("""\
            import pytest

            @pytest.fixture()
            def my_fixture():
                return 42

            @pytest.fixture()
            def another_fixture():
                return "hello"
        """)
        )

        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer._get_modified_function_names",
            return_value=None,
        ):
            modified_fixtures, modified_functions = _extract_modified_items_from_conftest(
                changed_file=conftest,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert modified_fixtures == {"my_fixture", "another_fixture"}
        assert modified_functions == set()


class TestSymbolClassificationHasUnattributedChanges:
    """Tests for the has_unattributed_changes field on SymbolClassification."""

    def test_defaults_to_false(self) -> None:
        classification = SymbolClassification(modified_symbols={"foo"}, new_symbols=set())
        assert classification.has_unattributed_changes is False

    def test_can_be_set_to_true(self) -> None:
        classification = SymbolClassification(
            modified_symbols={"foo"},
            new_symbols=set(),
            has_unattributed_changes=True,
        )
        assert classification.has_unattributed_changes is True


class TestExtractModifiedSymbolsUnattributed:
    """Tests that _extract_modified_symbols handles unattributed lines correctly.

    When changed lines fall outside any named symbol (e.g., import statements,
    comments between functions), the function should set has_unattributed_changes
    instead of returning None.
    """

    def test_import_only_change_returns_classification_not_none(self, tmp_path: Path) -> None:
        """When only import lines change, returns SymbolClassification with has_unattributed_changes=True."""
        source = textwrap.dedent("""\
            import os

            def my_func():
                pass
        """)
        file_path = tmp_path / "module.py"
        file_path.write_text(source)

        # Diff that changes only the import line (line 1)
        diff_content = "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-import sys\n+import os\n"
        mock_result = type("Result", (), {"returncode": 0, "stdout": diff_content, "stderr": ""})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _extract_modified_symbols(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is not None, "Should return SymbolClassification, not None"
        assert result.modified_symbols == set()
        assert result.has_unattributed_changes is True

    def test_mixed_import_and_constant_change(self, tmp_path: Path) -> None:
        """When both an import and a constant change, returns both info."""
        source = textwrap.dedent("""\
            import os

            TIMEOUT = 60

            def my_func():
                pass
        """)
        file_path = tmp_path / "module.py"
        file_path.write_text(source)

        # Diff that changes both line 1 (import) and line 3 (constant)
        diff_content = (
            "--- a/module.py\n"
            "+++ b/module.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-import sys\n"
            "+import os\n"
            " \n"
            "-TIMEOUT = 30\n"
            "+TIMEOUT = 60\n"
        )
        mock_result = type("Result", (), {"returncode": 0, "stdout": diff_content, "stderr": ""})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _extract_modified_symbols(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is not None, "Should return SymbolClassification, not None"
        assert "TIMEOUT" in result.modified_symbols
        assert result.has_unattributed_changes is True

    def test_all_changes_within_symbols_no_unattributed(self, tmp_path: Path) -> None:
        """When all changed lines fall within symbols, has_unattributed_changes is False."""
        source = textwrap.dedent("""\
            TIMEOUT = 60

            def my_func():
                return 42
        """)
        file_path = tmp_path / "module.py"
        file_path.write_text(source)

        # Diff that changes only line 4 (inside my_func)
        diff_content = (
            "--- a/module.py\n+++ b/module.py\n@@ -3,2 +3,2 @@\n def my_func():\n-    return 0\n+    return 42\n"
        )
        mock_result = type("Result", (), {"returncode": 0, "stdout": diff_content, "stderr": ""})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _extract_modified_symbols(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is not None
        assert "my_func" in result.modified_symbols
        assert result.has_unattributed_changes is False

    def test_diff_failure_still_returns_none(self, tmp_path: Path) -> None:
        """When diff retrieval fails, still returns None (not SymbolClassification)."""
        file_path = tmp_path / "module.py"
        file_path.write_text("def foo(): pass\n")

        mock_result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "error"})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _extract_modified_symbols(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        assert result is None

    def test_pure_deletion_still_returns_none(self, tmp_path: Path) -> None:
        """When diff is pure deletion (no added lines), still returns None."""
        file_path = tmp_path / "module.py"
        file_path.write_text("def foo(): pass\n")

        # Diff with only deletions (no + lines except the +++ header)
        diff_content = "--- a/module.py\n+++ b/module.py\n@@ -1,3 +1 @@\n-import os\n-import sys\n def foo(): pass\n"
        mock_result = type("Result", (), {"returncode": 0, "stdout": diff_content, "stderr": ""})()
        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run",
            return_value=mock_result,
        ):
            result = _extract_modified_symbols(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info=None,
            )

        # Pure deletion should return None (conservative fallback)
        assert result is None

    def test_fetch_failure_falls_through_to_local_file(self, tmp_path: Path) -> None:
        """When _fetch_file_at_ref fails, should fall through to local file read instead of returning None.

        In --checkout mode the local file IS the PR HEAD, so returning None
        (file-level fallback) is a false positive.  The function must read
        the local file and continue with symbol-level analysis.
        """
        source = textwrap.dedent("""\
            def my_func():
                return 42
        """)
        file_path = tmp_path / "module.py"
        file_path.write_text(source)

        # Diff that changes line 2 (inside my_func)
        diff_content = (
            "--- a/module.py\n+++ b/module.py\n@@ -1,2 +1,2 @@\n def my_func():\n-    return 0\n+    return 42\n"
        )
        pr_diffs_cache = {"module.py": diff_content}

        with patch(
            "scripts.tests_analyzer.pytest_marker_analyzer._fetch_file_at_ref",
            return_value=None,
        ):
            result = _extract_modified_symbols(
                file_path=file_path,
                base_branch="main",
                repo_root=tmp_path,
                github_pr_info={"repo": "owner/repo"},
                pr_diffs_cache=pr_diffs_cache,
                pr_head_ref="abc123",
            )

        assert result is not None, "Should fall through to local file, not return None"
        assert "my_func" in result.modified_symbols


class TestRunGithubModeCheckoutGithubPrInfo:
    """Verify that checkout mode passes github_pr_info to MarkerTestAnalyzer.

    When --checkout is used, the analyzer must still receive github_pr_info
    so the GitHub API diffs cache is available as fallback when local git
    diff fails (e.g., base branch fetch failure or shallow clone).
    """

    @patch("scripts.tests_analyzer.pytest_marker_analyzer.cleanup_temp_dir")
    @patch("scripts.tests_analyzer.pytest_marker_analyzer.os.chdir")
    @patch("scripts.tests_analyzer.pytest_marker_analyzer.subprocess.run")
    @patch("scripts.tests_analyzer.pytest_marker_analyzer.checkout_pr")
    @patch("scripts.tests_analyzer.pytest_marker_analyzer.get_pr_changed_files", return_value=["some_file.py"])
    @patch(
        "scripts.tests_analyzer.pytest_marker_analyzer.get_pr_info",
        return_value={"base_ref": "main", "head_ref": "feature-branch"},
    )
    @patch("scripts.tests_analyzer.pytest_marker_analyzer.MarkerTestAnalyzer")
    def test_checkout_mode_passes_github_pr_info(
        self,
        mock_analyzer_cls,
        mock_get_pr_info,
        mock_get_changed_files,
        mock_checkout_pr,
        mock_subprocess_run,
        mock_chdir,
        mock_cleanup,
        tmp_path,
    ):
        """Checkout mode must pass github_pr_info dict, not None."""
        mock_analyzer = MagicMock()
        mock_analyzer.marked_tests = ["test_something"]
        mock_analyzer.analyze_impact.return_value = MagicMock()
        mock_analyzer_cls.return_value = mock_analyzer

        args = argparse.Namespace(
            repo="org/repo",
            pr=42,
            github_token="fake-token",
            checkout=True,
            workdir=tmp_path,
            work_dir=None,
            markers="smoke",
        )

        run_github_mode(args=args)

        constructor_kwargs = mock_analyzer_cls.call_args
        actual_github_pr_info = constructor_kwargs.kwargs["github_pr_info"]

        assert actual_github_pr_info is not None, (
            "github_pr_info must not be None in checkout mode; it is needed as fallback when local git diff fails"
        )
        assert actual_github_pr_info["repo"] == "org/repo"
        assert actual_github_pr_info["pr_number"] == 42
        assert actual_github_pr_info["token"] == "fake-token"


class TestCheckConftestPathwayNoFixtureMatch:
    """Conftest imports a modified symbol but no fixture used by the test calls it."""

    def test_no_fixture_calls_overlapping_symbol_does_not_flag(self, tmp_path: Path) -> None:
        """When no fixture calls the overlapping symbol the test should NOT be flagged.

        Previously this was a false positive: the analyzer conservatively flagged
        the test even though no fixture connected the modified symbol to the test.
        """
        repo_root = tmp_path
        conftest_path = tmp_path / "tests" / "conftest.py"
        conftest_path.parent.mkdir(parents=True)
        conftest_path.touch()

        changed_file = tmp_path / "utilities" / "network.py"
        changed_file.parent.mkdir(parents=True)
        changed_file.touch()

        test_file = tmp_path / "tests" / "test_vm_deletion.py"
        test_file.touch()

        marked_test = MarkedTest(
            file_path=test_file,
            test_name="test_vm_deletion",
            node_id="tests/test_vm_deletion.py::test_vm_deletion",
            dependencies={conftest_path},
            fixtures={"some_unrelated_fixture"},
            symbol_imports={},
        )

        # Conftest imports lookup_iface_status from the changed file
        conftest_symbol_imports: dict[Path, dict[Path, set[str]]] = {
            conftest_path: {changed_file: {"lookup_iface_status"}},
        }

        # lookup_iface_status was modified
        modified_symbols_cache: dict[Path, SymbolClassification | None] = {
            changed_file: SymbolClassification(
                modified_symbols={"lookup_iface_status"},
                new_symbols=set(),
            ),
        }

        # The fixture used by the test does NOT call lookup_iface_status
        fixtures_dict: dict[str, Fixture] = {
            "some_unrelated_fixture": Fixture(
                name="some_unrelated_fixture",
                file_path=conftest_path,
                function_calls={"other_function"},
            ),
        }

        is_affected, matching_deps = _check_conftest_pathway(
            changed_file=changed_file,
            marked_test=marked_test,
            conftest_symbol_imports=conftest_symbol_imports,
            conftest_opaque_deps={},
            modified_symbols_cache=modified_symbols_cache,
            fixtures_dict=fixtures_dict,
            repo_root=repo_root,
        )

        assert not is_affected, (
            f"Test should NOT be flagged when no fixture calls the modified symbol, "
            f"but got matching_deps={matching_deps}"
        )
        assert matching_deps == []
