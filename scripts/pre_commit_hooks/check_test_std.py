"""Check product-test documentation and placeholder-state regressions."""

from __future__ import annotations

from ast import (
    AST,
    AnnAssign,
    Assign,
    AsyncFunctionDef,
    Attribute,
    Call,
    ClassDef,
    Constant,
    Expr,
    FunctionDef,
    Import,
    ImportFrom,
    Module,
    Name,
    Pass,
    dump,
    get_docstring,
    iter_child_nodes,
    parse,
    stmt,
)
from dataclasses import dataclass
from pathlib import Path
from re import IGNORECASE, compile
from typing import TYPE_CHECKING

from scripts.pre_commit_hooks.policy_types import PolicyViolation

if TYPE_CHECKING:
    from collections.abc import Sequence

_SECTION_HEADER = compile(
    pattern=r"^\s*(Preconditions|Steps|Expected|Markers|Parametrize):\s*(.*)$",
    flags=IGNORECASE,
)
_SECTION_ITEM_PREFIX = compile(pattern=r"^\s*(?:[-*+]|\d+[.)])?\s*")
_TRACKING_URL = compile(pattern=r"https?://[^\s)>\]]+")
_JIRA_URL = compile(
    pattern=r"https?://(?:issues\.redhat\.com|redhat\.atlassian\.net)/browse/[A-Z][A-Z0-9]+-\d+",
    flags=IGNORECASE,
)
_STP_URL = compile(
    pattern=r"https?://github\.com/RedHatQE/openshift-virtualization-tests-design-docs/(?:blob|tree)/[^\s]*/stps/",
    flags=IGNORECASE,
)
_PLACEHOLDERS = frozenset({"", "-", ".", "n/a", "none", "tba", "tbd", "todo"})
_JIRA_SKIP_MARKER = "# <skip-jira-utils-check>"
_MANUAL_MARKER = "pytest.mark.manual"
_UNRELATED_BINDING = "other"


@dataclass(frozen=True, slots=True)
class _TestDefinition:
    qualified_name: str
    node: FunctionDef | AsyncFunctionDef
    docs: tuple[str, ...]
    placeholder: bool
    disabled: bool
    manual: bool


def is_product_test_path(file_path: Path) -> bool:
    """Return whether a path is a product test module covered by STD checks.

    Args:
        file_path: Repository-relative candidate path.

    Returns:
        ``True`` only for test modules below a product feature in ``tests/``.
    """
    return (
        len(file_path.parts) >= 3
        and file_path.parts[0] == "tests"
        and (file_path.name.startswith("test_") or file_path.stem.endswith("_test"))
        and file_path.suffix == ".py"
    )


