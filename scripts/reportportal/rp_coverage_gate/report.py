# Co-authored-by: Claude <noreply@anthropic.com>
"""Coverage report generator.

Produces text, JSON, or HTML reports showing test coverage status
against ReportPortal execution data.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from scripts.reportportal.rp_coverage_gate.rp_checker import ItemResult
from scripts.reportportal.rp_coverage_gate.test_collector import QuarantinedTest
from scripts.reportportal.rp_utils.naming import node_id_to_rp_name

LOGGER = logging.getLogger(__name__)

TERMINAL_WIDTH = 100


def _split_params(node_id: str) -> tuple[str, str]:
    """Split a node ID into base test name and parameter suffix.

    Args:
        node_id: Pytest node ID, possibly with ``[params]`` suffix.

    Returns:
        Tuple of (base_name, params). Params is the bracketed part
        including ``[`` and ``]``, or empty string if not parametrized.
    """
    bracket_idx = node_id.find("[")
    if bracket_idx == -1:
        return node_id, ""
    return node_id[:bracket_idx], node_id[bracket_idx:]


def _parse_two_axis_params(params: str) -> tuple[str, str] | None:
    """Parse ``[#val1#-#val2#]`` into ``(val1, val2)``.

    Args:
        params: Parameter suffix string, e.g. ``[#rhel.10#-#hostpath-csi-basic#]``.

    Returns:
        Tuple of (axis1_value, axis2_value) if 2-axis format, None otherwise.
    """
    inner = params.strip("[]")
    parts = inner.split("#-#")
    if len(parts) == 2:
        return (parts[0].strip("#"), parts[1].strip("#"))
    return None


def _parse_hash_suffix_params(params: str) -> tuple[str, str] | None:
    """Parse ``[#val#-suffix]`` into ``(val, suffix)``.

    Handles the pattern where one axis uses ``#value#`` delimiters and
    the second axis is a plain suffix after a ``-`` separator.

    Args:
        params: Parameter suffix string, e.g. ``[#hostpath-csi-basic#-test_restore_basic_snapshot0]``.

    Returns:
        Tuple of (hash_value, suffix) if the pattern matches, None otherwise.
    """
    import re  # noqa: PLC0415

    match = re.match(r"^\[#([^#]+)#-(.+)\]$", params)
    if match:
        return (match.group(1), match.group(2))
    return None


def _detect_implicit_two_axis(
    variants: list[VariantStatus],
) -> tuple[bool, list[str], list[str]]:
    """Detect implicit 2-axis from ``[#val#-suffix]`` patterns.

    When all variants match ``#value#-suffix`` and there are multiple
    distinct suffixes (not just fixture names), the test is implicitly
    2-axis with hash values as axis 1 and suffixes as axis 2.

    If all suffixes are identical (e.g. fixture names like
    ``data_volume_multi_storage_scope_function0``), this is NOT 2-axis
    — it's single-axis with a junk suffix.

    Args:
        variants: List of variant statuses to analyze.

    Returns:
        Tuple of (is_two_axis, axis1_values, axis2_values).
    """
    parsed = [_parse_hash_suffix_params(params=v.params) for v in variants]
    if not all(p is not None for p in parsed):
        return (False, [], [])

    suffixes: set[str] = {p[1] for p in parsed if p}  # type: ignore[index]
    if len(suffixes) <= 1:
        return (False, [], [])

    axis1_set: set[str] = {p[0] for p in parsed if p}  # type: ignore[index]
    return (True, sorted(axis1_set), sorted(suffixes))


@dataclass
class VariantStatus:
    """Status of a single parametrized variant.

    Attributes:
        params: Parameter suffix (e.g., ``[#rhel.10#-#hostpath#]``).
        status: One of PASSED, FAILED, NEVER_EXECUTED, STALE, SKIPPED, QUARANTINED.
        result: ItemResult for executed tests, None for never-executed/quarantined.
        defect_type: Defect classification for FAILED tests.
    """

    params: str
    status: str
    result: ItemResult | None
    defect_type: str | None = None


@dataclass
class ParametrizedTestSummary:
    """Summary of all variants for a parametrized test.

    Attributes:
        base_test: Base test name without parameters.
        variants: All variant statuses.
        is_two_axis: True if all variants match 2-axis format.
        axis1_values: Row header values (sorted).
        axis2_values: Column header values (sorted).
    """

    base_test: str
    variants: list[VariantStatus]
    is_two_axis: bool
    axis1_values: list[str]
    axis2_values: list[str]


_DEFECT_ABBREVS: dict[str, str] = {
    "Product Bug": "Product Bug",
    "Automation Bug": "Auto Bug",
    "System Issue": "Sys Issue",
    "To Investigate": "To Invest.",
    "No Defect": "No Defect",
    "Not Issue": "No Defect",
}


_STATUS_SYMBOLS: dict[str, str] = {
    "PASSED": "✅",
    "FAILED": "❌",
    "NEVER_EXECUTED": "\u2014",
    "STALE": "\u26a0\ufe0f",
    "SKIPPED": "SKIP",
    "QUARANTINED": "Q",
}

_STATUS_CSS: dict[str, str] = {
    "PASSED": "status-passed",
    "FAILED": "status-failed",
    "NEVER_EXECUTED": "status-never",
    "STALE": "status-stale",
    "SKIPPED": "status-skipped",
    "QUARANTINED": "status-quarantined",
}


def _group_by_base(
    items: list[str],
) -> list[tuple[str, list[str]]]:
    """Group node IDs by base test name, preserving sorted order.

    Args:
        items: List of node IDs.

    Returns:
        List of (base_name, [params...]) tuples. Single-variant tests
        have a one-element params list (possibly empty string).
    """
    groups: dict[str, list[str]] = {}
    for node_id in sorted(items):
        base, params = _split_params(node_id=node_id)
        groups.setdefault(base, []).append(params)
    return [(base, params) for base, params in groups.items()]


def _group_results_by_base(
    items: list[tuple[str, ItemResult]],
) -> list[tuple[str, list[tuple[str, ItemResult]]]]:
    """Group (node_id, result) tuples by base test name.

    Args:
        items: List of (node_id, ItemResult) tuples.

    Returns:
        List of (base_name, [(params, result)...]) tuples.
    """
    groups: dict[str, list[tuple[str, ItemResult]]] = {}
    for node_id, result in sorted(items, key=lambda entry: entry[0]):
        base, params = _split_params(node_id=node_id)
        groups.setdefault(base, []).append((params, result))
    return list(groups.items())


def _group_ids_by_team(items: list[str]) -> list[tuple[str, list[str]]]:
    """Group node IDs by team, sorted alphabetically.

    Args:
        items: List of pytest node IDs.

    Returns:
        List of (team_name, [node_ids...]) sorted by team.
    """
    teams: dict[str, list[str]] = {}
    for node_id in items:
        team = _get_team_from_node_id(node_id=node_id)
        teams.setdefault(team or "other", []).append(node_id)
    return sorted(teams.items())


def _group_results_by_team(
    items: list[tuple[str, ItemResult]],
) -> list[tuple[str, list[tuple[str, ItemResult]]]]:
    """Group (node_id, result) tuples by team, sorted alphabetically.

    Args:
        items: List of (node_id, ItemResult) tuples.

    Returns:
        List of (team_name, [(node_id, result)...]) sorted by team.
    """
    teams: dict[str, list[tuple[str, ItemResult]]] = {}
    for node_id, result in items:
        team = _get_team_from_node_id(node_id=node_id)
        teams.setdefault(team or "other", []).append((node_id, result))
    return sorted(teams.items())


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
    never_executed_automated: list[str]
    never_executed_manual: list[str]
    stale: list[tuple[str, ItemResult]]
    gate_passed: bool
    gating_never_executed: list[str]
    gating_stale: list[tuple[str, ItemResult]]
    quarantined: list[QuarantinedTest]
    parametrized_summaries: dict[str, list[ParametrizedTestSummary]] | None = None
    team_stats: dict[str, TeamStats] | None = None


@dataclass
class TeamStats:
    """Per-team coverage statistics.

    Attributes:
        total: Total tests for this team.
        passed: Number of passed tests.
        failed: Number of failed tests.
        skipped: Number of skipped tests.
        never_executed: Number of never-executed tests.
        stale: Number of stale tests.
        coverage_pct: Percentage of tests with RP results.
    """

    total: int
    passed: int
    failed: int
    skipped: int
    never_executed: int
    stale: int
    quarantined: int
    coverage_pct: float


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
    exclude_teams: tuple[str, ...] | None = None,
    quarantined: list[QuarantinedTest] | None = None,
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
        exclude_teams: Optional teams to exclude from the report.

    Returns:
        CoverageReport with categorized results.
    """
    all_ids = automated_ids + unautomated_ids

    if team_filter:
        all_ids = [node_id for node_id in all_ids if _get_team_from_node_id(node_id=node_id) == team_filter]

    exclude_set = set(exclude_teams) if exclude_teams else set()
    if exclude_set:
        all_ids = [node_id for node_id in all_ids if _get_team_from_node_id(node_id=node_id) not in exclude_set]

    # Filter quarantined tests
    filtered_quarantined: list[QuarantinedTest] = []
    quarantined_node_ids: set[str] = set()
    if quarantined:
        for qt in quarantined:
            team = _get_team_from_node_id(node_id=qt.node_id)
            if team_filter and team != team_filter:
                continue
            if team in exclude_set:
                continue
            filtered_quarantined.append(qt)
            quarantined_node_ids.add(qt.node_id)

    # Remove quarantined from all_ids so they don't appear as never-executed
    all_ids = [nid for nid in all_ids if nid not in quarantined_node_ids]

    now = datetime.now(tz=UTC)
    passed: list[tuple[str, ItemResult]] = []
    failed: list[tuple[str, ItemResult]] = []
    skipped: list[tuple[str, ItemResult]] = []
    never_executed: list[str] = []
    never_executed_automated: list[str] = []
    never_executed_manual: list[str] = []
    stale: list[tuple[str, ItemResult]] = []

    unautomated_id_set = set(unautomated_ids)

    def _id_passes_filters(node_id: str) -> bool:
        team = _get_team_from_node_id(node_id=node_id)
        if team_filter and team != team_filter:
            return False
        return team not in exclude_set

    filtered_automated_count = sum(1 for node_id in automated_ids if _id_passes_filters(node_id=node_id))
    filtered_unautomated_count = sum(1 for node_id in unautomated_ids if _id_passes_filters(node_id=node_id))

    for node_id in all_ids:
        rp_name = node_id_to_rp_name(node_id=node_id)
        result = rp_results.get(rp_name)

        if result is None:
            never_executed.append(node_id)
            if node_id in unautomated_id_set:
                never_executed_manual.append(node_id)
            else:
                never_executed_automated.append(node_id)
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

    # Compute per-team stats
    team_stats: dict[str, TeamStats] = {}
    team_total: dict[str, int] = {}
    team_passed: dict[str, int] = {}
    team_failed: dict[str, int] = {}
    team_skipped: dict[str, int] = {}
    team_never: dict[str, int] = {}
    team_stale_count: dict[str, int] = {}
    team_quarantined: dict[str, int] = {}

    for node_id in all_ids:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        team_total[team] = team_total.get(team, 0) + 1

    for node_id, _result in passed:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        team_passed[team] = team_passed.get(team, 0) + 1

    for node_id, _result in failed:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        team_failed[team] = team_failed.get(team, 0) + 1

    for node_id, _result in skipped:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        team_skipped[team] = team_skipped.get(team, 0) + 1

    for node_id in never_executed:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        team_never[team] = team_never.get(team, 0) + 1

    for node_id, _result in stale:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        team_stale_count[team] = team_stale_count.get(team, 0) + 1

    for qt in filtered_quarantined:
        team = _get_team_from_node_id(node_id=qt.node_id) or "other"
        team_quarantined[team] = team_quarantined.get(team, 0) + 1
        # Add to team_total if not already counted (quarantined tests were removed from all_ids)
        team_total[team] = team_total.get(team, 0) + 1

    for team, total in team_total.items():
        p_count = team_passed.get(team, 0)
        f_count = team_failed.get(team, 0)
        s_count = team_skipped.get(team, 0)
        ne_count = team_never.get(team, 0)
        st_count = team_stale_count.get(team, 0)
        q_count = team_quarantined.get(team, 0)
        executed = p_count + f_count + s_count
        pct = (executed / total * 100) if total > 0 else 0.0
        team_stats[team] = TeamStats(
            total=total,
            passed=p_count,
            failed=f_count,
            skipped=s_count,
            never_executed=ne_count,
            stale=st_count,
            quarantined=q_count,
            coverage_pct=round(pct, 1),
        )

    # Build parametrized test summaries per team
    all_node_ids_with_status: dict[str, tuple[str, ItemResult | None, str | None]] = {}
    for node_id, result in passed:
        all_node_ids_with_status[node_id] = ("PASSED", result, None)
    for node_id, result in failed:
        all_node_ids_with_status[node_id] = ("FAILED", result, result.defect_type)
    for node_id, result in skipped:
        all_node_ids_with_status[node_id] = ("SKIPPED", result, None)
    for node_id, result in stale:
        all_node_ids_with_status[node_id] = ("STALE", result, None)
    for node_id in never_executed:
        all_node_ids_with_status[node_id] = ("NEVER_EXECUTED", None, None)
    for qt in filtered_quarantined:
        all_node_ids_with_status[qt.node_id] = ("QUARANTINED", None, None)

    # Group by base test name
    base_test_variants: dict[str, list[tuple[str, str]]] = {}
    for node_id in list(all_node_ids_with_status):
        base, params = _split_params(node_id=node_id)
        if params:
            base_test_variants.setdefault(base, []).append((node_id, params))

    parametrized_summaries: dict[str, list[ParametrizedTestSummary]] = {}
    for base, variant_list in base_test_variants.items():
        if len(variant_list) < 2:
            continue
        variants: list[VariantStatus] = []
        for node_id, params in variant_list:
            status, result, defect = all_node_ids_with_status.get(node_id, ("NEVER_EXECUTED", None, None))
            variants.append(VariantStatus(params=params, status=status, result=result, defect_type=defect))

        # Check if all variants are 2-axis
        parsed = [_parse_two_axis_params(params=v.params) for v in variants]
        is_two_axis = all(p is not None for p in parsed)

        axis1_values: list[str] = []
        axis2_values: list[str] = []
        if is_two_axis:
            axis1_set: set[str] = set()
            axis2_set: set[str] = set()
            for p in parsed:
                if p:
                    axis1_set.add(p[0])
                    axis2_set.add(p[1])
            axis1_values = sorted(axis1_set)
            axis2_values = sorted(axis2_set)
        else:
            # Fallback: detect implicit 2-axis from #val#-suffix patterns
            is_two_axis, axis1_values, axis2_values = _detect_implicit_two_axis(variants=variants)

        summary = ParametrizedTestSummary(
            base_test=base,
            variants=variants,
            is_two_axis=is_two_axis,
            axis1_values=axis1_values,
            axis2_values=axis2_values,
        )
        team = _get_team_from_node_id(node_id=base) or "other"
        parametrized_summaries.setdefault(team, []).append(summary)

    return CoverageReport(
        total_tests=len(all_ids),
        automated_count=filtered_automated_count,
        unautomated_count=filtered_unautomated_count,
        passed=passed,
        failed=failed,
        skipped=skipped,
        never_executed=never_executed,
        never_executed_automated=never_executed_automated,
        never_executed_manual=never_executed_manual,
        stale=stale,
        gate_passed=gate_passed,
        gating_never_executed=gating_never_executed,
        gating_stale=gating_stale,
        quarantined=filtered_quarantined,
        parametrized_summaries=parametrized_summaries if parametrized_summaries else None,
        team_stats=team_stats,
    )


def _format_text_filters(filters: dict[str, Any]) -> list[str]:
    """Format active filters as indented text lines.

    Only includes filters that differ from their defaults.

    Args:
        filters: Dict of filter name to value.

    Returns:
        List of formatted lines (may be empty if no non-default filters).
    """
    lines: list[str] = []
    if filters.get("team"):
        lines.append(f"  Team:             {filters['team']}")
    if filters.get("exclude_teams"):
        lines.append(f"  Excluded teams:   {', '.join(filters['exclude_teams'])}")
    if filters.get("max_launches", 0) != 0:
        lines.append(f"  Max launches:     {filters['max_launches']}")
    if str(filters.get("tests_dir", "tests")) != "tests":
        lines.append(f"  Tests dir:        {filters['tests_dir']}")
    return lines


def format_text_report(
    report: CoverageReport,
    bundle_prefix: str,
    stale_days: int,
    full: bool = False,
    filters: dict[str, Any] | None = None,
) -> str:
    """Generate a human-readable text report of coverage results.

    Args:
        report: CoverageReport from analyze_coverage.
        bundle_prefix: Bundle version string for the header.
        stale_days: Stale threshold in days for the header.
        full: If True, include per-test detail lines.
        filters: Optional dict of active filters for the header.

    Returns:
        Formatted text report string.
    """
    separator = "=" * TERMINAL_WIDTH
    lines: list[str] = []

    lines.append(separator)
    lines.append(f"Test Coverage Gate — {bundle_prefix} (stale threshold: {stale_days} days)")
    lines.append(separator)

    if filters:
        filter_lines = _format_text_filters(filters=filters)
        if filter_lines:
            lines.append("Filters:")
            lines.extend(filter_lines)

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
    lines.append(f"  Automated:             {len(report.never_executed_automated):,}")
    lines.append(f"  Manual (STD):          {len(report.never_executed_manual):,}")
    lines.append(f"Quarantined:             {len(report.quarantined):,}")
    lines.append(f"Coverage:                {coverage_pct:.1f}%")
    lines.append("")

    gating_gap_count = len(report.gating_never_executed) + len(report.gating_stale)
    if gating_gap_count > 0:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append(f"GATING — never executed or stale ({gating_gap_count}):")
        lines.append("-" * TERMINAL_WIDTH)
        for team, team_ids in _group_ids_by_team(items=report.gating_never_executed):
            lines.append(f"  ── {team} ({len(team_ids)}) ──")
            for base, params_list in _group_by_base(items=team_ids):
                if len(params_list) == 1 and not params_list[0]:
                    lines.append(f"    ⚠ {base} [NEVER EXECUTED]")
                elif len(params_list) == 1:
                    lines.append(f"    ⚠ {base}{params_list[0]} [NEVER EXECUTED]")
                else:
                    lines.append(f"    ⚠ {base} ({len(params_list)} variants) [NEVER EXECUTED]")
                    for params in params_list:
                        lines.append(f"        {params}")
        for team, team_items in _group_results_by_team(items=report.gating_stale):
            lines.append(f"  ── {team} ({len(team_items)}) ──")
            for node_id, result in sorted(team_items, key=lambda entry: entry[0]):
                date_str = result.last_executed[:10] if result.last_executed else "unknown"
                lines.append(f"    ⚠ {node_id} [STALE: {date_str}]")
        lines.append("")

    if report.failed:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append(f"FAILED TESTS ({len(report.failed)}):")
        lines.append("-" * TERMINAL_WIDTH)

        # Group by defect type
        defect_groups: dict[str, list[tuple[str, ItemResult]]] = {}
        for node_id, result in sorted(report.failed, key=lambda entry: entry[0]):
            group_key = result.defect_type or "Unclassified"
            defect_groups.setdefault(group_key, []).append((node_id, result))

        # Display order: Product Bug, Automation Bug, System Issue, To Investigate, then rest
        display_order = ["Product Bug", "Automation Bug", "System Issue", "To Investigate", "No Defect", "Not Issue"]
        sorted_groups = []
        for group_name in display_order:
            if group_name in defect_groups:
                sorted_groups.append((group_name, defect_groups.pop(group_name)))
        for group_name in sorted(defect_groups):
            sorted_groups.append((group_name, defect_groups[group_name]))

        max_comment_len = 60
        for group_name, group_items in sorted_groups:
            lines.append(f"  {group_name} ({len(group_items)}):")
            for team, team_items in _group_results_by_team(items=group_items):
                lines.append(f"    ── {team} ({len(team_items)}) ──")
                for node_id, result in team_items:
                    comment = ""
                    if result.defect_comment:
                        truncated = result.defect_comment[:max_comment_len]
                        if len(result.defect_comment) > max_comment_len:
                            truncated += "..."
                        comment = f"  [{truncated}]"
                    lines.append(f"      {node_id}  bundle={result.bundle}{comment}")
        lines.append("")

    if report.quarantined:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append(f"QUARANTINED ({len(report.quarantined)}):")
        lines.append("-" * TERMINAL_WIDTH)
        quarantined_by_team: dict[str, list[QuarantinedTest]] = {}
        for qt in report.quarantined:
            team = _get_team_from_node_id(node_id=qt.node_id) or "other"
            quarantined_by_team.setdefault(team, []).append(qt)
        for team in sorted(quarantined_by_team):
            team_qts = quarantined_by_team[team]
            lines.append(f"  ── {team} ({len(team_qts)}) ──")
            for qt in sorted(team_qts, key=lambda q: q.node_id):
                jira_str = f"  [{qt.jira}]" if qt.jira else ""
                lines.append(f"    ⏸ {qt.node_id}{jira_str}")
                if qt.reason:
                    lines.append(f"        {qt.reason[:80]}")
        lines.append("")

    if report.never_executed_manual:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append(f"MANUAL TESTS — never executed ({len(report.never_executed_manual)}):")
        lines.append("-" * TERMINAL_WIDTH)
        for base, params_list in _group_by_base(items=report.never_executed_manual):
            if len(params_list) == 1 and not params_list[0]:
                lines.append(f"  {base}")
            elif len(params_list) == 1:
                lines.append(f"  {base}{params_list[0]}")
            else:
                lines.append(f"  {base} ({len(params_list)} variants)")
                for params in params_list:
                    lines.append(f"    {params}")
        lines.append("")

    if full:
        if report.never_executed:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("NEVER EXECUTED:")
            lines.append("-" * TERMINAL_WIDTH)
            manual_set = set(report.never_executed_manual)
            for team, team_ids in _group_ids_by_team(items=report.never_executed):
                lines.append(f"  ── {team} ({len(team_ids)}) ──")
                for base, params_list in _group_by_base(items=team_ids):
                    if len(params_list) == 1 and not params_list[0]:
                        label = " [MANUAL]" if base in manual_set else ""
                        lines.append(f"    {base}{label}")
                    elif len(params_list) == 1:
                        full_id = f"{base}{params_list[0]}"
                        label = " [MANUAL]" if full_id in manual_set else ""
                        lines.append(f"    {full_id}{label}")
                    else:
                        lines.append(f"    {base} ({len(params_list)} variants)")
                        for params in params_list:
                            full_id = f"{base}{params}"
                            label = " [MANUAL]" if full_id in manual_set else ""
                            lines.append(f"      {params}{label}")
            lines.append("")

        if report.stale:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("STALE TESTS:")
            lines.append("-" * TERMINAL_WIDTH)
            for team, team_items in _group_results_by_team(items=report.stale):
                lines.append(f"  ── {team} ({len(team_items)}) ──")
                for base, variants in _group_results_by_base(items=team_items):
                    if len(variants) == 1 and not variants[0][0]:
                        result = variants[0][1]
                        lines.append(
                            f"    {base}  status={result.status}  bundle={result.bundle}"
                            f"  date={result.last_executed}  source={result.source}"
                        )
                    elif len(variants) == 1:
                        params, result = variants[0]
                        lines.append(
                            f"    {base}{params}  status={result.status}  bundle={result.bundle}"
                            f"  date={result.last_executed}  source={result.source}"
                        )
                    else:
                        lines.append(f"    {base} ({len(variants)} variants)")
                        for params, result in variants:
                            lines.append(
                                f"      {params}  status={result.status}  bundle={result.bundle}"
                                f"  date={result.last_executed}"
                            )
            lines.append("")

        if report.passed:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("PASSED TESTS:")
            lines.append("-" * TERMINAL_WIDTH)
            for team, team_items in _group_results_by_team(items=report.passed):
                lines.append(f"  ── {team} ({len(team_items)}) ──")
                for base, variants in _group_results_by_base(items=team_items):
                    if len(variants) == 1 and not variants[0][0]:
                        result = variants[0][1]
                        lines.append(
                            f"    {base}  bundle={result.bundle}  date={result.last_executed}  source={result.source}"
                        )
                    elif len(variants) == 1:
                        params, result = variants[0]
                        lines.append(
                            f"    {base}{params}  bundle={result.bundle}  date={result.last_executed}"
                            f"  source={result.source}"
                        )
                    else:
                        lines.append(f"    {base} ({len(variants)} variants)")
                        for params, result in variants:
                            lines.append(f"      {params}  bundle={result.bundle}  date={result.last_executed}")
            lines.append("")

        if report.skipped:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("SKIPPED TESTS:")
            lines.append("-" * TERMINAL_WIDTH)
            for team, team_items in _group_results_by_team(items=report.skipped):
                lines.append(f"  ── {team} ({len(team_items)}) ──")
                for base, variants in _group_results_by_base(items=team_items):
                    if len(variants) == 1 and not variants[0][0]:
                        result = variants[0][1]
                        lines.append(
                            f"    {base}  bundle={result.bundle}  date={result.last_executed}  source={result.source}"
                        )
                    elif len(variants) == 1:
                        params, result = variants[0]
                        lines.append(
                            f"    {base}{params}  bundle={result.bundle}  date={result.last_executed}"
                            f"  source={result.source}"
                        )
                    else:
                        lines.append(f"    {base} ({len(variants)} variants)")
                        for params, result in variants:
                            lines.append(f"      {params}  bundle={result.bundle}  date={result.last_executed}")
            lines.append("")

    gate_status = "PASSED" if report.gate_passed else "FAILED"
    lines.append(f"GATE: {gate_status}")
    lines.append(separator)

    return "\n".join(lines)


def format_json_report(
    report: CoverageReport,
    bundle_prefix: str,
    stale_days: int,
    filters: dict[str, Any] | None = None,
) -> str:
    """Generate a JSON report of coverage results.

    Args:
        report: CoverageReport from analyze_coverage.
        bundle_prefix: Bundle version string.
        stale_days: Stale threshold in days.
        filters: Optional dict of active filters.

    Returns:
        JSON-formatted string with all report data.
    """

    def _result_to_dict(node_id: str, result: ItemResult) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "node_id": node_id,
            "rp_name": result.name,
            "status": result.status,
            "last_executed": result.last_executed,
            "bundle": result.bundle,
            "launch_name": result.launch_name,
            "source": result.source,
        }
        if result.defect_type:
            entry["defect_type"] = result.defect_type
        if result.defect_comment:
            entry["defect_comment"] = result.defect_comment
        return entry

    executed_count = len(report.passed) + len(report.failed) + len(report.skipped)
    coverage_pct = (executed_count / report.total_tests * 100) if report.total_tests > 0 else 0.0

    data: dict[str, Any] = {
        "bundle_prefix": bundle_prefix,
        "stale_days": stale_days,
        "filters": filters or {},
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
            "quarantined_count": len(report.quarantined),
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
        "never_executed_automated": sorted(report.never_executed_automated),
        "never_executed_manual": sorted(report.never_executed_manual),
        "quarantined": [
            {"node_id": qt.node_id, "jira": qt.jira, "reason": qt.reason}
            for qt in sorted(report.quarantined, key=lambda q: q.node_id)
        ],
        "gating": {
            "never_executed": sorted(report.gating_never_executed),
            "stale": [
                _result_to_dict(node_id=node_id, result=result)
                for node_id, result in sorted(report.gating_stale, key=lambda entry: entry[0])
            ],
        },
    }

    # Add grouped view for parametrized tests
    def _build_grouped(items: list[tuple[str, ItemResult]]) -> list[dict[str, Any]]:
        grouped: list[dict[str, Any]] = []
        for base, variants in _group_results_by_base(items=items):
            if len(variants) == 1 and not variants[0][0]:
                grouped.append(_result_to_dict(node_id=base, result=variants[0][1]))
            else:
                grouped.append({
                    "base_test": base,
                    "variant_count": len(variants),
                    "variants": [
                        {"params": params, **_result_to_dict(node_id=f"{base}{params}", result=result)}
                        for params, result in variants
                    ],
                })
        return grouped

    data["grouped"] = {
        "passed": _build_grouped(items=report.passed),
        "failed": _build_grouped(items=report.failed),
        "skipped": _build_grouped(items=report.skipped),
        "stale": _build_grouped(items=report.stale),
        "never_executed": [
            {"base_test": base, "variant_count": len(params), "variants": params}
            for base, params in _group_by_base(items=report.never_executed)
        ],
    }

    def _build_team_results(items: list[tuple[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        by_team: dict[str, list[dict[str, Any]]] = {}
        for team, team_items in _group_results_by_team(items=items):
            by_team[team] = [_result_to_dict(node_id=nid, result=res) for nid, res in team_items]
        return by_team

    def _build_team_ids(items: list[str]) -> dict[str, list[str]]:
        by_team: dict[str, list[str]] = {}
        for team, team_ids in _group_ids_by_team(items=items):
            by_team[team] = sorted(team_ids)
        return by_team

    data["by_team"] = {
        "passed": _build_team_results(items=report.passed),
        "failed": _build_team_results(items=report.failed),
        "skipped": _build_team_results(items=report.skipped),
        "stale": _build_team_results(items=report.stale),
        "never_executed": _build_team_ids(items=report.never_executed),
        "never_executed_manual": _build_team_ids(items=report.never_executed_manual),
    }

    return json.dumps(obj=data, indent=2)


_STATUS_BADGE_CSS: dict[str, str] = {
    "PASSED": "badge-passed",
    "FAILED": "badge-failed",
    "NEVER_EXECUTED": "badge-never",
    "STALE": "badge-stale",
    "SKIPPED": "badge-skipped",
    "QUARANTINED": "badge-quarantined",
}

_STATUS_LABELS: dict[str, str] = {
    "PASSED": "PASSED",
    "FAILED": "FAILED",
    "NEVER_EXECUTED": "NEVER EXECUTED",
    "STALE": "STALE",
    "SKIPPED": "SKIPPED",
    "QUARANTINED": "QUARANTINED",
}


def _matrix_primary_section(
    summary: ParametrizedTestSummary,
    gating_ids: set[str] | None = None,
) -> str:
    """Determine which section a matrix test belongs to based on worst status.

    Priority order: gating > failed > stale > never_executed > skipped > passed.

    Args:
        summary: ParametrizedTestSummary with variant statuses.
        gating_ids: Set of gating test node IDs (if any variant is gating, returns "gating").

    Returns:
        Section name: "gating", "failed", "stale", "never_executed", "skipped", or "passed".
    """
    if gating_ids:
        for variant in summary.variants:
            node_id = f"{summary.base_test}{variant.params}"
            if node_id in gating_ids:
                return "gating"
    statuses = {v.status for v in summary.variants}
    if "FAILED" in statuses:
        return "failed"
    if "STALE" in statuses:
        return "stale"
    if "NEVER_EXECUTED" in statuses:
        return "never_executed"
    if "SKIPPED" in statuses:
        return "skipped"
    return "passed"


def _clean_param_display(params: str, strip_suffix: bool = False) -> str:
    """Clean parametrize display: remove ``#`` delimiters, keep all parts.

    Replaces ``#value#`` delimiters with the bare value and joins all
    segments with em-dash separators.  Suffixes after the last ``#..#``
    group are preserved because they may distinguish variants.

    Args:
        params: Raw parameter suffix (e.g., ``[#hostpath-csi-basic#-snap0]``).
        strip_suffix: If True, drop suffix after the last ``#value#`` group.
            Used when all variants share the same suffix (fixture names).

    Returns:
        Cleaned display string (e.g., ``[hostpath-csi-basic \u2014 snap0]``).
    """
    import re  # noqa: PLC0415

    values = re.findall(r"#([^#]+)#", params)
    if not values:
        return params

    display = " \u2014 ".join(values)
    if not strip_suffix:
        # Split on #...# groups — last part is the suffix after all hash values
        segments = re.split(r"#[^#]+#", params.strip("[]"))
        suffix = segments[-1].lstrip("-") if segments else ""
        if suffix:
            display += f" \u2014 {suffix}"
    return f"[{display}]"


_MAX_HORIZONTAL_VARIANTS: int = 10


def _render_annotated_list(summary: ParametrizedTestSummary, esc: Any) -> list[str]:
    """Render a non-2-axis parametrized test as a horizontal 1-row matrix.

    For tests with up to 10 variants, renders a horizontal table with
    cleaned parameter names as column headers and status symbols in the
    row below. Falls back to a vertical badge list for >10 variants.

    Args:
        summary: ParametrizedTestSummary (is_two_axis=False).
        esc: HTML escape function.

    Returns:
        List of HTML strings.
    """
    sorted_variants = sorted(summary.variants, key=lambda v: v.params)
    parts: list[str] = []
    parts.append(f"<div class='param-header'>{esc(s=summary.base_test)} ({len(summary.variants)} variants)</div>")

    # Detect if all variants share the same suffix (fixture name junk)
    import re  # noqa: PLC0415

    suffixes = set()
    for variant in sorted_variants:
        segments = re.split(r"#[^#]+#", variant.params.strip("[]"))
        suffix = segments[-1].lstrip("-") if segments else ""
        suffixes.add(suffix)
    should_strip_suffix = len(suffixes) == 1 and suffixes != {""}

    cleaned_headers = [
        _clean_param_display(params=v.params, strip_suffix=should_strip_suffix).strip("[]") for v in sorted_variants
    ]
    has_duplicates = len(set(cleaned_headers)) < len(cleaned_headers)

    if len(sorted_variants) > _MAX_HORIZONTAL_VARIANTS or has_duplicates:
        return _render_annotated_list_vertical(
            sorted_variants=sorted_variants,
            parts=parts,
            esc=esc,
            strip_suffix=should_strip_suffix,
        )

    # Horizontal 1-row matrix
    parts.append("<table class='matrix-table'>")
    header = "<tr>"
    for variant in sorted_variants:
        display = _clean_param_display(params=variant.params, strip_suffix=should_strip_suffix).strip("[]")
        header += f"<th>{esc(s=display)}</th>"
    header += "</tr>"
    parts.append(header)

    row = "<tr>"
    for variant in sorted_variants:
        css_class = _STATUS_CSS.get(variant.status, "")
        if variant.status == "FAILED" and variant.defect_type:
            abbrev = _DEFECT_ABBREVS.get(variant.defect_type, "\u274c")
            tooltip = esc(s=variant.defect_type)
            if variant.result and variant.result.defect_comment:
                tooltip += f": {esc(s=variant.result.defect_comment[:80])}"
            row += f"<td class='matrix-cell {css_class}' title='{tooltip}'>{abbrev}</td>"
        else:
            symbol = _STATUS_SYMBOLS.get(variant.status, "?")
            row += f"<td class='matrix-cell {css_class}'>{symbol}</td>"
    row += "</tr>"
    parts.append(row)
    parts.append("</table>")
    return parts


def _render_annotated_list_vertical(
    sorted_variants: list[VariantStatus],
    parts: list[str],
    esc: Any,
    strip_suffix: bool = False,
) -> list[str]:
    """Fallback vertical list for parametrized tests with many variants.

    Args:
        sorted_variants: Sorted list of variant statuses.
        parts: Existing HTML parts to append to.
        esc: HTML escape function.
        strip_suffix: If True, strip identical suffixes from display.

    Returns:
        List of HTML strings with param-variant divs.
    """
    parts.append("<div class='param-group'>")
    for variant in sorted_variants:
        badge_cls = _STATUS_BADGE_CSS.get(variant.status, "")
        label = _STATUS_LABELS.get(variant.status, variant.status)
        if variant.status == "FAILED" and variant.defect_type:
            label = f"FAILED ({variant.defect_type})"
        display_params = _clean_param_display(params=variant.params, strip_suffix=strip_suffix)
        parts.append(
            f"<div class='param-variant'>"
            f"<span class='mono'>{esc(s=display_params)}</span>"
            f"<span class='badge {badge_cls}'>{label}</span>"
            f"</div>"
        )
    parts.append("</div>")
    return parts


def _render_html_matrix(summary: ParametrizedTestSummary, esc: Any) -> list[str]:
    """Render a 2-axis parametrized test as an HTML matrix table.

    Args:
        summary: ParametrizedTestSummary with is_two_axis=True.
        esc: HTML escape function.

    Returns:
        List of HTML strings forming the matrix table.
    """
    parts: list[str] = []
    parts.append(
        f"<div class='mono' style='margin: 0.5rem 0;'><b>{esc(summary.base_test)}</b>"
        f" ({len(summary.variants)} variants)</div>"
    )

    # Build lookup: (axis1, axis2) -> VariantStatus
    variant_map: dict[tuple[str, str], VariantStatus] = {}
    for variant in summary.variants:
        parsed = _parse_two_axis_params(params=variant.params)
        if not parsed:
            parsed = _parse_hash_suffix_params(params=variant.params)
        if parsed:
            variant_map[parsed] = variant

    parts.append("<table class='matrix-table'>")
    # Header row
    header = "<tr><th></th>"
    for col in summary.axis2_values:
        header += f"<th>{esc(s=col)}</th>"
    header += "</tr>"
    parts.append(header)

    # Data rows
    for row_val in summary.axis1_values:
        row = f"<tr><th>{esc(s=row_val)}</th>"
        for col_val in summary.axis2_values:
            cell_variant = variant_map.get((row_val, col_val))
            if cell_variant:
                css_class = _STATUS_CSS.get(cell_variant.status, "")
                if cell_variant.status == "FAILED" and cell_variant.defect_type:
                    abbrev = _DEFECT_ABBREVS.get(cell_variant.defect_type, "❌")
                    tooltip = esc(s=cell_variant.defect_type)
                    if cell_variant.result and cell_variant.result.defect_comment:
                        tooltip += f": {esc(s=cell_variant.result.defect_comment[:80])}"
                    row += f"<td class='matrix-cell {css_class}' title='{tooltip}'>{abbrev}</td>"
                else:
                    symbol = _STATUS_SYMBOLS.get(cell_variant.status, "?")
                    row += f"<td class='matrix-cell {css_class}'>{symbol}</td>"
            else:
                row += f"<td class='matrix-cell status-never'>{_STATUS_SYMBOLS['NEVER_EXECUTED']}</td>"
        row += "</tr>"
        parts.append(row)

    parts.append("</table>")
    return parts


def format_html_report(
    report: CoverageReport,
    bundle_prefix: str,
    stale_days: int,
    filters: dict[str, Any] | None = None,
) -> str:
    """Generate a self-contained HTML report with tabbed per-team layout.

    Produces a Summary tab with overall stats and per-team table, plus
    one tab per team showing that team's sections (gating, failed, manual,
    never-executed, stale, passed, skipped).

    Args:
        report: CoverageReport from analyze_coverage.
        bundle_prefix: Bundle version string.
        stale_days: Stale threshold in days.
        filters: Optional dict of active filters.

    Returns:
        Complete HTML document as a string.
    """
    esc = html_mod.escape
    generated_at = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    executed_count = len(report.passed) + len(report.failed) + len(report.skipped)
    coverage_pct = (executed_count / report.total_tests * 100) if report.total_tests > 0 else 0.0
    gate_cls = "badge-pass" if report.gate_passed else "badge-fail"
    gate_label = "PASSED" if report.gate_passed else "FAILED"

    def _result_row(node_id: str, result: ItemResult, extra_col: str = "") -> str:
        date = esc(result.last_executed[:10]) if result.last_executed else ""
        return (
            f"<tr><td class='mono'>{esc(node_id)}</td>"
            f"<td>{esc(result.bundle)}</td>"
            f"<td>{date}</td>"
            f"<td>{esc(result.source)}</td>"
            f"{extra_col}</tr>"
        )

    # Collect all team names sorted
    all_teams = sorted((report.team_stats or {}).keys())

    # ── CSS ──
    css = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 2rem; color: #333; background: #fafafa; }
h1 { margin-bottom: 0.3rem; }
.subtitle { color: #666; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9rem; }
th { background: #f0f0f0; font-weight: 600; }
tr:nth-child(even) { background: #f9f9f9; }
.mono { font-family: 'SF Mono', Menlo, Monaco, monospace; font-size: 0.85rem; }
.summary-table { width: auto; min-width: 400px; }
.summary-table td:last-child { text-align: right; font-weight: 600; }
details { margin-bottom: 1rem; }
summary { cursor: pointer; font-weight: 600; font-size: 1.1rem; padding: 8px 12px;
           border-radius: 4px; margin-bottom: 0.3rem; }
summary:hover { opacity: 0.85; }
.section-gating summary { background: #fff3cd; color: #856404; }
.section-failed summary { background: #f8d7da; color: #842029; }
.section-manual summary { background: #ffe0b2; color: #7c4d0f; }
.section-never summary { background: #e2e3e5; color: #41464b; }
.section-stale summary { background: #e2e3e5; color: #41464b; }
.section-passed summary { background: #d1e7dd; color: #0f5132; }
.section-skipped summary { background: #cff4fc; color: #055160; }
.section-quarantined summary { background: #e8d5f5; color: #5b2d8e; }
.section-desc { font-weight: normal; color: #666; font-size: 0.85em; }
.matrix-table { border-collapse: collapse; margin: 0.5rem 0 1rem 1.5rem; }
.matrix-table th, .matrix-table td { border: 1px solid #ddd; padding: 4px 8px; text-align: center; }
.matrix-table th { background: #f5f5f5; font-size: 0.85em; }
.matrix-cell { font-size: 0.85em; min-width: 60px; padding: 4px 6px; }
.legend { margin: 1rem 0; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; background: #fafafa; }
.legend summary { cursor: pointer; }
.legend th { text-align: left; padding: 2px 8px; }
.legend table { border-collapse: collapse; }
.legend td { padding: 2px 8px; }
.status-passed { background: #d4edda; }
.status-failed { background: #f8d7da; }
.status-never { background: #e9ecef; }
.status-stale { background: #fff3cd; }
.status-skipped { background: #cff4fc; }
.status-quarantined { background: #e8daef; }
.badge { padding: 1px 6px; border-radius: 3px; font-size: 0.8em; font-weight: 600; }
.badge-passed { background: #d4edda; color: #155724; }
.badge-failed { background: #f8d7da; color: #721c24; }
.badge-never { background: #e9ecef; color: #495057; }
.badge-stale { background: #fff3cd; color: #856404; }
.badge-skipped { background: #cff4fc; color: #055160; }
.badge-quarantined { background: #e8daef; color: #6c3483; }
.param-group { margin: 0.5rem 0 0.8rem 0; border-left: 3px solid #ddd; padding-left: 0.8rem; }
.param-header { font-weight: 700; font-family: monospace; font-size: 0.9em; margin-bottom: 0.3rem; }
.param-variant { display: flex; justify-content: space-between; align-items: center;
                 padding: 2px 0; font-size: 0.85em; max-width: 900px; }
.param-variant .mono { font-family: monospace; overflow: hidden; text-overflow: ellipsis; }
.badge { display: inline-block; padding: 6px 18px; border-radius: 4px;
         font-weight: bold; font-size: 1.2rem; margin: 0.5rem 0 1.5rem; }
.badge-pass { background: #198754; color: white; }
.badge-fail { background: #dc3545; color: white; }
.defect-group { font-weight: 600; padding: 4px 0; margin-top: 0.5rem; }
.footer { color: #999; font-size: 0.8rem; margin-top: 2rem; border-top: 1px solid #ddd; padding-top: 0.5rem; }
.team-header { font-weight: 600; color: #444; padding: 6px 0 2px; margin-top: 0.8rem; border-bottom: 1px solid #e0e0e0; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; border-bottom: 2px solid #ddd; margin-bottom: 1rem; }
.tab-btn { padding: 8px 16px; border: 1px solid #ddd; border-bottom: none; border-radius: 4px 4px 0 0;
           background: #f0f0f0; cursor: pointer; font-size: 0.9rem; font-weight: 500; }
.tab-btn:hover { background: #e0e0e0; }
.tab-btn.active { background: white; border-bottom: 2px solid white; margin-bottom: -2px; font-weight: 700; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.team-summary-table { width: 100%; margin-bottom: 1.5rem; }
.team-summary-table td:not(:first-child) { text-align: right; }
.team-summary-table tr.total-row { font-weight: 700; border-top: 2px solid #333; }
.team-bar { font-size: 1rem; color: #555; margin-bottom: 1rem; padding: 8px 12px; background: #f0f0f0; border-radius: 4px; }
"""

    js = """
function openTab(evt, tabName) {
  document.querySelectorAll('.tab-content').forEach(function(t) { t.classList.remove('active'); });
  document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
  document.getElementById(tabName).classList.add('active');
  evt.currentTarget.classList.add('active');
  document.getElementById(tabName).querySelectorAll('details').forEach(function(d) { d.removeAttribute('open'); });
}
"""

    parts: list[str] = []
    parts.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    parts.append(f"<title>Coverage Gate — {esc(bundle_prefix)}</title>")
    parts.append(f"<style>{css}</style>")
    parts.append(f"<script>{js}</script></head><body>")
    parts.append(f"<h1>Test Coverage Gate — {esc(bundle_prefix)}</h1>")
    subtitle_parts = [f"Bundle: {esc(bundle_prefix)}"]
    if filters:
        if filters.get("team"):
            subtitle_parts.append(f"Team: {esc(filters['team'])}")
        if filters.get("exclude_teams"):
            subtitle_parts.append(f"Excluded: {esc(', '.join(filters['exclude_teams']))}")
        if filters.get("max_launches", 0) != 0:
            subtitle_parts.append(f"Max launches: {filters['max_launches']}")
        if str(filters.get("tests_dir", "tests")) != "tests":
            subtitle_parts.append(f"Tests dir: {esc(str(filters['tests_dir']))}")
    subtitle_parts.append(f"Stale: {stale_days} days")
    subtitle_parts.append(f"Generated: {generated_at}")
    parts.append(f"<div class='subtitle'>{'  ·  '.join(subtitle_parts)}</div>")

    # Gate badge
    parts.append(f"<div class='badge {gate_cls}'>GATE: {gate_label}</div>")

    # Tab buttons
    parts.append("<div class='tabs'>")
    parts.append("<button class='tab-btn active' onclick='openTab(event, \"summary\")'>Summary</button>")
    for team in all_teams:
        team_total = (report.team_stats or {}).get(team)
        count_label = f" ({team_total.total})" if team_total else ""
        parts.append(
            f"<button class='tab-btn' onclick='openTab(event, \"{esc(team)}\")'>{esc(team)}{count_label}</button>"
        )
    parts.append("</div>")

    # Legend (always visible, outside tabs)
    parts.append("<div class='legend'>")
    parts.append("<details>")
    parts.append("<summary><strong>Legend</strong></summary>")
    parts.append("<table>")
    parts.append("<tr><th colspan='2'>Status Icons</th></tr>")
    parts.append(
        "<tr><td class='matrix-cell status-passed'>\u2705</td>"
        "<td>Passed \u2014 test passed in most recent run</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell status-failed'>\u274c</td>"
        "<td>Failed \u2014 test failed, no defect classification in ReportPortal</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell status-never'>\u2014</td>"
        "<td>Never Executed \u2014 no results found in ReportPortal for this bundle</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell status-stale'>\u26a0\ufe0f</td>"
        "<td>Stale \u2014 last execution is older than the stale threshold</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell'>SKIP</td>"
        "<td>Skipped \u2014 test was skipped (not quarantined) in most recent run</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell status-quarantined'>Q</td>"
        "<td>Quarantined \u2014 intentionally disabled due to known bug or automation issue</td></tr>"
    )
    parts.append("<tr><th colspan='2'>Defect Classifications (shown in matrix cells for failed tests)</th></tr>")
    parts.append(
        "<tr><td class='matrix-cell status-failed'>Product Bug</td><td>Confirmed defect in the product</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell status-failed'>Auto Bug</td><td>Test code issue, not a product defect</td></tr>"
    )
    parts.append(
        "<tr><td class='matrix-cell status-failed'>Sys Issue</td><td>Environment or infrastructure problem</td></tr>"
    )
    parts.append("<tr><td class='matrix-cell status-failed'>To Invest.</td><td>Failure not yet analyzed</td></tr>")
    parts.append(
        "<tr><td class='matrix-cell status-failed'>No Defect</td><td>False alarm or expected behavior</td></tr>"
    )
    parts.append("</table>")
    parts.append("</details>")
    parts.append("</div>")

    # ==================== SUMMARY TAB ====================
    parts.append("<div id='summary' class='tab-content active'>")

    # Overall summary table
    parts.append("<h2>Overall Summary</h2>")
    parts.append("<table class='summary-table'>")
    parts.append(f"<tr><td>Total tests in repo</td><td>{report.total_tests:,}</td></tr>")
    parts.append(f"<tr><td>  Automated</td><td>{report.automated_count:,}</td></tr>")
    parts.append(f"<tr><td>  Unautomated (STD)</td><td>{report.unautomated_count:,}</td></tr>")
    parts.append(f"<tr><td>Executed in RP</td><td>{executed_count:,}</td></tr>")
    parts.append(f"<tr><td>  Passed</td><td>{len(report.passed):,}</td></tr>")
    parts.append(f"<tr><td>  Failed</td><td>{len(report.failed):,}</td></tr>")
    parts.append(f"<tr><td>  Skipped</td><td>{len(report.skipped):,}</td></tr>")
    parts.append(f"<tr><td>  Stale (&gt;{stale_days}d)</td><td>{len(report.stale):,}</td></tr>")
    parts.append(f"<tr><td>Never executed</td><td>{len(report.never_executed):,}</td></tr>")
    parts.append(f"<tr><td>Quarantined</td><td>{len(report.quarantined):,}</td></tr>")
    parts.append(f"<tr><td>Coverage</td><td>{coverage_pct:.1f}%</td></tr>")
    parts.append("</table>")

    # Per-team breakdown table
    if report.team_stats:
        parts.append("<h2>Per-Team Breakdown</h2>")
        parts.append("<table class='team-summary-table'>")
        parts.append(
            "<tr><th>Team</th><th>Total</th><th>Passed</th><th>Failed</th><th>Quarantined</th>"
            "<th>Never Executed</th><th>Stale</th><th>Coverage</th></tr>"
        )
        for team in all_teams:
            stats = report.team_stats[team]
            parts.append(
                f"<tr><td>{esc(team)}</td><td>{stats.total:,}</td><td>{stats.passed:,}</td>"
                f"<td>{stats.failed:,}</td><td>{stats.quarantined:,}</td><td>{stats.never_executed:,}</td>"
                f"<td>{stats.stale:,}</td><td>{stats.coverage_pct:.1f}%</td></tr>"
            )
        parts.append(
            f"<tr class='total-row'><td>TOTAL</td><td>{report.total_tests:,}</td>"
            f"<td>{len(report.passed):,}</td><td>{len(report.failed):,}</td><td>{len(report.quarantined):,}</td>"
            f"<td>{len(report.never_executed):,}</td><td>{len(report.stale):,}</td>"
            f"<td>{coverage_pct:.1f}%</td></tr>"
        )
        parts.append("</table>")

    parts.append("</div>")  # end summary tab

    # ==================== PER-TEAM TABS ====================
    # Pre-group data by team for efficient tab rendering
    failed_by_team: dict[str, list[tuple[str, ItemResult]]] = {}
    for node_id, result in report.failed:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        failed_by_team.setdefault(team, []).append((node_id, result))

    passed_by_team: dict[str, list[tuple[str, ItemResult]]] = {}
    for node_id, result in report.passed:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        passed_by_team.setdefault(team, []).append((node_id, result))

    skipped_by_team: dict[str, list[tuple[str, ItemResult]]] = {}
    for node_id, result in report.skipped:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        skipped_by_team.setdefault(team, []).append((node_id, result))

    stale_by_team: dict[str, list[tuple[str, ItemResult]]] = {}
    for node_id, result in report.stale:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        stale_by_team.setdefault(team, []).append((node_id, result))

    never_by_team: dict[str, list[str]] = {}
    for node_id in report.never_executed:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        never_by_team.setdefault(team, []).append(node_id)

    manual_by_team: dict[str, list[str]] = {}
    for node_id in report.never_executed_manual:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        manual_by_team.setdefault(team, []).append(node_id)

    quarantine_by_team: dict[str, list[QuarantinedTest]] = {}
    for qt in report.quarantined:
        team = _get_team_from_node_id(node_id=qt.node_id) or "other"
        quarantine_by_team.setdefault(team, []).append(qt)

    # Pre-compute parametrized summaries by team
    param_summaries_by_team = report.parametrized_summaries or {}

    gating_ne_set = set(report.gating_never_executed)
    gating_stale_map = dict(report.gating_stale)
    all_gating_ids = list(report.gating_never_executed) + [nid for nid, _ in report.gating_stale]
    gating_by_team: dict[str, list[str]] = {}
    for node_id in all_gating_ids:
        team = _get_team_from_node_id(node_id=node_id) or "other"
        gating_by_team.setdefault(team, []).append(node_id)

    manual_set = set(report.never_executed_manual)

    for team in all_teams:
        team_stat = (report.team_stats or {}).get(team)
        team_summaries = param_summaries_by_team.get(team, [])
        # Map each 2-axis matrix test to its primary section and collect all matrix bases
        param_bases: set[str] = set()
        param_owners: dict[str, str] = {}
        team_gating_set = set(gating_by_team.get(team, []))
        for summary in team_summaries:
            param_bases.add(summary.base_test)
            param_owners[summary.base_test] = _matrix_primary_section(
                summary=summary,
                gating_ids=team_gating_set or None,
            )

        parts.append(f"<div id='{esc(team)}' class='tab-content'>")

        # Team summary bar
        if team_stat:
            parts.append(
                f"<div class='team-bar'><b>{esc(team)}</b> — "
                f"{team_stat.total:,} tests, {team_stat.coverage_pct:.1f}% coverage, "
                f"{team_stat.failed:,} failed, {team_stat.never_executed:,} never executed</div>"
            )

        # GATING section for this team
        team_gating = gating_by_team.get(team, [])
        if team_gating:
            parts.append("<details open class='section-gating'>")
            parts.append(
                f"<summary>⚠ GATING ({len(team_gating)}) <small class='section-desc'>— Tests marked as gating with no results or stale</small></summary>"
            )
            parts.append("<table><tr><th>Test</th><th>Status</th></tr>")
            for base, params_list in _group_by_base(items=team_gating):
                if base in param_bases:
                    continue
                if len(params_list) == 1 and not params_list[0]:
                    full_id = base
                    if full_id in gating_ne_set:
                        parts.append(f"<tr><td class='mono'>{esc(full_id)}</td><td>NEVER EXECUTED</td></tr>")
                    else:
                        stale_r = gating_stale_map[full_id]
                        date_str = stale_r.last_executed[:10] if stale_r.last_executed else "unknown"
                        parts.append(f"<tr><td class='mono'>{esc(full_id)}</td><td>STALE: {esc(date_str)}</td></tr>")
                elif len(params_list) == 1:
                    full_id = f"{base}{params_list[0]}"
                    if full_id in gating_ne_set:
                        parts.append(f"<tr><td class='mono'>{esc(full_id)}</td><td>NEVER EXECUTED</td></tr>")
                    else:
                        stale_r = gating_stale_map[full_id]
                        date_str = stale_r.last_executed[:10] if stale_r.last_executed else "unknown"
                        parts.append(f"<tr><td class='mono'>{esc(full_id)}</td><td>STALE: {esc(date_str)}</td></tr>")
                else:
                    parts.append(
                        f"<tr><td class='mono' colspan='2'><b>{esc(base)}</b> ({len(params_list)} variants)</td></tr>"
                    )
                    for params in params_list:
                        full_id = f"{base}{params}"
                        if full_id in gating_ne_set:
                            parts.append(f"<tr><td class='mono'>  {esc(params)}</td><td>NEVER EXECUTED</td></tr>")
                        else:
                            stale_r = gating_stale_map[full_id]
                            date_str = stale_r.last_executed[:10] if stale_r.last_executed else "unknown"
                            parts.append(
                                f"<tr><td class='mono'>  {esc(params)}</td><td>STALE: {esc(date_str)}</td></tr>"
                            )
            parts.append("</table>")
            for summary in team_summaries:
                if param_owners.get(summary.base_test) == "gating":
                    if summary.is_two_axis:
                        parts.extend(_render_html_matrix(summary=summary, esc=esc))
                    else:
                        parts.extend(_render_annotated_list(summary=summary, esc=esc))
            parts.append("</details>")

        # FAILED section for this team
        team_failed = failed_by_team.get(team, [])

        # Pre-compute failed variants from tests owned by other sections
        cross_section_failed: list[tuple[str, ItemResult]] = []
        for summary in team_summaries:
            owner = param_owners.get(summary.base_test)
            if owner and owner != "failed":
                for variant in summary.variants:
                    if variant.status == "FAILED" and variant.result:
                        node_id = f"{summary.base_test}{variant.params}"
                        cross_section_failed.append((node_id, variant.result))

        if team_failed or cross_section_failed:
            parts.append("<details open class='section-failed'>")
            parts.append(
                f"<summary>FAILED TESTS ({len(team_failed)}) <small class='section-desc'>— Tests whose most recent result across all launches is FAILED</small></summary>"
            )

            defect_groups: dict[str, list[tuple[str, ItemResult]]] = {}
            for node_id, result in sorted(team_failed, key=lambda entry: entry[0]):
                group_key = result.defect_type or "Unclassified"
                defect_groups.setdefault(group_key, []).append((node_id, result))

            display_order = [
                "Product Bug",
                "Automation Bug",
                "System Issue",
                "To Investigate",
                "No Defect",
                "Not Issue",
            ]
            sorted_groups: list[tuple[str, list[tuple[str, ItemResult]]]] = []
            remaining = dict(defect_groups)
            for group_name in display_order:
                if group_name in remaining:
                    sorted_groups.append((group_name, remaining.pop(group_name)))
            for group_name in sorted(remaining):
                sorted_groups.append((group_name, remaining[group_name]))

            for group_name, group_items in sorted_groups:
                parts.append(f"<div class='defect-group'>{esc(group_name)} ({len(group_items)}):</div>")
                parts.append(
                    "<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th><th>Defect</th><th>Comment</th></tr>"
                )
                for node_id, result in group_items:
                    base, _ = _split_params(node_id=node_id)
                    if base in param_bases:
                        continue
                    raw_comment = result.defect_comment or ""
                    defect_cell = f"<td>{html_mod.escape(s=result.defect_type or '')}</td>"
                    comment = html_mod.escape(s=raw_comment)
                    parts.append(
                        _result_row(node_id=node_id, result=result, extra_col=f"{defect_cell}<td>{comment}</td>")
                    )
                parts.append("</table>")
            # Render full matrices whose primary section is "failed"
            for summary in team_summaries:
                if param_owners.get(summary.base_test) == "failed":
                    if summary.is_two_axis:
                        parts.extend(_render_html_matrix(summary=summary, esc=esc))
                    else:
                        parts.extend(_render_annotated_list(summary=summary, esc=esc))
            if cross_section_failed:
                parts.append("<div class='defect-group'>Additional failed variants:</div>")
                parts.append(
                    "<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th><th>Defect</th><th>Comment</th></tr>"
                )
                for node_id, result in sorted(cross_section_failed, key=lambda e: e[0]):
                    defect_cell = f"<td>{html_mod.escape(s=result.defect_type or '')}</td>"
                    comment_cell = f"<td>{html_mod.escape(s=(result.defect_comment or '')[:200])}</td>"
                    parts.append(_result_row(node_id=node_id, result=result, extra_col=f"{defect_cell}{comment_cell}"))
                parts.append("</table>")
            parts.append("</details>")

        # QUARANTINED section for this team
        team_quarantine = quarantine_by_team.get(team, [])
        if team_quarantine:
            parts.append("<details class='section-quarantined'>")
            parts.append(
                f"<summary>⏸ QUARANTINED ({len(team_quarantine)})"
                " <small class='section-desc'>— Tests intentionally skipped"
                " due to known bugs or automation issues</small></summary>"
            )
            parts.append("<table><tr><th>Test</th><th>Jira</th><th>Reason</th></tr>")
            for qt in sorted(team_quarantine, key=lambda q: q.node_id):
                jira_cell = ""
                if qt.jira:
                    jira_url = f"https://issues.redhat.com/browse/{esc(qt.jira)}"
                    jira_cell = f"<a href='{jira_url}'>{esc(qt.jira)}</a>"
                parts.append(
                    f"<tr><td class='mono'>{esc(qt.node_id)}</td>"
                    f"<td>{jira_cell}</td>"
                    f"<td>{esc(qt.reason[:120])}</td></tr>"
                )
            parts.append("</table></details>")

        # MANUAL section for this team
        team_manual = manual_by_team.get(team, [])
        if team_manual:
            parts.append("<details open class='section-manual'>")
            parts.append(
                f"<summary>MANUAL TESTS ({len(team_manual)}) <small class='section-desc'>— Unimplemented test designs (__test__ = False) with no results in RP</small></summary>"
            )
            parts.append("<table><tr><th>Test</th></tr>")
            for base, params_list in _group_by_base(items=team_manual):
                if len(params_list) == 1 and not params_list[0]:
                    parts.append(f"<tr><td class='mono'>{esc(base)}</td></tr>")
                elif len(params_list) == 1:
                    parts.append(f"<tr><td class='mono'>{esc(base)}{esc(params_list[0])}</td></tr>")
                else:
                    parts.append(f"<tr><td class='mono'><b>{esc(base)}</b> ({len(params_list)} variants)</td></tr>")
                    for params in params_list:
                        parts.append(f"<tr><td class='mono'>  {esc(params)}</td></tr>")
            parts.append("</table></details>")

        # NEVER EXECUTED section for this team
        team_never = never_by_team.get(team, [])
        if team_never:
            parts.append("<details class='section-never'>")
            parts.append(
                f"<summary>NEVER EXECUTED ({len(team_never)}) <small class='section-desc'>— Implemented tests with no results in RP for this bundle</small></summary>"
            )
            parts.append("<table><tr><th>Test</th><th>Type</th></tr>")
            for base, params_list in _group_by_base(items=team_never):
                if base in param_bases:
                    continue
                if len(params_list) == 1 and not params_list[0]:
                    label = "Manual" if base in manual_set else "Automated"
                    parts.append(f"<tr><td class='mono'>{esc(base)}</td><td>{label}</td></tr>")
                elif len(params_list) == 1:
                    full_id = f"{base}{params_list[0]}"
                    label = "Manual" if full_id in manual_set else "Automated"
                    parts.append(f"<tr><td class='mono'>{esc(full_id)}</td><td>{label}</td></tr>")
                else:
                    parts.append(
                        f"<tr><td class='mono' colspan='2'><b>{esc(base)}</b> ({len(params_list)} variants)</td></tr>"
                    )
                    for params in params_list:
                        full_id = f"{base}{params}"
                        label = "Manual" if full_id in manual_set else "Automated"
                        parts.append(f"<tr><td class='mono'>  {esc(params)}</td><td>{label}</td></tr>")
            parts.append("</table>")
            # Render full matrices whose primary section is "never_executed"
            for summary in team_summaries:
                if param_owners.get(summary.base_test) == "never_executed":
                    if summary.is_two_axis:
                        parts.extend(_render_html_matrix(summary=summary, esc=esc))
                    else:
                        parts.extend(_render_annotated_list(summary=summary, esc=esc))
            parts.append("</details>")

        # STALE section for this team
        team_stale = stale_by_team.get(team, [])
        if team_stale:
            parts.append("<details class='section-stale'>")
            parts.append(
                f"<summary>STALE TESTS ({len(team_stale)}) <small class='section-desc'>— Last execution older than the stale threshold</small></summary>"
            )
            parts.append("<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th></tr>")
            for base, variants in _group_results_by_base(items=team_stale):
                if base in param_bases:
                    continue
                if len(variants) == 1 and not variants[0][0]:
                    parts.append(_result_row(node_id=base, result=variants[0][1]))
                elif len(variants) == 1:
                    parts.append(_result_row(node_id=f"{base}{variants[0][0]}", result=variants[0][1]))
                else:
                    parts.append(
                        f"<tr><td class='mono' colspan='4'><b>{esc(base)}</b> ({len(variants)} variants)</td></tr>"
                    )
                    for params, result in variants:
                        parts.append(_result_row(node_id=f"  {esc(params)}", result=result))
            # Render full matrices whose primary section is "stale"
            for summary in team_summaries:
                if param_owners.get(summary.base_test) == "stale":
                    if summary.is_two_axis:
                        parts.extend(_render_html_matrix(summary=summary, esc=esc))
                    else:
                        parts.extend(_render_annotated_list(summary=summary, esc=esc))
            parts.append("</table></details>")

        # PASSED section for this team
        team_passed = passed_by_team.get(team, [])
        if team_passed:
            parts.append("<details class='section-passed'>")
            parts.append(
                f"<summary>PASSED TESTS ({len(team_passed)}) <small class='section-desc'>— Tests whose most recent result across all launches is PASSED</small></summary>"
            )
            parts.append("<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th></tr>")
            for base, variants in _group_results_by_base(items=team_passed):
                if base in param_bases:
                    continue
                if len(variants) == 1 and not variants[0][0]:
                    parts.append(_result_row(node_id=base, result=variants[0][1]))
                elif len(variants) == 1:
                    parts.append(_result_row(node_id=f"{base}{variants[0][0]}", result=variants[0][1]))
                else:
                    parts.append(
                        f"<tr><td class='mono' colspan='4'><b>{esc(base)}</b> ({len(variants)} variants)</td></tr>"
                    )
                    for params, result in variants:
                        parts.append(_result_row(node_id=f"  {esc(params)}", result=result))
            parts.append("</table>")
            # Render full matrices whose primary section is "passed"
            for summary in team_summaries:
                if param_owners.get(summary.base_test) == "passed":
                    if summary.is_two_axis:
                        parts.extend(_render_html_matrix(summary=summary, esc=esc))
                    else:
                        parts.extend(_render_annotated_list(summary=summary, esc=esc))
            parts.append("</details>")

        # SKIPPED section for this team
        team_skipped = skipped_by_team.get(team, [])
        if team_skipped:
            parts.append("<details class='section-skipped'>")
            parts.append(
                f"<summary>SKIPPED TESTS ({len(team_skipped)}) <small class='section-desc'>— Tests whose most recent result across all launches is SKIPPED</small></summary>"
            )
            parts.append("<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th></tr>")
            for base, variants in _group_results_by_base(items=team_skipped):
                if base in param_bases:
                    continue
                if len(variants) == 1 and not variants[0][0]:
                    parts.append(_result_row(node_id=base, result=variants[0][1]))
                elif len(variants) == 1:
                    parts.append(_result_row(node_id=f"{base}{variants[0][0]}", result=variants[0][1]))
                else:
                    parts.append(
                        f"<tr><td class='mono' colspan='4'><b>{esc(base)}</b> ({len(variants)} variants)</td></tr>"
                    )
                    for params, result in variants:
                        parts.append(_result_row(node_id=f"  {esc(params)}", result=result))
            # Render full matrices whose primary section is "skipped"
            for summary in team_summaries:
                if param_owners.get(summary.base_test) == "skipped":
                    if summary.is_two_axis:
                        parts.extend(_render_html_matrix(summary=summary, esc=esc))
                    else:
                        parts.extend(_render_annotated_list(summary=summary, esc=esc))
            parts.append("</table></details>")

        parts.append("</div>")  # end team tab

    parts.append(f"<div class='footer'>Generated by rp_coverage_gate · {generated_at}</div>")
    parts.append("</body></html>")

    return "\n".join(parts)
