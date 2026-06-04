"""Polarion Sync — main entry point.

Orchestrates the three stages:
  1. **Detect** — scan merged commit for new tests without Polarion IDs
  2. **Create** — create Polarion test cases via pylero
  3. **Inject + Push** — inject markers into test files, validate, push

Usage::

    # Full run (requires Polarion access):
    uv run python -m scripts.polarion_sync.main

    # Dry-run (no Polarion, no push):
    uv run python -m scripts.polarion_sync.main --dry-run

    # Scan only (just show what's missing):
    uv run python -m scripts.polarion_sync.main --scan-only

    # Scan all tests (not just changed):
    uv run python -m scripts.polarion_sync.main --scan-all --scan-only

    # Jenkins CI run:
    uv run python -m scripts.polarion_sync.main --pr-author rnetser --pr-number 5014

    # Jenkins CI dry-run:
    uv run python -m scripts.polarion_sync.main --pr-author rnetser --pr-number 5014 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scripts.polarion_sync.injector import inject_polarion_ids
from scripts.polarion_sync.polarion_client import create_test_cases
from scripts.polarion_sync.push_gate import create_followup_pr, validate_and_push
from scripts.polarion_sync.scanner import scan_all, scan_changed

LOGGER = logging.getLogger(__name__)


def main() -> int:
    """Orchestrate Polarion sync: scan for unlinked tests, create test cases, inject markers, push.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description="Polarion Sync — auto-create test cases on merge")
    parser.add_argument("--dry-run", action="store_true", help="Simulate Polarion creation and skip push")
    parser.add_argument("--scan-only", action="store_true", help="Only scan — do not create or inject")
    parser.add_argument("--scan-all", action="store_true", help="Scan all tests, not just changed files")
    parser.add_argument("--project-id", default="CNV", help="Polarion project ID (default: CNV)")
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="Repository root (default: current directory)"
    )
    parser.add_argument("--pr-author", help="GitHub username of the PR author (for follow-up PRs)")
    parser.add_argument("--pr-number", type=int, help="Original PR number that triggered the sync")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    repo_root = args.repo_root.resolve()

    # ── Stage 1: Detect ─────────────────────────────────────────────
    LOGGER.info("=" * 60)
    LOGGER.info("Stage 1: Scanning for tests without Polarion IDs")
    LOGGER.info("=" * 60)

    if args.scan_all:
        unlinked = scan_all(repo_root=repo_root)
    else:
        unlinked = scan_changed(repo_root=repo_root)

    if not unlinked:
        LOGGER.info("No unlinked tests found — nothing to do")
        return 0

    LOGGER.info(f"Found {len(unlinked)} test(s) without Polarion ID:")
    for test in unlinked:
        LOGGER.info(f"  {test.node_id}")

    if args.scan_only:
        return 0

    # ── Stage 2: Create in Polarion ─────────────────────────────────
    LOGGER.info("")
    LOGGER.info("=" * 60)
    LOGGER.info("Stage 2: Creating Polarion test cases")
    LOGGER.info("=" * 60)

    results = create_test_cases(
        tests=unlinked,
        project_id=args.project_id,
        dry_run=args.dry_run,
    )

    if not results:
        LOGGER.error("No Polarion test cases were created — aborting")
        return 1

    LOGGER.info(f"Created {len(results)} Polarion test case(s)")

    # ── Stage 3: Inject + Validate + Push ───────────────────────────
    LOGGER.info("")
    LOGGER.info("=" * 60)
    LOGGER.info("Stage 3: Injecting IDs and pushing")
    LOGGER.info("=" * 60)

    modified = inject_polarion_ids(results=results)
    LOGGER.info(f"Modified {len(modified)} file(s)")

    all_linked = all(result.requirement_linked for result in results)

    if all_linked:
        LOGGER.info("All test cases linked to requirements \u2014 pushing to main")
        success = validate_and_push(repo_root=repo_root, dry_run=args.dry_run)
        if not success:
            LOGGER.warning("Push to main failed \u2014 falling back to PR")
            if not args.pr_author or not args.pr_number:
                LOGGER.error("ABORT: --pr-author and --pr-number required for PR fallback")
                return 1
            success = create_followup_pr(
                repo_root=repo_root,
                pr_author=args.pr_author,
                pr_number=args.pr_number,
                unlinked_tests=["Push to main failed (rebase conflict with parallel job)"],
                dry_run=args.dry_run,
            )
            if not success:
                LOGGER.error("Follow-up PR creation also failed")
                return 1
    else:
        LOGGER.warning("Some test cases could NOT be linked to requirements")
        if not args.pr_author or not args.pr_number:
            LOGGER.error("ABORT: --pr-author and --pr-number are required when requirement linking fails")
            return 1

        unlinked_descriptions = [
            f"{result.test.node_id} (Polarion: {result.polarion_id})"
            for result in results
            if not result.requirement_linked
        ]
        for desc in unlinked_descriptions:
            LOGGER.warning(f"  Unlinked: {desc}")

        success = create_followup_pr(
            repo_root=repo_root,
            pr_author=args.pr_author,
            pr_number=args.pr_number,
            unlinked_tests=unlinked_descriptions,
            dry_run=args.dry_run,
        )
        if not success:
            LOGGER.error("Follow-up PR creation failed")
            return 1

    LOGGER.info("Done \u2705")
    return 0


if __name__ == "__main__":
    sys.exit(main())
