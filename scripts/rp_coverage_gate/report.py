"""Coverage report generator.

Produces text or JSON reports showing test coverage status against
ReportPortal execution data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from scripts.rp_coverage_gate.rp_checker import ItemResult
from scripts.rp_coverage_gate.test_collector import node_id_to_rp_name

LOGGER = logging.getLogger(__name__)

TERMINAL_WIDTH = 100


@dataclass
class CoverageReport:
    """Test coverage analysis results.

    Attributes:
        total_tests: Total tests in repo.
        automated_count: Number of automated tests.
        unautomated_count: Number of STD placeholder tests.
        passed: List of (node_id, ItemResult) for passed tests.
        failed: List of (node_id, ItemResult) for failed tests.
        skipped: List of (node_id, ItemResult) for skipped tests.
        never_executed: List of node_ids with no RP results.
        stale: List of (node_id, ItemResult) for stale tests.
        gate_passed: Whether the gate check passed.
        gating_never_executed: List of gating node_ids with no RP results.
        gating_stale: List of (node_id, ItemResult) for stale gating tests.
    """

    total_tests: int
    automated_count: int
    unautomated_count: int
    passed: list[tuple[str, ItemResult]]
    failed: list[tuple[str, ItemResult]]
    skipped: list[tuple[str, ItemResult]]
    never_executed: list[str]
    stale: list[tuple[str, ItemResult]]
    gate_passed: bool
    gating_never_executed: list[str]
    gating_stale: list[tuple[str, ItemResult]]


def _get_team_from_node_id(node_id: str) -> str:
    """Extract the team name from a pytest node ID.

    The team is the first directory component after ``tests/``.

    Args:
        node_id: Pytest-style node ID, e.g.
            ``tests/network/foo/test_bar.py::TestClass::test_method``.

    Returns:
        Team name, e.g. ``network``. Returns empty string if not determinable.
    """
    parts = node_id.split("/")
    if len(parts) >= 2 and parts[0] == "tests":
        return parts[1]
    return ""


def analyze_coverage(
    automated_ids: list[str],
    unautomated_ids: list[str],
    rp_results: dict[str, ItemResult],
    stale_days: int = 30,
    team_filter: str | None = None,
    fail_on_stale: bool = True,
    gating_ids: set[str] | None = None,
) -> CoverageReport:
    """Analyze test coverage by cross-referencing repo tests with RP results.

    Args:
        automated_ids: Pytest node IDs for automated tests.
        unautomated_ids: Pytest node IDs for unautomated tests.
        rp_results: Dict from rp_checker.check_coverage.
        stale_days: Threshold for stale tests.
        team_filter: Optional team name to filter results.
        fail_on_stale: Whether stale tests cause gate failure.
        gating_ids: Optional set of gating-marked test node IDs.

    Returns:
        CoverageReport with categorized results.
    """
    all_ids = automated_ids + unautomated_ids

    if team_filter:
        all_ids = [node_id for node_id in all_ids if _get_team_from_node_id(node_id=node_id) == team_filter]

    now = datetime.now(tz=UTC)
    passed: list[tuple[str, ItemResult]] = []
    failed: list[tuple[str, ItemResult]] = []
    skipped: list[tuple[str, ItemResult]] = []
    never_executed: list[str] = []
    stale: list[tuple[str, ItemResult]] = []

    filtered_automated_count = len([
        node_id
        for node_id in automated_ids
        if not team_filter or _get_team_from_node_id(node_id=node_id) == team_filter
    ])
    filtered_unautomated_count = len([
        node_id
        for node_id in unautomated_ids
        if not team_filter or _get_team_from_node_id(node_id=node_id) == team_filter
    ])

    for node_id in all_ids:
        rp_name = node_id_to_rp_name(node_id=node_id)
        result = rp_results.get(rp_name)

        if result is None:
            never_executed.append(node_id)
            continue

        # Check staleness
        if result.last_executed:
            try:
                executed_time = datetime.fromisoformat(result.last_executed)
                if executed_time.tzinfo is None:
                    executed_time = executed_time.replace(tzinfo=UTC)
                age_days = (now - executed_time).days
                if age_days > stale_days:
                    stale.append((node_id, result))
            except ValueError, TypeError:
                LOGGER.warning(f"Could not parse timestamp for {rp_name}: {result.last_executed}")

        # Categorize by status
        status_upper = result.status.upper()
        if status_upper == "PASSED":
            passed.append((node_id, result))
        elif status_upper == "FAILED":
            failed.append((node_id, result))
        elif status_upper == "SKIPPED":
            skipped.append((node_id, result))

    gating_never_executed: list[str] = []
    gating_stale: list[tuple[str, ItemResult]] = []

    if gating_ids:
        gating_never_executed = [nid for nid in never_executed if nid in gating_ids]
        gating_stale = [(nid, res) for nid, res in stale if nid in gating_ids]

    gate_passed = len(never_executed) == 0
    if fail_on_stale and len(stale) > 0:
        gate_passed = False

    return CoverageReport(
        total_tests=len(all_ids),
        automated_count=filtered_automated_count,
        unautomated_count=filtered_unautomated_count,
        passed=passed,
        failed=failed,
        skipped=skipped,
        never_executed=never_executed,
        stale=stale,
        gate_passed=gate_passed,
        gating_never_executed=gating_never_executed,
        gating_stale=gating_stale,
    )


def format_text_report(
    report: CoverageReport,
    bundle_prefix: str,
    stale_days: int,
    full: bool = False,
) -> str:
    """Generate a human-readable text report of coverage results.

    Args:
        report: CoverageReport from analyze_coverage.
        bundle_prefix: Bundle version string for the header.
        stale_days: Stale threshold in days for the header.
        full: If True, include per-test detail lines.

    Returns:
        Formatted text report string.
    """
    separator = "=" * TERMINAL_WIDTH
    lines: list[str] = []

    lines.append(separator)
    lines.append(f"Test Coverage Gate — {bundle_prefix} (stale threshold: {stale_days} days)")
    lines.append(separator)
    lines.append("")

    executed_count = len(report.passed) + len(report.failed) + len(report.skipped)
    coverage_pct = (executed_count / report.total_tests * 100) if report.total_tests > 0 else 0.0

    lines.append(f"Total tests in repo:     {report.total_tests:,}")
    lines.append(f"  Automated:             {report.automated_count:,}")
    lines.append(f"  Unautomated (STD):     {report.unautomated_count:,}")
    lines.append("")
    lines.append(f"Executed in RP:          {executed_count:,}")
    lines.append(f"  Passed:                {len(report.passed):,}")
    lines.append(f"  Failed:                {len(report.failed):,}")
    lines.append(f"  Skipped:               {len(report.skipped):,}")
    lines.append(f"  Stale (>{stale_days}d):          {len(report.stale):,}")
    lines.append("")
    lines.append(f"Never executed:          {len(report.never_executed):,}")
    lines.append(f"Coverage:                {coverage_pct:.1f}%")
    lines.append("")

    gating_gap_count = len(report.gating_never_executed) + len(report.gating_stale)
    if gating_gap_count > 0:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append(f"GATING — never executed or stale ({gating_gap_count}):")
        lines.append("-" * TERMINAL_WIDTH)
        for node_id in sorted(report.gating_never_executed):
            lines.append(f"  ⚠ {node_id} [NEVER EXECUTED]")
        for node_id, result in sorted(report.gating_stale, key=lambda entry: entry[0]):
            date_str = result.last_executed[:10] if result.last_executed else "unknown"
            lines.append(f"  ⚠ {node_id} [STALE: {date_str}]")
        lines.append("")

    if report.failed:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append("FAILED TESTS:")
        lines.append("-" * TERMINAL_WIDTH)
        for node_id, result in sorted(report.failed, key=lambda entry: entry[0]):
            polarion = f" [{result.polarion_id}]" if result.polarion_id else ""
            lines.append(
                f"  {node_id}  bundle={result.bundle}  date={result.last_executed}  source={result.source}{polarion}"
            )
        lines.append("")

    if full:
        if report.never_executed:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("NEVER EXECUTED:")
            lines.append("-" * TERMINAL_WIDTH)
            for node_id in sorted(report.never_executed):
                lines.append(f"  {node_id}")
            lines.append("")

        if report.stale:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("STALE TESTS:")
            lines.append("-" * TERMINAL_WIDTH)
            for node_id, result in sorted(report.stale, key=lambda entry: entry[0]):
                polarion = f" [{result.polarion_id}]" if result.polarion_id else ""
                lines.append(
                    f"  {node_id}  status={result.status}  bundle={result.bundle}"
                    f"  date={result.last_executed}  source={result.source}{polarion}"
                )
            lines.append("")

        if report.passed:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("PASSED TESTS:")
            lines.append("-" * TERMINAL_WIDTH)
            for node_id, result in sorted(report.passed, key=lambda entry: entry[0]):
                polarion = f" [{result.polarion_id}]" if result.polarion_id else ""
                lines.append(
                    f"  {node_id}  bundle={result.bundle}"
                    f"  date={result.last_executed}  source={result.source}{polarion}"
                )
            lines.append("")

        if report.skipped:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("SKIPPED TESTS:")
            lines.append("-" * TERMINAL_WIDTH)
            for node_id, result in sorted(report.skipped, key=lambda entry: entry[0]):
                polarion = f" [{result.polarion_id}]" if result.polarion_id else ""
                lines.append(
                    f"  {node_id}  bundle={result.bundle}"
                    f"  date={result.last_executed}  source={result.source}{polarion}"
                )
            lines.append("")

    gate_status = "PASSED" if report.gate_passed else "FAILED"
    lines.append(f"GATE: {gate_status}")
    lines.append(separator)

    return "\n".join(lines)


def format_json_report(
    report: CoverageReport,
    bundle_prefix: str,
    stale_days: int,
) -> str:
    """Generate a JSON report of coverage results.

    Args:
        report: CoverageReport from analyze_coverage.
        bundle_prefix: Bundle version string.
        stale_days: Stale threshold in days.

    Returns:
        JSON-formatted string with all report data.
    """

    def _result_to_dict(node_id: str, result: ItemResult) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "rp_name": result.name,
            "status": result.status,
            "last_executed": result.last_executed,
            "bundle": result.bundle,
            "launch_name": result.launch_name,
            "polarion_id": result.polarion_id,
            "source": result.source,
        }

    executed_count = len(report.passed) + len(report.failed) + len(report.skipped)
    coverage_pct = (executed_count / report.total_tests * 100) if report.total_tests > 0 else 0.0

    data: dict[str, Any] = {
        "bundle_prefix": bundle_prefix,
        "stale_days": stale_days,
        "gate_passed": report.gate_passed,
        "summary": {
            "total_tests": report.total_tests,
            "automated_count": report.automated_count,
            "unautomated_count": report.unautomated_count,
            "executed_count": executed_count,
            "coverage_pct": round(coverage_pct, 2),
            "passed_count": len(report.passed),
            "failed_count": len(report.failed),
            "skipped_count": len(report.skipped),
            "stale_count": len(report.stale),
            "never_executed_count": len(report.never_executed),
        },
        "passed": [
            _result_to_dict(node_id=node_id, result=result)
            for node_id, result in sorted(report.passed, key=lambda entry: entry[0])
        ],
        "failed": [
            _result_to_dict(node_id=node_id, result=result)
            for node_id, result in sorted(report.failed, key=lambda entry: entry[0])
        ],
        "skipped": [
            _result_to_dict(node_id=node_id, result=result)
            for node_id, result in sorted(report.skipped, key=lambda entry: entry[0])
        ],
        "stale": [
            _result_to_dict(node_id=node_id, result=result)
            for node_id, result in sorted(report.stale, key=lambda entry: entry[0])
        ],
        "never_executed": sorted(report.never_executed),
        "gating": {
            "never_executed": sorted(report.gating_never_executed),
            "stale": [
                _result_to_dict(node_id=node_id, result=result)
                for node_id, result in sorted(report.gating_stale, key=lambda entry: entry[0])
            ],
        },
    }

    return json.dumps(obj=data, indent=2)
