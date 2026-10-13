"""Integration tests for staged Git input to pre-commit policy checks."""

from __future__ import annotations

from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING

from pyhelper_utils.shell import run_command
from pytest import mark, raises

from scripts.pre_commit_hooks import check_policy
from scripts.pre_commit_hooks.check_policy import main
from scripts.pre_commit_hooks.tests.git_repository import commit_all, initialize_git_repository, stage_paths

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


_RELATIVE_RESOURCE_IMPORT = "from .wrappers import Wrapped\n\nLEGACY = True\n"
_RESOURCE_WRAPPER = "from ocp_resources.resource import Resource\n\nclass Wrapped(Resource):\n    pass\n"


@mark.parametrize(
    ("target", "addition"),
    (
        ("utilities/pkg/caller.py", "\nWrapped()\n"),
        ("utilities/pkg/caller.py", "\nclass Child(Wrapped):\n    pass\n\nChild()\n"),
        ("utilities/pkg/__init__.py", "\nWrapped()\n"),
        ("utilities/pkg/__init__.py", "\nclass Child(Wrapped):\n    pass\n\nChild()\n"),
    ),
)
def test_main_resolves_unchanged_relative_resource_imports_from_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    target: str,
    addition: str,
) -> None:
    """Legacy relative imports resolve Resource calls from indexed wrappers in modules and packages."""
    initialize_git_repository(repository_root=tmp_path)
    package_root = tmp_path / "utilities/pkg"
    package_root.mkdir(parents=True)
    (tmp_path / "utilities/__init__.py").write_text(data="", encoding="utf-8")
    (package_root / "wrappers.py").write_text(data=_RESOURCE_WRAPPER, encoding="utf-8")
    target_path = tmp_path / target
    target_path.write_text(data=_RELATIVE_RESOURCE_IMPORT, encoding="utf-8")
    commit_all(repository_root=tmp_path)
    target_path.write_text(data=_RELATIVE_RESOURCE_IMPORT + addition, encoding="utf-8")
    stage_paths(repository_root=tmp_path, paths=(target,))
    (tmp_path / "utilities/pkg/wrappers.py").write_text(data="class Wrapped:\n    pass\n", encoding="utf-8")
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[target]) == 1, (
        "a new Resource call through an unchanged relative import must use indexed wrapper inheritance"
    )


@mark.parametrize(
    ("baseline", "staged_source", "expected"),
    (
        (
            "LEGACY = True\n",
            "from .wrappers import Wrapped\n\nLEGACY = True\n\nWrapped()\n",
            1,
        ),
        (
            "from utilities.pkg.wrappers import Wrapped\n\nLEGACY = True\n",
            "from utilities.pkg.wrappers import Wrapped\n\nLEGACY = True\n\nWrapped()\n",
            1,
        ),
        (
            _RELATIVE_RESOURCE_IMPORT,
            _RELATIVE_RESOURCE_IMPORT + "\nWrapped(client=None)\n",
            1,
        ),
        (
            _RELATIVE_RESOURCE_IMPORT,
            _RELATIVE_RESOURCE_IMPORT + "\nWrapped(client=client)\n",
            0,
        ),
    ),
)
def test_main_preserves_relative_import_and_resource_client_controls(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    baseline: str,
    staged_source: str,
    expected: int,
) -> None:
    """New relative imports and invalid clients fail while absolute and explicit-client behavior remains stable."""
    target = "utilities/pkg/caller.py"
    initialize_git_repository(repository_root=tmp_path)
    package_root = tmp_path / "utilities/pkg"
    package_root.mkdir(parents=True)
    (tmp_path / "utilities/__init__.py").write_text(data="", encoding="utf-8")
    (package_root / "wrappers.py").write_text(data=_RESOURCE_WRAPPER, encoding="utf-8")
    target_path = tmp_path / target
    target_path.write_text(data=baseline, encoding="utf-8")
    commit_all(repository_root=tmp_path)
    target_path.write_text(data=staged_source, encoding="utf-8")
    stage_paths(repository_root=tmp_path, paths=(target,))
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[target]) == expected, (
        "the policy hook must report exactly the expected violations for the staged source"
    )


