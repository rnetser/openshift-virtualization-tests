<!-- Co-authored-by: Claude <noreply@anthropic.com> -->
# CI Coverage Gate for ReportPortal

Analyzes test coverage against ReportPortal data. Collects all tests from the repo,
cross-references with RP results across all matching launches, and generates a report
showing coverage gaps, stale tests, quarantined tests, and parametrized test matrices.

---

## Table of Contents

- [Authentication](#authentication)
- [Output Formats](#output-formats)
- [Report Sections](#report-sections)
- [Matrix View](#matrix-view)
- [Parametrized Test Handling](#parametrized-test-handling)
- [Quarantine Detection](#quarantine-detection)
- [Usage Examples](#usage-examples)
- [CLI Reference](#cli-reference)
- [Exit Codes](#exit-codes)
- [Running Tests](#running-tests)

---

## Authentication

The gate authenticates with ReportPortal using an API token.

```bash
export REPORT_PORTAL_URL="https://your-reportportal-instance.example.com"
export REPORT_PORTAL_PROJECT="your-project"
export REPORT_PORTAL_TOKEN="your-api-key-here"
```

These can also be passed via CLI flags `--rp-url`, `--rp-project`, and `--rp-token`.

---

## Output Formats

| Format | Flag | Description |
|--------|------|-------------|
| **text** | `--output-format text` (default) | Terminal output with ANSI-friendly layout |
| **json** | `--output-format json` | Machine-readable JSON with summary, sections, and per-team breakdowns |
| **html** | `--output-format html` | Self-contained HTML report written to `coverage_report_<bundle>.html` |

### HTML Report Features

- **Tabbed layout** — Summary tab with overall stats + one tab per team
- **Per-team stats** — Breakdown table showing pass/fail/never-executed/stale per team
- **Matrix view** — 2D grid for tests with 2-axis parameters (e.g., OS × StorageClass)
- **Annotated list** — Single-axis parametrized tests with status badges per variant
- **Collapsible sections** — Each section has a description and can be expanded/collapsed
- **Color-coded cells** — Status symbols with defect classification in matrix cells
- **Collapsible legend** — Explains all symbols and defect type abbreviations
- **Collapse on tab switch** — All sections close when switching between team tabs

---

## Report Sections

Each team tab contains these sections (ordered by severity):

| Section | Description |
|---------|-------------|
| **⚠ GATING** | Tests marked with `-m gating` that have no results or are stale |
| **FAILED TESTS** | Tests whose most recent result across all launches is FAILED, grouped by defect type |
| **⏸ QUARANTINED** | Tests intentionally skipped due to known bugs (AST-detected `xfail`/`jira run=False`) |
| **MANUAL TESTS** | Unimplemented test designs (`__test__ = False`) with no results in RP |
| **NEVER EXECUTED** | Implemented tests with no results in RP for this bundle |
| **STALE TESTS** | Tests whose last execution is older than the `--stale-days` threshold |
| **PASSED TESTS** | Tests whose most recent result across all launches is PASSED |
| **SKIPPED TESTS** | Tests whose most recent result across all launches is SKIPPED |

Sections only appear when they contain tests. GATING and FAILED are open by default.

---

## Matrix View

Tests with 2-axis parameters (format: `[#val1#-#val2#]`) render as a 2D grid showing
all combinations at a glance.

### Status symbols

| Symbol | CSS Class | Meaning |
|--------|-----------|---------|
| ✅ | `status-passed` | Passed |
| ❌ | `status-failed` | Failed (no defect classification) |
| — | `status-never` | Never Executed |
| ⚠️ | `status-stale` | Stale |
| SKIP | — | Skipped |
| Q | `status-quarantined` | Quarantined |

### Defect abbreviations in matrix cells

When a failed test has a defect classification in ReportPortal, the matrix cell
shows the abbreviation instead of ❌, with a tooltip showing the full type and comment:

| Code | Meaning |
|------|---------|
| **PB** | Product Bug — confirmed defect in the product |
| **AB** | Automation Bug — test code issue |
| **SI** | System Issue — environment or infrastructure problem |
| **TI** | To Investigate — failure not yet analyzed |
| **NI** | No Issue — false alarm or expected behavior |

---

## Parametrized Test Handling

Tests with multiple variants are grouped by base test name:

- **2-axis params** (`[#val1#-#val2#]`) → matrix grid with row/column headers
- **Single-axis params** (`[param]`) → annotated list with status badges per variant
- **Mixed statuses** → grouped test appears in **one section only**, determined by worst
  variant status: GATING > FAILED > STALE > NEVER_EXECUTED > SKIPPED > PASSED

The matrix/annotated list always shows **all** variants with their individual status,
regardless of which section it appears in. This gives the complete picture in one place
instead of splitting variants across multiple sections.

---

## Quarantine Detection

The gate uses AST analysis to detect quarantined tests directly from source code
(no pytest collection required):

- **xfail quarantine:** `@pytest.mark.xfail(reason=f"{QUARANTINED}: ...", run=False)`
- **Jira quarantine:** `@pytest.mark.jira("CNV-XXXXX", run=False)`

Quarantined tests are:

- Excluded from coverage percentage calculation
- Shown in a dedicated QUARANTINED section with Jira links
- Not counted as "never executed"

Class-level quarantine markers expand to all `test_*` methods in the class.

---

## Usage Examples

### Basic text report

```bash
uv run python -m scripts.rp_coverage_gate.rp_coverage_gate --bundle v4.22.0
```

### HTML report with exclusions

```bash
uv run python -m scripts.rp_coverage_gate.rp_coverage_gate \
  --bundle v4.22.0 \
  --output-format html \
  --exclude-team chaos \
  --exclude-team deprecated_api \
  --exclude-team after_cluster_deploy_sanity \
  --exclude-team scale \
  --full
```

### Specific team with custom stale threshold

```bash
uv run python -m scripts.rp_coverage_gate.rp_coverage_gate \
  --bundle v4.22.0 \
  --team network \
  --stale-days 60
```

### Dry run (no RP connection)

Preview test inventory without querying ReportPortal:

```bash
uv run python -m scripts.rp_coverage_gate.rp_coverage_gate \
  --bundle v4.22.0 --dry-run
```

### Limit launches for faster iteration

```bash
uv run python -m scripts.rp_coverage_gate.rp_coverage_gate \
  --bundle v4.22.0 --max-launches 200
```

### JSON output for CI integration

```bash
uv run python -m scripts.rp_coverage_gate.rp_coverage_gate \
  --bundle v4.22.0 --output-format json > coverage.json
```

---

## CLI Reference

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--bundle TEXT` | Yes | — | Bundle version prefix (e.g., `v4.22.0`). Used to filter RP launches by BUNDLE attribute. |
| `--stale-days INT` | No | `30` | Flag tests whose last execution is older than N days as stale. |
| `--tests-dir PATH` | No | `tests` | Directory to scan for test files. |
| `--rp-url TEXT` | No | env `REPORT_PORTAL_URL` | ReportPortal base URL. |
| `--rp-project TEXT` | No | env `REPORT_PORTAL_PROJECT` | ReportPortal project name. |
| `--rp-token TEXT` | No | env `REPORT_PORTAL_TOKEN` | ReportPortal API token. |
| `--output-format` | No | `text` | Output format: `text`, `json`, or `html`. HTML writes a file to the current directory. |
| `--team TEXT` | No | — | Filter report to a specific team (first directory segment after `tests/`). |
| `--exclude-team TEXT` | No | — | Exclude team(s) from the report. Repeatable (e.g., `--exclude-team chaos --exclude-team scale`). |
| `--max-launches INT` | No | `0` (all) | Maximum number of recent launches to query. `0` means process all matching launches. |
| `--full` | No | `false` | Show all sections including PASSED, SKIPPED, STALE, NEVER EXECUTED (default shows only summary + GATING + FAILED + MANUAL). |
| `--fail-on-stale / --no-fail-on-stale` | No | `--fail-on-stale` | Whether stale tests cause a non-zero exit code. |
| `--dry-run` | No | `false` | Collect tests only, skip RP query. Useful for verifying test discovery. |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All tests covered (no never-executed, no stale if `--fail-on-stale`) |
| `1` | Coverage gaps found (never-executed or stale tests exist) |
| `2` | Error (invalid arguments, RP connection failure, etc.) |

---

## Running Tests

```bash
uv run tox -e rp-coverage-gate-tests
```
