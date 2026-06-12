"""Manual Test Reporter for ReportPortal.

Interactive CLI that collects __test__ = False placeholder tests,
shows full test context (docstrings, markers, preconditions) one-by-one,
lets the tester mark each as pass/fail/skip, and pushes results to
ReportPortal as a new launch.

Supports batch mode via YAML file for non-interactive use and failure retry.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml
from simple_logger.logger import get_logger

from scripts.rp_manual_reporter.collector import (
    PlaceholderTestDetail,
    collect_placeholder_details,
    node_id_to_rp_name,
)
from scripts.rp_utils.rp_client import RPClient

LOGGER = get_logger(name=__name__)

RP_DEFAULT_URL = "https://reportportal-cnv.apps.dno.ocp-hub.prod.psi.redhat.com"
RP_DEFAULT_PROJECT = "cnv"
TERMINAL_WIDTH = 80

_VALID_STATUSES = {"PASSED", "FAILED", "SKIPPED"}


def _build_launch_attributes(
    team: str,
    bundle: str | None = None,
    cnv_version: str | None = None,
    arch: str | None = None,
    ocp_version: str | None = None,
    cluster_name: str | None = None,
    cluster_domain: str | None = None,
    storage_class: str | None = None,
    channel: str | None = None,
    tier: str | None = None,
    cluster_attrs: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build launch attribute list from CLI args and optional cluster attributes.

    Cluster-derived attributes serve as defaults; explicit CLI values
    override them.  ``TEAM`` and ``MANUAL`` are always present.

    Args:
        team: Team name (e.g. ``NETWORK``).
        bundle: Bundle version string.
        cnv_version: CNV X.Y version override.
        arch: Architecture override.
        ocp_version: OCP version override.
        cluster_name: Cluster name override.
        cluster_domain: Cluster domain override.
        storage_class: Storage-class label override.
        channel: Channel override.
        tier: Tier label (e.g. ``TIER-2``).
        cluster_attrs: Attributes auto-populated from ``--from-cluster``.

    Returns:
        Final list of ``{"key": ..., "value": ...}`` dicts.
    """
    # Start from cluster attrs (as a mutable copy) or empty list
    attrs_by_key: dict[str, str] = {}
    if cluster_attrs:
        for attr in cluster_attrs:
            attrs_by_key[attr["key"]] = attr["value"]

    # Map explicit CLI overrides to their RP attribute keys
    overrides: dict[str, str | None] = {
        "BUNDLE": bundle,
        "CNV_VERSION": cnv_version,
        "ARCHITECTURE": arch,
        "OCP_VERSION": ocp_version,
        "CLUSTER_NAME": cluster_name,
        "CLUSTER_DOMAIN": cluster_domain,
        "STORAGE_CLASS": storage_class,
        "CHANNEL": channel,
    }

    for key, value in overrides.items():
        if value is not None:
            attrs_by_key[key] = value

    # Mandatory attributes
    attrs_by_key["TEAM"] = team.upper()
    attrs_by_key["MANUAL"] = "true"

    if tier is not None:
        attrs_by_key["TIER"] = tier.upper()

    return [{"key": key, "value": value} for key, value in attrs_by_key.items()]


