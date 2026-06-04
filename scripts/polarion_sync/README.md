# Polarion Sync

**Automated Polarion test case creation and marker injection for merged PRs**

Runs as a post-merge Jenkins job to detect new tests without Polarion markers, create matching Polarion test cases, and inject `@pytest.mark.polarion("CNV-XXXXX")` decorators back into the source code.

## Overview

The Polarion Sync pipeline ensures every merged test is tracked in Polarion by:

- **Scanning** merged commits for test functions missing `@pytest.mark.polarion` markers
- **Creating** Polarion TestCase work items via pylero, with requirement linking through Jira
- **Injecting** markers into source files and pushing changes back to main (or opening a follow-up PR)

This eliminates manual Polarion bookkeeping — developers merge tests and the pipeline handles the rest.

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│    SCAN      │───▶│    CREATE    │───▶│  INJECT + PUSH   │
│  scanner.py  │    │polarion_     │    │  injector.py     │
│              │    │  client.py   │    │  push_gate.py    │
└──────────────┘    └──────────────┘    └──────────────────┘
       │                   │                     │
   AST parse          pylero API            Insert markers
   Find tests         Create work items     Validate diff
   without markers    Link requirements     Push or open PR
```

### Modules

| Module | Responsibility |
|--------|---------------|
| `scanner.py` | AST-based detection of test functions missing `@pytest.mark.polarion`; supports changed-files-only and full scan modes; detects parametrized tests with nested polarion marks; collects sibling polarion IDs for requirement fallback |
| `polarion_client.py` | Creates Polarion TestCase work items via pylero; resolves requirements via Jira linker; uses sibling fallback for requirement linking; enforces all-or-nothing creation |
| `jira_linker.py` | Resolves Jira IDs → parent Epic (traverses parent chain and issuelinks up to 3 levels) → Polarion requirement via `jiraurl` query; caches results |
| `injector.py` | Inserts `@pytest.mark.polarion("CNV-XXXXX")` decorator before `def` lines; auto-adds `import pytest` if missing (respects module docstrings); idempotent |
| `push_gate.py` | Validates diff (only polarion markers and import lines allowed); runs pre-commit; pushes to main or creates a follow-up PR assigned to the original PR author |
| `main.py` | CLI entry point; orchestrates the three stages |

## How It Works

1. **Scan** — Parse test files with Python's `ast` module to find functions/methods that have no `@pytest.mark.polarion()` decorator. By default, only files changed in the last merge commit are scanned; `--scan-all` scans the entire test suite.

2. **Create** — For each unlinked test, create a Polarion TestCase work item. The pipeline attempts to link each test case to a Polarion requirement by resolving Jira references found in test docstrings (see [Requirement Resolution Chain](#requirement-resolution-chain) below).

3. **Inject + Push** — Insert the new marker decorators into the source files, validate that the diff contains only expected changes, run pre-commit checks, and push to main. If anything goes wrong, a follow-up PR is created instead.

## Decision Logic

### Push directly to main when:
- All new test cases were successfully linked to Polarion requirements
- The diff contains **only** polarion marker additions and `import pytest` lines
- Pre-commit passes cleanly

### Create a follow-up PR when:
- Some test cases could **not** be linked to requirements (Jira ID not found, Epic missing, or requirement not in Polarion)
- Push to main fails (e.g., rebase conflict with a parallel job)
- The follow-up PR is assigned to the original PR author for manual requirement linking

### All-or-nothing rule:
- If **any** test case fails to create in Polarion, **none** are injected into source
- This prevents partial marker injection that would leave some tests untracked

## Requirement Resolution Chain

```
Test docstring contains Jira URL (e.g., CNV-12345)
    ↓
Jira API: resolve issue → find parent Epic (up to 3 levels via parent + issuelinks)
    ↓
Polarion query: jiraurl:"https://redhat.atlassian.net/browse/CNV-XXXXX"
    ↓
Found requirement → link to test case
    ↓
Not found → fallback: check sibling tests in same file for existing requirement links
    ↓