def test_main_uses_index_content_when_worktree_differs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Policy checks inspect the staged source rather than unstaged worktree edits."""
    initialize_git_repository(repository_root=tmp_path)
    (tmp_path / "example.py").write_text(data="value = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "scripts/pre_commit_hooks/exceptions.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(data="exceptions = []\n", encoding="utf-8")
    commit_all(repository_root=tmp_path)

    (tmp_path / "example.py").write_text(data="value = 2\n", encoding="utf-8")
    run_command(command=["git", "add", "example.py"], cwd=tmp_path, check=True, verify_stderr=False)
    (tmp_path / "example.py").write_text(data="pytest.skip(reason='worktree only')\n", encoding="utf-8")
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=["example.py"]) == 0, "unstaged violations must not affect the staged result"

    (tmp_path / "example.py").write_text(data="pytest.skip(reason='staged')\n", encoding="utf-8")
    run_command(command=["git", "add", "example.py"], cwd=tmp_path, check=True, verify_stderr=False)
    (tmp_path / "example.py").write_text(data="value = 3\n", encoding="utf-8")

    assert main(arguments=["example.py"]) == 1, "a violation in the staged result must be reported"


def test_main_handles_quoted_space_and_unicode_filenames(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Staged source with spaces, quotes, and Unicode in its filename is checked."""
    initialize_git_repository(repository_root=tmp_path)
    run_command(command=["git", "config", "core.quotePath", "true"], cwd=tmp_path, check=True, verify_stderr=False)
    file_path = tmp_path / 'example "quoted" é.py'
    file_path.write_text(data="client = DynamicClient(api_client)\n", encoding="utf-8")
    manifest_path = tmp_path / "scripts/pre_commit_hooks/exceptions.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(data="exceptions = []\n", encoding="utf-8")
    stage_paths(repository_root=tmp_path, paths=(".",))
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[file_path.name]) == 1, "quoted and Unicode filenames must retain their staged source"


def test_main_handles_rename_copy_and_deletion_statuses(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Renamed and copied files are checked while deleted files are skipped."""
    initialize_git_repository(repository_root=tmp_path)
    (tmp_path / "old.py").write_text(data="value = 1\n", encoding="utf-8")
    (tmp_path / "copy-source.py").write_text(data="value = 2\n", encoding="utf-8")
    (tmp_path / "gone.py").write_text(data="value = 3\n", encoding="utf-8")
    manifest_path = tmp_path / "scripts/pre_commit_hooks/exceptions.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(data="exceptions = []\n", encoding="utf-8")
    commit_all(repository_root=tmp_path)

    run_command(command=["git", "mv", "old.py", "renamed.py"], cwd=tmp_path, check=True, verify_stderr=False)
    copyfile(src=tmp_path / "copy-source.py", dst=tmp_path / "copied.py")
    run_command(command=["git", "rm", "-q", "gone.py"], cwd=tmp_path, check=True, verify_stderr=False)
    run_command(command=["git", "add", "copied.py"], cwd=tmp_path, check=True, verify_stderr=False)
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=["old.py", "renamed.py", "copied.py", "gone.py"]) == 0, (
        "renames and copies should check their new content while deletions are ignored"
    )


def test_main_checks_copied_file_full_policy_when_only_other_hunks_changed(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A copied Python file with a changed hunk still receives full-file policy checking."""
    initialize_git_repository(repository_root=tmp_path)
    source_path = tmp_path / "copy-source.py"
    source_path.write_text(data="pytest.skip(reason='legacy')\nvalue = 1\n", encoding="utf-8")
    commit_all(repository_root=tmp_path)

    copied_path = tmp_path / "copied.py"
    copyfile(src=source_path, dst=copied_path)
    copied_path.write_text(data="pytest.skip(reason='legacy')\nvalue = 2\n", encoding="utf-8")
    stage_paths(repository_root=tmp_path, paths=("copied.py",))
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=["copied.py"]) == 1, (
        "copied files must check unchanged violation lines as well as changed hunks"
    )


def test_main_checks_renamed_test_with_full_std_validation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Renaming a test module must not let it inherit its old path's STD baseline."""
    initialize_git_repository(repository_root=tmp_path)
    old_path = tmp_path / "tests/network/test_original.py"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(
        data='''"""Jira: https://issues.redhat.com/browse/CNV-88909"""

def test_behavior():
    """Original behavior.

    Preconditions:
    - the component is available
    Steps:
    - exercise the behavior
    Expected:
    - the behavior succeeds
    """
    pass
''',
        encoding="utf-8",
    )
    commit_all(repository_root=tmp_path)
    new_path = old_path.with_name("test_renamed.py")
    run_command(
        command=["git", "mv", str(old_path.relative_to(tmp_path)), str(new_path.relative_to(tmp_path))],
        cwd=tmp_path,
        check=True,
        verify_stderr=False,
    )
    new_path.write_text(
        data='''"""Jira: https://issues.redhat.com/browse/CNV-88909"""

def test_behavior():
    """Original behavior.

    Preconditions:
    - the component is available
    """
    pass
''',
        encoding="utf-8",
    )
    stage_paths(repository_root=tmp_path, paths=(str(new_path.relative_to(tmp_path)),))
    success, status_output, _ = run_command(
        command=["git", "diff", "--cached", "--name-status", "-z", "--"],
        cwd=tmp_path,
        check=False,
        verify_stderr=False,
    )
    assert success and status_output.startswith("R"), "the fixture must exercise Git rename status handling"
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[str(new_path.relative_to(tmp_path))]) == 1, "renamed tests must receive full STD validation"