def _display_test_detail(test: PlaceholderTestDetail, index: int, total: int) -> None:
    """Display a single test's full context to stdout.

    Renders the test header, markers, fixtures, docstrings, and
    separator lines using a fixed-width terminal format.

    Args:
        test: Placeholder test detail to display.
        index: 1-based index of the current test.
        total: Total number of tests.
    """
    header_line = "═" * TERMINAL_WIDTH
    separator_line = "─" * TERMINAL_WIDTH

    # Header block
    click.echo(message=f"\n{header_line}")
    if test.class_name:
        click.echo(message=f"[{index}/{total}] {test.file_path}")
        click.echo(message=f"       {test.class_name}::{test.method_name}")
    else:
        click.echo(message=f"[{index}/{total}] {test.file_path}")
        click.echo(message=f"       {test.method_name}")
    click.echo(message=header_line)
    click.echo()

    # Module markers
    if test.module_markers:
        formatted_markers = ", ".join(f"@{marker}" for marker in test.module_markers)
        click.echo(message=f"Module markers: {formatted_markers}")

    # Class info
    if test.class_name:
        click.echo(message=f"Class:          {test.class_name}")

    # Class fixtures
    if test.class_fixtures:
        formatted_fixtures = ", ".join(f'"{fixture}"' for fixture in test.class_fixtures)
        click.echo(message=f"Class fixtures: @usefixtures({formatted_fixtures})")

    # Class markers
    if test.class_markers:
        formatted_class_markers = ", ".join(f"@{marker}" for marker in test.class_markers)
        click.echo(message=f"Class markers:  {formatted_class_markers}")

    # Test markers
    if test.test_markers:
        formatted_test_markers = ", ".join(f"@{marker}" for marker in test.test_markers)
        click.echo(message=f"Test markers:   {formatted_test_markers}")

    # Polarion ID
    if test.polarion_id:
        click.echo(message=f"Polarion:       {test.polarion_id}")

    # Module docstring (STP / preconditions)
    if test.module_docstring and test.module_docstring.strip():
        click.echo()
        click.echo(message="Module:")
        for line in test.module_docstring.strip().splitlines():
            click.echo(message=f"  {line}")

    # Class docstring
    if test.class_docstring and test.class_docstring.strip():
        click.echo()
        click.echo(message="Class docs:")
        for line in test.class_docstring.strip().splitlines():
            click.echo(message=f"  {line}")

    # Test docstring
    if test.test_docstring and test.test_docstring.strip():
        click.echo()
        click.echo(message="Description:")
        for line in test.test_docstring.strip().splitlines():
            click.echo(message=f"  {line}")

    click.echo()
    click.echo(message=separator_line)


def _run_interactive_mode(tests: list[PlaceholderTestDetail]) -> list[dict[str, Any]]:
    """Run interactive test result collection.

    Presents each placeholder test one-by-one and collects a verdict
    from the tester via the terminal.

    Args:
        tests: List of placeholder tests to present.

    Returns:
        List of result dicts:
        ``[{"test": node_id, "status": "PASSED"/"FAILED"/"SKIPPED", "comment": ""}]``
    """
    results: list[dict[str, Any]] = []
    total = len(tests)

    for index, test in enumerate(tests, start=1):
        _display_test_detail(test=test, index=index, total=total)

        while True:
            choice = (
                click
                .prompt(
                    "Result (p=pass, f=fail, s=skip, n=next, q=quit)",
                    type=str,
                )
                .strip()
                .lower()
            )

            if choice == "p":
                results.append({"test": test.node_id, "status": "PASSED", "comment": ""})
                break
            elif choice == "f":
                comment = click.prompt("Failure comment (optional)", default="", show_default=False)
                results.append({"test": test.node_id, "status": "FAILED", "comment": comment})
                break
            elif choice == "s":
                results.append({"test": test.node_id, "status": "SKIPPED", "comment": ""})
                break
            elif choice == "n":
                break
            elif choice == "q":
                click.echo(message="Quitting — returning results collected so far.")
                return results
            else:
                click.echo(message="Invalid choice. Use p/f/s/n/q.")

    return results


