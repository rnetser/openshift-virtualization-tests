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
from pathlib import Path

import click
from simple_logger.logger import get_logger

from scripts.rp_coverage_gate.report import (
    analyze_coverage,
    format_json_report,
    format_text_report,
)
from scripts.rp_coverage_gate.rp_checker import check_coverage
from scripts.rp_coverage_gate.test_collector import collect_all_tests
from scripts.rp_utils.rp_client import RPClient

LOGGER = get_logger(name=__name__)

RP_DEFAULT_URL = "https://reportportal-cnv.apps.dno.ocp-hub.prod.psi.redhat.com"
RP_DEFAULT_PROJECT = "cnv"


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
@click.option("--rp-url", type=str, default=RP_DEFAULT_URL, help="ReportPortal URL")
@click.option("--rp-project", type=str, default=RP_DEFAULT_PROJECT, help="RP project name")
@click.option("--rp-token", type=str, envvar="REPORT_PORTAL_TOKEN", default=None, help="RP API token")
@click.option(
    "--output-format",
    type=click.Choice(choices=["text", "json"]),
    default="text",
    help="Output format",
)
@click.option("--team", type=str, default=None, help="Filter report to specific team")
@click.option("--fail-on-stale/--no-fail-on-stale", default=True, help="Whether stale tests fail the gate")
@click.option("--full", is_flag=True, default=False, help="Show per-test details including bundle")
@click.option("--dry-run", is_flag=True, default=False, help="Collect tests only, skip RP query")
def main(
    bundle: str,
    stale_days: int,
    tests_dir: Path,
    rp_url: str,
    rp_project: str,
    rp_token: str | None,
    output_format: str,
    team: str | None,
    fail_on_stale: bool,
    full: bool,
    dry_run: bool,
) -> None:
    """Run the coverage gate check."""
    automated_ids, unautomated_ids = collect_all_tests(tests_dir=tests_dir)
    LOGGER.info(f"Collected {len(automated_ids)} automated and {len(unautomated_ids)} unautomated test IDs")

    if dry_run:
        total_count = len(automated_ids) + len(unautomated_ids)
        click.echo(message="Test inventory (dry-run):")
        click.echo(message=f"  Total:        {total_count}")
        click.echo(message=f"  Automated:    {len(automated_ids)}")
        click.echo(message=f"  Unautomated:  {len(unautomated_ids)}")
        if team:
            filtered_automated = {test_id for test_id in automated_ids if team.lower() in test_id.lower()}
            filtered_unautomated = {test_id for test_id in unautomated_ids if team.lower() in test_id.lower()}
            filtered_count = len(filtered_automated) + len(filtered_unautomated)
            click.echo(message=f"  Filtered ({team}): {filtered_count}")
        sys.exit(0)

    if not rp_token:
        click.echo(message="Error: REPORT_PORTAL_TOKEN env var or --rp-token required", err=True)
        sys.exit(2)

    try:
        rp_client = RPClient(base_url=rp_url, project=rp_project, token=rp_token)
        rp_results = check_coverage(rp_client=rp_client, bundle_prefix=bundle)
        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=unautomated_ids,
            rp_results=rp_results,
            stale_days=stale_days,
            team_filter=team,
            fail_on_stale=fail_on_stale,
        )

        if output_format == "json":
            click.echo(message=format_json_report(report=report, bundle_prefix=bundle, stale_days=stale_days))
        else:
            click.echo(
                message=format_text_report(
                    report=report,
                    bundle_prefix=bundle,
                    stale_days=stale_days,
                    full=full,
                )
            )

        sys.exit(0 if report.gate_passed else 1)

    except Exception:
        LOGGER.exception("Coverage gate failed with an error")
        sys.exit(2)


if __name__ == "__main__":
    main()