def _boolean_assignment(statements: Sequence[stmt], target_name: str | None = None) -> bool | None:
    value: bool | None = None
    for statement in statements:
        if not isinstance(statement, (Assign, AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, Assign) else [statement.target]
        assigned_value = statement.value
        if not isinstance(assigned_value, Constant) or not isinstance(assigned_value.value, bool):
            continue
        for target in targets:
            if target_name is None and isinstance(target, Name) and target.id == "__test__":
                value = assigned_value.value
            elif (
                target_name is not None
                and isinstance(target, Attribute)
                and isinstance(target.value, Name)
                and target.value.id == target_name
                and target.attr == "__test__"
            ):
                value = assigned_value.value
    return value


def _docstring_only(node: FunctionDef | AsyncFunctionDef) -> bool:
    if not (
        node.body
        and isinstance(node.body[0], Expr)
        and isinstance(node.body[0].value, Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return False
    return all(
        isinstance(statement, Pass)
        or (isinstance(statement, Expr) and isinstance(statement.value, Constant) and statement.value.value is Ellipsis)
        for statement in node.body[1:]
    )


def _scope_statements(statements: Sequence[stmt]) -> Sequence[stmt]:
    collected: list[stmt] = []

    def collect_children(node: AST) -> None:
        for child in iter_child_nodes(node):
            if isinstance(child, stmt):
                collected.append(child)
                if not isinstance(child, (ClassDef, FunctionDef, AsyncFunctionDef)):
                    collect_children(node=child)
            else:
                collect_children(node=child)

    for statement in statements:
        collected.append(statement)
        if not isinstance(statement, (ClassDef, FunctionDef, AsyncFunctionDef)):
            collect_children(node=statement)
    return collected


@dataclass(frozen=True)
class _MarkerRoots:
    """Module-scope name bindings used to resolve manual markers."""

    bindings: dict[str, str]

    def resolve(self, chain: Sequence[str]) -> str | None:
        """Resolve a decorator name chain to its canonical dotted path.

        Args:
            chain: Decorator attribute chain, root name first (for example
                ``["m", "manual"]``).

        Returns:
            The canonical dotted path the chain resolves to (for example
            ``pytest.mark.manual``), or ``None`` when the root is bound to an
            unrelated name or the chain has no by-name meaning.
        """
        if not chain:
            return None
        root = chain[0]
        if root in self.bindings:
            binding = self.bindings[root]
            if binding == _UNRELATED_BINDING:
                return None
            return ".".join((binding, *chain[1:]))
        if root == "pytest":
            return ".".join(chain)
        if root == "mark":
            return ".".join(("pytest", *chain))
        return None


def _marker_roots(tree: Module) -> _MarkerRoots:
    """Map module-scope names to the canonical pytest paths they are bound to.

    Args:
        tree: Parsed module.

    Returns:
        Bindings from each module-scope name to the dotted pytest path it
        resolves to (for example ``from pytest import mark as m`` binds ``m``
        to ``pytest.mark``), or to an unrelated sentinel when the last binding
        points elsewhere, so a shadowed root such as ``from framework import
        pytest`` cannot satisfy the manual-marker requirement. Names with no
        visible module-scope binding stay unbound and keep their by-name
        meaning.
    """
    bindings: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, Import):
            for alias in statement.names:
                bound_name = alias.asname or alias.name.split(sep=".")[0]
                from_pytest = alias.name == "pytest" or alias.name.startswith("pytest.")
                bindings[bound_name] = (
                    alias.name if alias.asname and from_pytest else (bound_name if from_pytest else _UNRELATED_BINDING)
                )
        elif isinstance(statement, ImportFrom):
            for alias in statement.names:
                bound_name = alias.asname or alias.name
                bindings[bound_name] = f"pytest.{alias.name}" if statement.module == "pytest" else _UNRELATED_BINDING
        elif isinstance(statement, Assign):
            for target in statement.targets:
                if isinstance(target, Name):
                    bindings[target.id] = _UNRELATED_BINDING
    return _MarkerRoots(bindings=bindings)


def _definitions(tree: Module) -> list[_TestDefinition]:
    module_doc = get_docstring(node=tree, clean=False) or ""
    marker_roots = _marker_roots(tree=tree)
    module_scope_statements = _scope_statements(statements=tree.body)
    module_disabled = _boolean_assignment(statements=module_scope_statements) is False
    definitions: list[_TestDefinition] = []

    def collect_class(
        node: ClassDef,
        parents: tuple[str, ...],
        inherited_docs: tuple[str, ...],
        inherited_disabled: bool,
    ) -> None:
        class_doc = get_docstring(node=node, clean=False) or ""
        class_scope_statements = _scope_statements(statements=node.body)
        class_disabled = inherited_disabled or _boolean_assignment(statements=class_scope_statements) is False
        class_parents = (*parents, node.name)
        class_docs = (class_doc, *inherited_docs)
        for child in class_scope_statements:
            if isinstance(child, ClassDef):
                collect_class(
                    node=child,
                    parents=class_parents,
                    inherited_docs=class_docs,
                    inherited_disabled=class_disabled,
                )
            elif isinstance(child, (FunctionDef, AsyncFunctionDef)) and child.name.startswith("test_"):
                function_disabled = (
                    _boolean_assignment(statements=class_scope_statements, target_name=child.name) is False
                )
                qualified_name = ".".join((*class_parents, child.name))
                definitions.append(
                    _TestDefinition(
                        qualified_name=qualified_name,
                        node=child,
                        docs=(get_docstring(node=child, clean=False) or "", *class_docs),
                        placeholder=_docstring_only(node=child),
                        disabled=class_disabled or function_disabled,
                        manual=_has_manual_marker(node=child, marker_roots=marker_roots),
                    )
                )

    for node in module_scope_statements:
        if isinstance(node, ClassDef):
            collect_class(
                node=node,
                parents=(),
                inherited_docs=(module_doc,),
                inherited_disabled=module_disabled,
            )
        elif isinstance(node, (FunctionDef, AsyncFunctionDef)) and node.name.startswith("test_"):
            function_disabled = _boolean_assignment(statements=module_scope_statements, target_name=node.name) is False
            definitions.append(
                _TestDefinition(
                    qualified_name=node.name,
                    node=node,
                    docs=(get_docstring(node=node, clean=False) or "", module_doc),
                    placeholder=_docstring_only(node=node),
                    disabled=module_disabled or function_disabled,
                    manual=_has_manual_marker(node=node, marker_roots=marker_roots),
                )
            )
    return definitions


def _sections(docstring: str) -> tuple[str, dict[str, list[str]]]:
    description: list[str] = []
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for line in docstring.splitlines():
        if match := _SECTION_HEADER.match(string=line):
            current_section = match.group(1).lower()
            sections.setdefault(current_section, []).append(match.group(2))
        elif current_section is None:
            description.append(line)
        else:
            sections[current_section].append(line)
    return "\n".join(description), sections


def _meaningful(lines: Sequence[str]) -> bool:
    for line in lines:
        without_urls = _TRACKING_URL.sub(repl="", string=line)
        without_marker = without_urls.replace(_JIRA_SKIP_MARKER, "")
        content = _SECTION_ITEM_PREFIX.sub(repl="", string=without_marker).strip(" \t\r\n-*.)0123456789:").lower()
        if content in {"jira", "rfe", "stp"}:
            content = ""
        if content not in _PLACEHOLDERS:
            return True
    return False


def _has_tracking_url(docstrings: Sequence[str]) -> bool:
    for docstring in docstrings:
        for line in docstring.splitlines():
            for url in _TRACKING_URL.findall(string=line):
                if _JIRA_URL.fullmatch(string=url) or _STP_URL.match(string=url):
                    return True
    return False


def _has_manual_marker(node: FunctionDef | AsyncFunctionDef, marker_roots: _MarkerRoots) -> bool:
    """Return whether the test carries a direct ``@pytest.mark.manual`` decorator.

    The attribute chain must resolve to ``pytest.mark.manual`` through the
    module-scope bindings: a plain ``pytest.mark.manual`` chain, the bare
    ``mark.manual`` produced by ``from pytest import mark``, or an aliased
    binding such as ``from pytest import mark as m`` used as ``@m.manual``.
    A root name bound at module scope to something other than the pytest
    marker chain (for example ``from framework import pytest`` or
    ``from pytest import fixture as mark``) cannot satisfy the requirement.

    Args:
        node: Test function or method definition.
        marker_roots: Module-scope root bindings, from ``_marker_roots``.

    Returns:
        ``True`` only when the decorator sits on the test itself; enclosing class or
        module markers are deliberately ignored.
    """
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, Call) else decorator
        names: list[str] = []
        while isinstance(target, Attribute):
            names.append(target.attr)
            target = target.value
        if isinstance(target, Name):
            names.append(target.id)
        resolved = list(reversed(names))
        if resolved and marker_roots.resolve(chain=resolved) == _MANUAL_MARKER:
            return True
    return False


def _jira_lines_missing_skip_marker(docstring: str) -> bool:
    """Return whether any Jira link in the docstring omits the jira-utils skip marker.

    Args:
        docstring: Test docstring to inspect.

    Returns:
        ``True`` when a Jira URL appears on a line without ``# <skip-jira-utils-check>``.
    """
    return any(_JIRA_URL.search(string=line) and _JIRA_SKIP_MARKER not in line for line in docstring.splitlines())


def _documentation_violations(file_path: Path, definition: _TestDefinition) -> list[PolicyViolation]:
    test_doc = definition.docs[0]
    description, sections = _sections(docstring=test_doc)
    violations: list[PolicyViolation] = []

    def add(message: str) -> None:
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: {message}",
            )
        )

    if not _meaningful(lines=[description]):
        add(message="add a nonempty test description before the STD sections")
    for section in ("steps", "expected"):
        if not _meaningful(lines=sections.get(section, [])):
            add(message=f"add a nonempty {section.title()}: section to the test docstring")
    if not any(_meaningful(lines=_sections(docstring=doc)[1].get("preconditions", [])) for doc in definition.docs):
        add(message="add nonempty Preconditions: at test, enclosing class, or module level")
    if not _has_tracking_url(docstrings=definition.docs):
        add(message="add an STP link or Jira/RFE tracking URL to the test, class, or module docstring")
    return violations