def _load_batch_file(batch_path: Path) -> list[dict[str, Any]]:
    """Load test results from a batch YAML file.

    Expected format::

        results:
          - test: "tests/foo/test_bar.py::TestClass::test_method"
            status: passed
            comment: "optional"

    Args:
        batch_path: Path to the YAML file.

    Returns:
        List of result dicts with test, status, and optional comment.

    Raises:
        click.ClickException: If the file format is invalid or a status
            value is unrecognised.
    """
    try:
        raw = yaml.safe_load(batch_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise click.ClickException(f"Failed to read batch file {batch_path}: {exc}") from exc

    if not isinstance(raw, dict) or "results" not in raw:
        raise click.ClickException(f"Batch file {batch_path} must contain a top-level 'results' key")

    results: list[dict[str, Any]] = []
    for entry in raw["results"]:
        status = entry.get("status", "").upper()
        if status not in _VALID_STATUSES:
            raise click.ClickException(
                f"Invalid status '{entry.get('status')}' for test '{entry.get('test')}'. "
                f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
            )
        results.append({
            "test": entry["test"],
            "status": status,
            "comment": entry.get("comment", ""),
        })

    LOGGER.info(f"Loaded {len(results)} results from batch file {batch_path}")
    return results


def _save_results_for_retry(results: list[dict[str, Any]], team: str, bundle: str | None) -> Path:
    """Save test results to a YAML file for later retry.

    The file is written to the current directory with a timestamped
    name so that multiple retry files can coexist.

    Args:
        results: List of result dicts to save.
        team: Team name.
        bundle: Bundle version.

    Returns:
        Path to the saved YAML file.
    """
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"manual_results_{timestamp}.yaml"
    output_path = Path.cwd() / filename

    payload: dict[str, Any] = {
        "metadata": {
            "team": team,
            "bundle": bundle,
            "saved_at": datetime.now(tz=UTC).isoformat(),
        },
        "results": results,
    }

    yaml_content = yaml.dump(data=payload, default_flow_style=False, sort_keys=False)
    output_path.write_text(data=yaml_content, encoding="utf-8")
    LOGGER.info(f"Saved {len(results)} results to {output_path}")
    return output_path


def _push_results_to_rp(
    rp_client: RPClient,
    results: list[dict[str, Any]],
    launch_name: str,
    attributes: list[dict[str, str]],
    tests: list[PlaceholderTestDetail] | None = None,
    description: str = "",
) -> int:
    """Push test results to ReportPortal.

    Creates a launch, populates it with test items (one per result),
    and finishes the launch.

    Args:
        rp_client: Authenticated RPClient instance.
        results: List of result dicts with test, status, comment.
        launch_name: Name for the RP launch.
        attributes: Launch attributes.
        tests: Optional list of placeholder test details for Polarion ID
            lookup. When provided, matching tests get a
            ``polarion-testcase-id`` attribute on their RP item.
        description: Launch description.

    Returns:
        The launch ID.
    """
    # Build a node_id → polarion_id lookup from collected tests
    polarion_lookup: dict[str, str] = {}
    if tests:
        for test in tests:
            if test.polarion_id:
                polarion_lookup[test.node_id] = test.polarion_id

    launch_id = rp_client.create_launch(name=launch_name, attributes=attributes, description=description)

    for result in results:
        item_name = node_id_to_rp_name(node_id=result["test"])
        item_attrs: list[dict[str, str]] | None = None

        polarion_id = polarion_lookup.get(result["test"])
        if polarion_id:
            item_attrs = [{"key": "polarion-testcase-id", "value": polarion_id}]

        rp_client.create_test_item(
            launch_id=launch_id,
            name=item_name,
            status=result["status"],
            description=result.get("comment", ""),
            attributes=item_attrs,
        )

    rp_client.finish_launch(launch_id=launch_id)
    LOGGER.info(f"Pushed {len(results)} results to launch {launch_id}")
    return launch_id


@click.command(
    help="Manual Test Reporter for ReportPortal",
    epilog="Collects manual test results for __test__ = False STD placeholder tests and pushes to ReportPortal.",
)
@click.option("--bundle", type=str, default=None, help="Bundle version prefix (e.g., v4.22.0.rhel9-102)")
@click.option("--team", type=str, required=True, help="Team name (e.g., NETWORK, STORAGE, VIRT)")
@click.option("--tier", type=str, default=None, help="Tier label (e.g., TIER-2)")
@click.option(
    "--tests-dir",
    type=click.Path(exists=True, path_type=Path),
    default=Path("tests"),
    help="Tests directory",
)
@click.option("--from-cluster", is_flag=True, default=False, help="Auto-fill attributes from connected cluster")
@click.option("--arch", type=str, default=None, help="Override architecture")
@click.option("--ocp-version", type=str, default=None, help="Override OCP version")
@click.option("--cnv-version", type=str, default=None, help="Override CNV X.Y version")
@click.option("--cluster-name", type=str, default=None, help="Override cluster name")
@click.option("--cluster-domain", type=str, default=None, help="Override cluster domain")
@click.option("--sc", type=str, default=None, help="Override storage class label")
@click.option("--channel", type=str, default=None, help="Override channel")
@click.option("--rp-url", type=str, default=RP_DEFAULT_URL, help="ReportPortal URL")
@click.option("--rp-project", type=str, default=RP_DEFAULT_PROJECT, help="RP project name")
@click.option("--rp-token", type=str, envvar="REPORT_PORTAL_TOKEN", default=None, help="RP API token")
@click.option(
    "--batch-file",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Batch YAML file with pre-filled results",
)
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be pushed without pushing")
def main(
    bundle: str | None,
    team: str,
    tier: str | None,
    tests_dir: Path,
    from_cluster: bool,
    arch: str | None,
    ocp_version: str | None,
    cnv_version: str | None,
    cluster_name: str | None,
    cluster_domain: str | None,
    sc: str | None,
    channel: str | None,
    rp_url: str,
    rp_project: str,
    rp_token: str | None,
    batch_file: Path | None,
    dry_run: bool,
) -> None:
    """Collect manual test results and push to ReportPortal.

    In interactive mode, each placeholder test is shown with full
    context and the tester marks it pass/fail/skip.  In batch mode a
    YAML file supplies pre-filled verdicts.
    """
    # ── 1. Resolve cluster attributes ──
    cluster_attrs: list[dict[str, str]] | None = None
    if from_cluster:
        from scripts.rp_manual_reporter.cluster_info import (  # noqa: PLC0415
            cluster_attributes_to_launch_attrs,
            get_cluster_attributes,
        )

        raw_cluster = get_cluster_attributes()
        cluster_attrs = cluster_attributes_to_launch_attrs(cluster_attrs=raw_cluster)
        click.echo(message=f"Loaded {len(cluster_attrs)} attributes from connected cluster.")

    # ── 2. Build launch attributes ──
    attributes = _build_launch_attributes(
        team=team,
        bundle=bundle,
        cnv_version=cnv_version,
        arch=arch,
        ocp_version=ocp_version,
        cluster_name=cluster_name,
        cluster_domain=cluster_domain,
        storage_class=sc,
        channel=channel,
        tier=tier,
        cluster_attrs=cluster_attrs,
    )

    # ── 3. Validate: bundle must be present ──
    has_bundle = any(attr["key"] == "BUNDLE" for attr in attributes)
    if not has_bundle and not from_cluster:
        raise click.ClickException("No BUNDLE attribute found. Provide --bundle or use --from-cluster to auto-detect.")

    # ── 4. Collect results ──
    collected_tests: list[PlaceholderTestDetail] | None = None

    if batch_file:
        results = _load_batch_file(batch_path=batch_file)
    else:
        click.echo(message=f"Scanning {tests_dir} for placeholder tests...")
        collected_tests = collect_placeholder_details(tests_dir=tests_dir)

        if not collected_tests:
            click.echo(message="No placeholder tests found.")
            sys.exit(0)

        click.echo(message=f"Found {len(collected_tests)} placeholder tests.\n")
        results = _run_interactive_mode(tests=collected_tests)

    # ── 5. Check for results ──
    if not results:
        click.echo(message="No results to push.")
        sys.exit(0)

    # ── 6. Dry-run summary ──
    if dry_run:
        click.echo(message="\n── Dry-run summary ──")
        click.echo(message=f"Results: {len(results)} tests")
        status_counts: dict[str, int] = {}
        for result in results:
            status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1
        for status, count in sorted(status_counts.items()):
            click.echo(message=f"  {status}: {count}")
        click.echo(message="\nAttributes:")
        for attr in attributes:
            click.echo(message=f"  {attr['key']} = {attr['value']}")
        click.echo(message="\nNo data was pushed to ReportPortal.")
        sys.exit(0)

    # ── 7. Validate token ──
    if not rp_token:
        raise click.ClickException("REPORT_PORTAL_TOKEN env var or --rp-token required.")

    # ── 8. Push to ReportPortal ──
    launch_name = f"Manual - {team.upper()}"
    if bundle:
        launch_name = f"{launch_name} - {bundle}"

    try:
        client = RPClient(base_url=rp_url, project=rp_project, token=rp_token)
        launch_id = _push_results_to_rp(
            rp_client=client,
            results=results,
            launch_name=launch_name,
            attributes=attributes,
            tests=collected_tests,
            description=f"Manual test results for {team.upper()}",
        )
        launch_url = f"{rp_url}/ui/#{rp_project}/launches/all/{launch_id}"
        click.echo(message=f"\n✓ Launch created: {launch_url}")

    except Exception as exc:
        LOGGER.error(f"Failed to push results to ReportPortal: {exc}")
        saved_path = _save_results_for_retry(results=results, team=team, bundle=bundle)
        click.echo(message=f"\n✗ Push failed: {exc}", err=True)
        click.echo(message=f"  Results saved to: {saved_path}", err=True)
        click.echo(message=f"  Retry with: --batch-file {saved_path}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
