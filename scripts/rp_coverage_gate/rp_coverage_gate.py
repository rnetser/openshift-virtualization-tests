# Co-authored-by: Claude <noreply@anthropic.com>
"""CI Coverage Gate for ReportPortal.

Collects all tests from the repository, checks ReportPortal for execution
results on a target bundle, and produces a coverage report. Flags tests
that were never executed or are stale (older than a configurable threshold).

Exit codes:
    0 — all tests have recent RP results (gate passes)
    1 — coverage gaps found (never-executed or stale tests)
    2 — error (e.g., RP connection failure)
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from simple_logger.logger import get_logger

from scripts.rp_coverage_gate.report import (
    analyze_coverage,
    format_html_report,
    format_json_report,
    format_text_report,
)
from scripts.rp_coverage_gate.rp_checker import check_coverage
from scripts.rp_coverage_gate.test_collector import collect_all_tests, scan_quarantined_tests
from scripts.rp_utils.rp_client import RPClient

LOGGER = get_logger(name=__name__)


@click.command(
    help="CI Coverage Gate for ReportPortal",
    epilog="""
Checks test coverage against ReportPortal for a target bundle.
Collects all tests from the repo, queries RP for results, and produces
a coverage report showing executed, never-executed, and stale tests.

Exit codes: 0 = pass, 1 = gaps found, 2 = error

\b
Examples:
    uv run python -m scripts.rp_coverage_gate.rp_coverage_gate --bundle v4.22.0
    uv run python -m scripts.rp_coverage_gate.rp_coverage_gate --bundle v4.22.0 --team network
    uv run python -m scripts.rp_coverage_gate.rp_coverage_gate --bundle v4.22.0 --output-format json
    uv run python -m scripts.rp_coverage_gate.rp_coverage_gate --bundle v4.22.0 --full
    """,
)
@click.option("--bundle", type=str, required=True, help="Bundle version prefix (e.g., v4.22.0)")
@click.option("--stale-days", type=int, default=30, help="Flag tests older than N days (default: 30)")
@click.option(
    "--tests-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path("tests"),
    help="Tests directory",
)
@click.option(
    "--rp-url", type=str, envvar="REPORT_PORTAL_URL", default=None, help="ReportPortal URL (env: REPORT_PORTAL_URL)"
)
@click.option(
    "--rp-project",
    type=str,
    envvar="REPORT_PORTAL_PROJECT",
    default=None,
    help="RP project name (env: REPORT_PORTAL_PROJECT)",
)
@click.option("--rp-token", type=str, envvar="REPORT_PORTAL_TOKEN", default=None, help="RP API token")
@click.option(
    "--output-format",
    type=click.Choice(choices=["text", "json", "html"]),
    default="text",
    help="Output format (html writes to file)",
)
@click.option("--team", type=str, default=None, help="Filter report to specific team")
@click.option(
    "--exclude-team",
    type=str,
    multiple=True,
    help="Exclude team(s) from report (repeatable, e.g., --exclude-team chaos --exclude-team deprecated_api)",
)
@click.option("--max-launches", type=int, default=0, help="Max recent launches to query (0 = all, default: all)")
@click.option("--fail-on-stale/--no-fail-on-stale", default=True, help="Whether stale tests fail the gate")
@click.option("--full", is_flag=True, default=False, help="Show per-test details including bundle")
@click.option("--dry-run", is_flag=True, default=False, help="Collect tests only, skip RP query")
def main(
    bundle: str,
    stale_days: int,
    tests_dir: Path,
    rp_url: str | None,
    rp_project: str | None,
    rp_token: str | None,
    output_format: str,
    team: str | None,
    exclude_team: tuple[str, ...],
    max_launches: int,
    fail_on_stale: bool,
    full: bool,
    dry_run: bool,
) -> None:
    """Run the coverage gate check."""
    automated_ids, unautomated_ids, gating_ids = collect_all_tests(tests_dir=tests_dir)
    quarantined = scan_quarantined_tests(tests_dir=tests_dir)
    LOGGER.info(
        f"Collected {len(automated_ids)} automated, {len(unautomated_ids)} unautomated, {len(quarantined)} quarantined test IDs"
    )

    if dry_run:
        total_count = len(automated_ids) + len(unautomated_ids)
        click.echo(message="Test inventory (dry-run):")
        click.echo(message=f"  Total:        {total_count}")
        click.echo(message=f"  Automated:    {len(automated_ids)}")
        click.echo(message=f"  Unautomated:  {len(unautomated_ids)}")
        click.echo(message=f"  Gating:       {len(gating_ids)}")
        click.echo(message=f"  Quarantined:  {len(quarantined)}")
        if team:
            filtered_automated = {test_id for test_id in automated_ids if team.lower() in test_id.lower()}
            filtered_unautomated = {test_id for test_id in unautomated_ids if team.lower() in test_id.lower()}
            filtered_count = len(filtered_automated) + len(filtered_unautomated)
            click.echo(message=f"  Filtered ({team}): {filtered_count}")
        sys.exit(0)

    if not rp_url:
        click.echo(message="Error: REPORT_PORTAL_URL env var or --rp-url required", err=True)
        sys.exit(2)
    if not rp_project:
        click.echo(message="Error: REPORT_PORTAL_PROJECT env var or --rp-project required", err=True)
        sys.exit(2)
    if not rp_token:
        click.echo(message="Error: REPORT_PORTAL_TOKEN env var or --rp-token required", err=True)
        sys.exit(2)

    try:
        rp_client = RPClient(base_url=rp_url, project=rp_project, token=rp_token)

        def _progress(current: int, total: int) -> None:
            click.echo(message=f"\rFetching items from launch {current}/{total}...", nl=False)
            if current == total:
                click.echo(message="")

        rp_results = check_coverage(
            rp_client=rp_client,
            bundle_prefix=bundle,
            max_launches=max_launches,
            progress_callback=_progress,
        )
        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=unautomated_ids,
            rp_results=rp_results,
            stale_days=stale_days,
            team_filter=team,
            fail_on_stale=fail_on_stale,
            gating_ids=gating_ids,
            exclude_teams=exclude_team if exclude_team else None,
            quarantined=quarantined,
        )

        report_filters: dict[str, Any] = {
            "bundle": bundle,
            "team": team,
            "exclude_teams": list(exclude_team),
            "max_launches": max_launches,
            "stale_days": stale_days,
            "tests_dir": str(tests_dir),
        }

        if output_format == "json":
            click.echo(
                message=format_json_report(
                    report=report, bundle_prefix=bundle, stale_days=stale_days, filters=report_filters
                )
            )
        elif output_format == "html":
            html_content = format_html_report(
                report=report, bundle_prefix=bundle, stale_days=stale_days, filters=report_filters
            )
            timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
            safe_bundle = bundle.replace("/", "_")
            output_path = Path.cwd() / f"coverage_report_{safe_bundle}_{timestamp}.html"
            output_path.write_text(data=html_content, encoding="utf-8")
            click.echo(message=f"HTML report written to: {output_path}")
        else:
            click.echo(
                message=format_text_report(
                    report=report,
                    bundle_prefix=bundle,
                    stale_days=stale_days,
                    full=full,
                    filters=report_filters,
                )
            )

        sys.exit(0 if report.gate_passed else 1)

    except Exception:
        LOGGER.exception("Coverage gate failed with an error")
        sys.exit(2)


if __name__ == "__main__":
    main()