def _new_test_documentation_violations(file_path: Path, definition: _TestDefinition) -> list[PolicyViolation]:
    """Return documentation violations for a new test, whose traceability must be its own.

    Args:
        file_path: Repository-relative test path.
        definition: Parsed indexed test definition.

    Returns:
        Violations that do not depend on a ``HEAD`` baseline to interpret.
    """
    inherited = _documentation_violations(file_path=file_path, definition=definition)
    violations = [
        violation
        for violation in inherited
        if violation.message != f"test-std/{definition.qualified_name}: "
        "add an STP link or Jira/RFE tracking URL to the test, class, or module docstring"
    ]
    if not _has_tracking_url(docstrings=(definition.docs[0],)):
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: "
                "add an STP link or Jira/RFE tracking URL to the test docstring",
            )
        )
    elif _jira_lines_missing_skip_marker(docstring=definition.docs[0]):
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: add {_JIRA_SKIP_MARKER} to this Jira line",
            )
        )
    return violations


def _new_test_violations(file_path: Path, definition: _TestDefinition) -> list[PolicyViolation]:
    violations = _new_test_documentation_violations(file_path=file_path, definition=definition)

    if definition.placeholder and not definition.disabled:
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: "
                "mark this docstring-only STD placeholder with effective __test__ = False",
            )
        )
    if not definition.placeholder and definition.disabled:
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: "
                "remove effective __test__ = False from this implemented test",
            )
        )
    if definition.placeholder and definition.disabled and not definition.manual:
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: declare @pytest.mark.manual on this test",
            )
        )
    if definition.manual and not definition.disabled and not definition.placeholder:
        violations.append(
            PolicyViolation(
                file_path=file_path,
                line_number=definition.node.lineno,
                message=f"test-std/{definition.qualified_name}: remove @pytest.mark.manual from this implemented test",
            )
        )
    return violations


