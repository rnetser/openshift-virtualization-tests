"""Safety gate: verify diff is only Polarion marker additions, then push.

This module ensures that the only changes in the working tree are
``@pytest.mark.polarion()`` decorator insertions on test functions.
If any unexpected change is detected the push is aborted.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

POLARION_LINE_PATTERN = re.compile(r"^\+\s*@pytest\.mark\.polarion\(")
ALLOWED_DIFF_PATTERNS = (
    # Added Polarion marker decorator
    POLARION_LINE_PATTERN,
    # Empty added line (formatting)
    re.compile(r"^\+\s*$"),
    # Diff metadata lines
    re.compile(r"^(\+\+\+|---|\@\@|diff )"),
    # Import lines (pytest import may be added)
    re.compile(r"^\+\s*import\s"),
    re.compile(r"^\+\s*from\s"),
)


def _run_precommit(repo_root: Path) -> bool:
    """Run pre-commit and return True if it passes."""
    LOGGER.info("Running pre-commit...")
    result = subprocess.run(
        ["uv", "run", "pre-commit", "run", "--all-files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        LOGGER.error(f"Pre-commit failed:\n{result.stdout}\n{result.stderr}")
        return False
    LOGGER.info("Pre-commit passed")
    return True


def _get_diff(repo_root: Path) -> str:
    """Return the staged + unstaged diff."""
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return result.stdout


def _validate_diff(diff: str) -> tuple[bool, list[str]]:
    """Check that every added/removed line is a Polarion marker or whitespace.

    Returns:
        Tuple of (is_safe, list_of_violations).
    """
    violations: list[str] = []

    for line_num, line in enumerate(diff.splitlines(), start=1):
        # Skip context lines (no + or - prefix)
        if not line.startswith(("+", "-")):
            continue

        # Skip diff metadata
        if line.startswith(("+++", "---", "@@", "diff ")):
            continue

        # Added lines must be Polarion markers, imports, or blank
        if line.startswith("+"):
            if not any(pattern.match(line) for pattern in ALLOWED_DIFF_PATTERNS):
                violations.append(f"  line {line_num}: {line}")

        # Removed lines are NOT allowed — Polarion sync should only add
        if line.startswith("-"):
            violations.append(f"  line {line_num} (removal): {line}")

    return len(violations) == 0, violations


def _changed_files(repo_root: Path) -> list[str]:
    """Return list of files changed relative to HEAD."""
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return result.stdout.strip().splitlines()


def _validate_changed_files(changed_files: list[str]) -> tuple[bool, list[str]]:
    """Ensure only test files were modified."""
    violations: list[str] = []
    for file in changed_files:
        if not file.startswith("tests/") or not file.endswith(".py"):
            violations.append(f"  non-test file modified: {file}")
    return len(violations) == 0, violations


def validate_and_push(
    repo_root: Path,
    bot_name: str = "Polarion Sync Bot",
    bot_email: str = "cnvqe-polarion-bot@redhat.com",
    dry_run: bool = False,
) -> bool:
    """Run pre-commit, validate the diff, and push to main.

    Args:
        repo_root: path to the repository root.
        bot_name: git author/committer name for the push commit.
        bot_email: git author/committer email.
        dry_run: when True, validate but do not commit or push.

    Returns:
        True if push succeeded (or dry_run validated), False otherwise.
    """
    # 1. Run pre-commit
    if not _run_precommit(repo_root=repo_root):
        LOGGER.error("ABORT: pre-commit failed — Polarion ID injection broke formatting")
        return False

    # 2. Check which files changed
    changed_files = _changed_files(repo_root=repo_root)
    if not changed_files:
        LOGGER.info("No files changed — nothing to push")
        return True

    files_ok, file_violations = _validate_changed_files(changed_files=changed_files)
    if not files_ok:
        LOGGER.error("ABORT: unexpected files modified:\n" + "\n".join(file_violations))
        return False

    # 3. Validate the diff content
    diff = _get_diff(repo_root=repo_root)
    diff_ok, diff_violations = _validate_diff(diff=diff)
    if not diff_ok:
        LOGGER.error("ABORT: diff contains non-Polarion changes:\n" + "\n".join(diff_violations))
        return False

    LOGGER.info(f"Safety gate passed: {len(changed_files)} file(s), all changes are Polarion markers only")

    if dry_run:
        LOGGER.info("[dry-run] Would commit and push — skipping")
        return True

    # 4. Stage, commit, push
    subprocess.run(["git", "add"] + changed_files, cwd=repo_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            f"user.name={bot_name}",
            "-c",
            f"user.email={bot_email}",
            "commit",
            "--signoff",
            "-m",
            "chore(polarion): add test case IDs\n\nAuto-generated Polarion test cases for new STDs.",
        ],
        cwd=repo_root,
        check=True,
    )

    # Rebase on latest main before pushing (parallel job safety)
    rebase_result = subprocess.run(
        ["git", "pull", "--rebase", "origin", "main"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if rebase_result.returncode != 0:
        LOGGER.error(f"Rebase failed (conflict with parallel job?):\n{rebase_result.stderr}")
        subprocess.run(["git", "rebase", "--abort"], cwd=repo_root)
        subprocess.run(["git", "reset", "HEAD~1"], cwd=repo_root)
        return False

    result = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        LOGGER.error(f"Push failed:\n{result.stderr}")
        subprocess.run(["git", "reset", "HEAD~1"], cwd=repo_root)
        return False

    LOGGER.info("Successfully pushed Polarion IDs to main")
    return True


def create_followup_pr(
    repo_root: Path,
    pr_author: str,
    pr_number: int,
    unlinked_tests: list[str],
    bot_name: str = "Polarion Sync Bot",
    bot_email: str = "cnvqe-polarion-bot@redhat.com",
    dry_run: bool = False,
) -> bool:
    """Create a follow-up PR when requirement linking fails.

    Creates a branch with the Polarion marker changes and opens a PR
    assigned to the original PR author, asking them to manually link
    test cases to Polarion requirements.

    Args:
        repo_root: path to the repository root.
        pr_author: GitHub username of the original PR author.
        pr_number: original PR number that triggered the sync.
        unlinked_tests: descriptions of tests missing requirement links.
        bot_name: git author/committer name.
        bot_email: git author/committer email.
        dry_run: when True, log what would happen without executing.

    Returns:
        True if PR was created successfully (or dry_run), False otherwise.
    """
    if not _run_precommit(repo_root=repo_root):
        LOGGER.error("ABORT: pre-commit failed")
        return False

    changed_files = _changed_files(repo_root=repo_root)
    if not changed_files:
        LOGGER.info("No files changed \u2014 nothing to do")
        return True

    files_ok, file_violations = _validate_changed_files(changed_files=changed_files)
    if not files_ok:
        LOGGER.error("ABORT: unexpected files modified:\n" + "\n".join(file_violations))
        return False

    diff = _get_diff(repo_root=repo_root)
    diff_ok, diff_violations = _validate_diff(diff=diff)
    if not diff_ok:
        LOGGER.error("ABORT: diff contains non-Polarion changes:\n" + "\n".join(diff_violations))
        return False

    branch_name = f"polarion-sync/pr-{pr_number}"
    unlinked_list = "\n".join(f"- {test}" for test in unlinked_tests)
    commit_message = (
        f"chore(polarion): add test case IDs from PR #{pr_number}\n\n"
        f"Auto-generated Polarion test cases.\n"
        f"The following test(s) need manual requirement association in Polarion:\n\n"
        f"{unlinked_list}\n\n"
        f"Please link each test case to its Polarion requirement, then merge this PR."
    )
    pr_body = (
        f"## Polarion Sync Follow-up for PR #{pr_number}\n\n"
        f"Polarion test cases were created but could not be automatically linked "
        f"to requirements.\n\n"
        f"### Tests needing manual requirement linking:\n\n"
        f"{unlinked_list}\n\n"
        f"### What to do:\n\n"
        f"1. Open each test case in Polarion\n"
        f"2. Add a **verifies** link to the appropriate requirement\n"
        f"3. Merge this PR\n"
    )

    if dry_run:
        LOGGER.info(f"[dry-run] Would create branch: {branch_name}")
        LOGGER.info(f"[dry-run] Would commit {len(changed_files)} file(s)")
        LOGGER.info(f"[dry-run] Would create PR assigned to {pr_author}")
        LOGGER.info(f"[dry-run] Unlinked tests:\n{unlinked_list}")
        return True

    subprocess.run(
        ["git", "checkout", "-B", branch_name],
        cwd=repo_root,
        check=True,
    )

    subprocess.run(["git", "add"] + changed_files, cwd=repo_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            f"user.name={bot_name}",
            "-c",
            f"user.email={bot_email}",
            "commit",
            "--signoff",
            "-m",
            commit_message,
        ],
        cwd=repo_root,
        check=True,
    )

    result = subprocess.run(
        ["git", "push", "--force", "origin", branch_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        LOGGER.error(f"Push failed:\n{result.stderr}")
        return False

    # Check if PR already exists for this branch (retry scenario)
    existing_pr = subprocess.run(
        ["gh", "pr", "list", "--head", branch_name, "--json", "url", "--jq", ".[0].url"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if existing_pr.returncode == 0 and existing_pr.stdout.strip():
        LOGGER.info(f"PR already exists (branch force-pushed): {existing_pr.stdout.strip()}")
        return True

    result = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            f"chore(polarion): add test case IDs from PR #{pr_number}",
            "--body",
            pr_body,
            "--assignee",
            pr_author,
            "--reviewer",
            pr_author,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        LOGGER.error(f"PR creation failed:\n{result.stderr}")
        return False

    LOGGER.info(f"Follow-up PR created: {result.stdout.strip()}")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    repo = Path.cwd()
    success = validate_and_push(repo_root=repo, dry_run="--dry-run" in sys.argv)
    sys.exit(0 if success else 1)