Still not found → requirement_linked=False → follow-up PR
```

## Configuration

### Polarion (pylero)

Requires a `~/.pylero` config file with credentials:

```ini
[webservice]
url=https://polarion.engineering.redhat.com/polarion
user=automation_report
password=<token>
svn_repo=
default_project=CNV
```

> **Note:** Without `~/.pylero`, pylero crashes on import with `PyleroLibException`. This is why the package uses lazy (deferred) imports for pylero and jira modules.

SSL verification can be disabled via the `POLARION_DISABLE_SSL_VERIFY=1` environment variable (affects all HTTPS calls in the process).

### Jira

- `JIRA_TOKEN` — API token (required for requirement resolution)
- `JIRA_SERVER` — Server URL (default: `https://redhat.atlassian.net`)

### Git / GitHub

- Write access to the repository (push to main or create PRs)
- `gh` CLI authenticated for PR creation
- `GITHUB_TOKEN` for PR operations

### Environment Variables Summary

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_TOKEN` | Yes (for Jira) | Jira API token |
| `JIRA_SERVER` | No | Jira server URL (default: `https://redhat.atlassian.net`) |
| `GITHUB_TOKEN` | Yes (for PRs) | GitHub token for PR creation |
| `POLARION_DISABLE_SSL_VERIFY` | No | Set to `1` to disable SSL verification |

> **Jenkins note:** The `~/.pylero` config file and environment variables are provisioned automatically by the Jenkins job configuration.

## Usage Examples

### Dry-run (no Polarion access, no push)

Simulates the full pipeline without side effects — useful for local testing:

```bash
uv run python -m scripts.polarion_sync.main --dry-run
```

### Scan only (show unlinked tests)

Find tests missing polarion markers without creating anything:

```bash
uv run python -m scripts.polarion_sync.main --scan-only
```

### Scan all tests (not just changed files)

```bash
uv run python -m scripts.polarion_sync.main --scan-all --scan-only
```

### Full run (requires Polarion + Jira access)

```bash
uv run python -m scripts.polarion_sync.main
```

### Jenkins CI run with PR metadata

Enables follow-up PR creation assigned to the original PR author:

```bash
uv run python -m scripts.polarion_sync.main \
  --pr-author rnetser --pr-number 5014
```

### Jenkins CI dry-run

```bash
uv run python -m scripts.polarion_sync.main \
  --pr-author rnetser --pr-number 5014 --dry-run
```

## CLI Arguments

| Argument | Description |
|----------|-------------|
| `--dry-run` | Simulate Polarion creation and skip push |
| `--scan-only` | Only scan for unlinked tests; don't create or inject |
| `--scan-all` | Scan all test files, not just recently changed |
| `--project-id` | Polarion project ID (default: `CNV`) |
| `--repo-root` | Repository root path (default: current directory) |
| `--pr-author` | GitHub username of PR author (for follow-up PRs) |
| `--pr-number` | Original PR number (for follow-up PRs) |

## Running Tests

```bash
uv run pytest scripts/polarion_sync/tests/ -v
```

25 unit tests covering scanner, injector, client, and push gate logic.

## Implementation Notes

- **Lazy imports** — `pylero` and `jira` are imported at call time, not module level, because pylero crashes on import without `~/.pylero`. The `# noqa: PLC0415` suppression on these lines is approved by the maintainer.
- **Broad exception handling** — `except Exception` is used on pylero/jira API calls because these are unversioned external libraries with undocumented exception types (see [Acceptable Defensive Checks](../../AGENTS.md#acceptable-defensive-checks-exceptions-only)).
- **Idempotent injection** — The injector skips files that already have the marker, so re-running the pipeline is safe.
- **Bottom-up insertion** — Markers are inserted from the bottom of each file upward to avoid line-number offset drift.

## Related Documentation

- [Polarion Sync Skill](../../.pi/skills/polarion-sync/SKILL.md) — Agent skill for post-merge Polarion workflows
- [pylero documentation](https://github.com/RedHatQE/pylero)
- [Jira Python library](https://jira.readthedocs.io/)