def test_main_checks_new_test_added_to_existing_staged_module(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A newly staged test function is checked even when its module already exists in HEAD."""
    initialize_git_repository(repository_root=tmp_path)
    test_path = tmp_path / "tests" / "network" / "test_existing.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        data='''"""Jira: https://issues.redhat.com/browse/CNV-88909"""

def test_existing():
    """Existing behavior.

    Preconditions:
    - the component is available
    Steps:
    - exercise the behavior
    Expected:
    - the behavior succeeds
    """
    assert condition, "the existing behavior should succeed"
''',
        encoding="utf-8",
    )
    manifest_path = tmp_path / "scripts/pre_commit_hooks/exceptions.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(data="exceptions = []\n", encoding="utf-8")
    commit_all(repository_root=tmp_path)

    test_path.write_text(
        data=test_path.read_text(encoding="utf-8") + "\ndef test_new():\n    pass\n",
        encoding="utf-8",
    )
    run_command(
        command=["git", "add", str(test_path.relative_to(tmp_path))], cwd=tmp_path, check=True, verify_stderr=False
    )
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[str(test_path.relative_to(tmp_path))]) == 1, (
        "a new test lacking STD documentation should be rejected"
    )


def test_main_reports_invalid_staged_manifest_even_for_unrelated_selected_path(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """An invalid staged manifest is checked independently of selected filenames."""
    initialize_git_repository(repository_root=tmp_path)
    unrelated_path = tmp_path / "README.md"
    unrelated_path.write_text(data="text\n", encoding="utf-8")
    manifest_path = tmp_path / "scripts/pre_commit_hooks/exceptions.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(data="not valid = [\n", encoding="utf-8")
    stage_paths(repository_root=tmp_path, paths=(".",))
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=["README.md"]) == 1, "invalid staged manifest must fail independently of selected paths"


def test_main_fails_clearly_when_python_is_staged_without_index_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Python additions require an exceptions manifest in the Git index."""
    initialize_git_repository(repository_root=tmp_path)
    (tmp_path / "example.py").write_text(data="value = 1\n", encoding="utf-8")
    (tmp_path / "scripts/pre_commit_hooks/exceptions.toml").unlink()
    run_command(command=["git", "add", "example.py"], cwd=tmp_path, check=True, verify_stderr=False)
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=["example.py"]) == 1, "a missing index manifest should return a policy failure"
    assert "exception manifest must exist in the Git index" in capsys.readouterr().err, (
        "the missing-manifest violation should explain how to fix the index snapshot"
    )


def test_main_propagates_git_failures_with_the_failing_command(monkeypatch: MonkeyPatch) -> None:
    """Git failures are not hidden behind a generic policy result."""
    monkeypatch.setattr(
        target=check_policy,
        name="run_command",
        value=lambda **kwargs: (False, "", "fatal: repository unavailable"),
    )

    with raises(expected_exception=RuntimeError, match=r"git diff --cached"):
        main(arguments=["example.py"])


def test_main_rejects_a_staged_top_level_test_path(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A staged test directly below tests/ is rejected before source policy checks."""
    initialize_git_repository(repository_root=tmp_path)
    test_path = tmp_path / "tests" / "test_policy.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(data="def test_policy():\n    pass\n", encoding="utf-8")
    stage_paths(
        repository_root=tmp_path,
        paths=("tests/test_policy.py", "scripts/pre_commit_hooks/exceptions.toml"),
    )
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=["tests/test_policy.py"]) == 1, "staged top-level test paths must be rejected"


def test_main_rejects_omitted_staged_top_level_test_path(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """A staged test directly below tests/ is rejected when hook filenames are omitted."""
    initialize_git_repository(repository_root=tmp_path)
    test_path = tmp_path / "tests" / "test_example.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(data="def test_example():\n    pass\n", encoding="utf-8")
    stage_paths(
        repository_root=tmp_path,
        paths=("tests/test_example.py", "scripts/pre_commit_hooks/exceptions.toml"),
    )
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[]) == 1, "omitted staged top-level tests must still be rejected"


def test_main_rejects_staged_docs_site_symlink_when_filenames_are_empty(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A staged generated-site symlink is checked even when no hook filenames are supplied."""
    initialize_git_repository(repository_root=tmp_path)
    target_path = tmp_path / "source.html"
    target_path.write_text(data="source\n", encoding="utf-8")
    link_path = tmp_path / "docs" / "site" / "link"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target_path)
    stage_paths(repository_root=tmp_path, paths=("docs/site/link",))
    monkeypatch.chdir(path=tmp_path)

    assert main(arguments=[]) == 1, "staged generated-site symlinks must be rejected without hook filenames"