def _transition_violations(
    file_path: Path,
    current: _TestDefinition,
    previous: _TestDefinition,
) -> list[PolicyViolation]:
    message: str | None = None
    if not previous.placeholder and current.placeholder:
        message = (
            "do not replace an implemented test with a docstring-only placeholder; "
            "restore its implementation rather than changing __test__"
        )
    elif previous.placeholder and current.placeholder and previous.disabled and not current.disabled:
        message = "keep effective __test__ = False until this placeholder is implemented"
    elif previous.placeholder and not current.placeholder and current.disabled:
        message = "remove effective __test__ = False when implementing this placeholder"
    elif not previous.placeholder and not previous.disabled and current.disabled:
        message = "remove newly effective __test__ = False from implemented test"
    messages = [message] if message is not None else []
    # Manual classification is reported independently so it is never masked by the
    # placeholder-state message above.
    if previous.manual and not current.manual and current.disabled:
        messages.append("declare @pytest.mark.manual on this test")
    if current.manual and not current.disabled and not current.placeholder:
        messages.append("remove @pytest.mark.manual from this implemented test")
    return [
        PolicyViolation(
            file_path=file_path,
            line_number=current.node.lineno,
            message=f"test-std/{current.qualified_name}: {message}",
        )
        for message in messages
    ]


def check_test_std(
    file_path: Path,
    indexed_source: str,
    head_source: str | None,
) -> list[PolicyViolation]:
    """Check new tests and documentation or placeholder regressions against ``HEAD``.

    Args:
        file_path: Repository-relative staged test path.
        indexed_source: Complete source from the Git index.
        head_source: Source at ``HEAD``, or ``None`` for a new or copied file.

    Returns:
        Structural STD and placeholder-state violations.
    """
    if not is_product_test_path(file_path=file_path):
        return []
    indexed = _definitions(tree=parse(source=indexed_source, filename=str(file_path)))
    head = _definitions(tree=parse(source=head_source, filename=str(file_path))) if head_source is not None else []
    indexed_by_name: dict[str, list[_TestDefinition]] = {}
    head_by_name: dict[str, list[_TestDefinition]] = {}
    for definition in indexed:
        indexed_by_name.setdefault(definition.qualified_name, []).append(definition)
    for definition in head:
        head_by_name.setdefault(definition.qualified_name, []).append(definition)

    violations = [
        violation
        for definition in indexed
        if definition.qualified_name not in head_by_name
        for violation in _new_test_violations(file_path=file_path, definition=definition)
    ]
    for qualified_name in indexed_by_name.keys() & head_by_name.keys():
        current_definitions = indexed_by_name[qualified_name]
        previous_definitions = head_by_name[qualified_name]
        unmatched_previous = list(previous_definitions)
        unmatched_current: list[_TestDefinition] = []
        retained_pairs: list[tuple[_TestDefinition, _TestDefinition]] = []

        for current in current_definitions:
            current_identity = dump(node=current.node, include_attributes=False)
            for position, previous in enumerate(unmatched_previous):
                if current_identity == dump(node=previous.node, include_attributes=False):
                    retained_pairs.append((current, previous))
                    unmatched_previous.pop(position)
                    break
            else:
                unmatched_current.append(current)

        paired_count = min(len(unmatched_current), len(unmatched_previous))
        retained_pairs.extend(zip(unmatched_current[:paired_count], unmatched_previous[:paired_count], strict=True))
        for current, previous in retained_pairs:
            previous_documentation_messages = {
                violation.message for violation in _documentation_violations(file_path=file_path, definition=previous)
            }
            violations.extend(
                violation
                for violation in _documentation_violations(file_path=file_path, definition=current)
                if violation.message not in previous_documentation_messages
            )
            violations.extend(_transition_violations(file_path=file_path, current=current, previous=previous))

        previous_documentation_messages = {
            violation.message
            for previous in previous_definitions
            for violation in _documentation_violations(file_path=file_path, definition=previous)
        }
        previous_states = {(previous.placeholder, previous.disabled) for previous in previous_definitions}
        for current in unmatched_current[paired_count:]:
            violations.extend(
                violation
                for violation in _documentation_violations(file_path=file_path, definition=current)
                if violation.message not in previous_documentation_messages
            )
            if len(previous_states) == 1:
                violations.extend(
                    _transition_violations(file_path=file_path, current=current, previous=previous_definitions[0])
                )
    return sorted(violations, key=lambda violation: (violation.line_number or 0, violation.message))
