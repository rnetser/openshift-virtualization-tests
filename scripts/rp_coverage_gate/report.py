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
    never_executed_automated: list[str]
    never_executed_manual: list[str]
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
    never_executed_automated: list[str] = []
    never_executed_manual: list[str] = []
    stale: list[tuple[str, ItemResult]] = []

    unautomated_id_set = set(unautomated_ids)

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
    lines.append(f"  Automated:             {len(report.never_executed_automated):,}")
    lines.append(f"  Manual (STD):          {len(report.never_executed_manual):,}")
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
            for node_id, result in group_items:
                comment = ""
                if result.defect_comment:
                    truncated = result.defect_comment[:max_comment_len]
                    if len(result.defect_comment) > max_comment_len:
                        truncated += "..."
                    comment = f"  [{truncated}]"
                lines.append(f"    {node_id}  bundle={result.bundle}{comment}")
        lines.append("")

    if report.never_executed_manual:
        lines.append("-" * TERMINAL_WIDTH)
        lines.append(f"MANUAL TESTS \u2014 never executed ({len(report.never_executed_manual)}):")
        lines.append("-" * TERMINAL_WIDTH)
        for node_id in sorted(report.never_executed_manual):
            lines.append(f"  {node_id}")
        lines.append("")

    if full:
        if report.never_executed:
            lines.append("-" * TERMINAL_WIDTH)
            lines.append("NEVER EXECUTED:")
            lines.append("-" * TERMINAL_WIDTH)
            for node_id in sorted(report.never_executed):
                label = " [MANUAL]" if node_id in set(report.never_executed_manual) else ""
                lines.append(f"  {node_id}{label}")
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
        entry: dict[str, Any] = {
            "node_id": node_id,
            "rp_name": result.name,
            "status": result.status,
            "last_executed": result.last_executed,
            "bundle": result.bundle,
            "launch_name": result.launch_name,
            "polarion_id": result.polarion_id,
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
        "never_executed_automated": sorted(report.never_executed_automated),
        "never_executed_manual": sorted(report.never_executed_manual),
        "gating": {
            "never_executed": sorted(report.gating_never_executed),
            "stale": [
                _result_to_dict(node_id=node_id, result=result)
                for node_id, result in sorted(report.gating_stale, key=lambda entry: entry[0])
            ],
        },
    }

    return json.dumps(obj=data, indent=2)


def format_html_report(
    report: CoverageReport,
    bundle_prefix: str,
    stale_days: int,
) -> str:
    """Generate a self-contained HTML report of coverage results.

    Args:
        report: CoverageReport from analyze_coverage.
        bundle_prefix: Bundle version string.
        stale_days: Stale threshold in days.

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
        polarion = esc(result.polarion_id) if result.polarion_id else ""
        date = esc(result.last_executed[:10]) if result.last_executed else ""
        return (
            f"<tr><td class='mono'>{esc(node_id)}</td>"
            f"<td>{esc(result.bundle)}</td>"
            f"<td>{date}</td>"
            f"<td>{esc(result.source)}</td>"
            f"<td>{polarion}</td>"
            f"{extra_col}</tr>"
        )

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
.badge { display: inline-block; padding: 6px 18px; border-radius: 4px;
         font-weight: bold; font-size: 1.2rem; margin: 0.5rem 0 1.5rem; }
.badge-pass { background: #198754; color: white; }
.badge-fail { background: #dc3545; color: white; }
.defect-group { font-weight: 600; padding: 4px 0; margin-top: 0.5rem; }
.footer { color: #999; font-size: 0.8rem; margin-top: 2rem; border-top: 1px solid #ddd; padding-top: 0.5rem; }
"""

    parts: list[str] = []
    parts.append("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>")
    parts.append(f"<title>Coverage Gate — {esc(bundle_prefix)}</title>")
    parts.append(f"<style>{css}</style></head><body>")
    parts.append(f"<h1>Test Coverage Gate — {esc(bundle_prefix)}</h1>")
    parts.append(f"<div class='subtitle'>Stale threshold: {stale_days} days · Generated: {generated_at}</div>")

    # ── Gate badge ──
    parts.append(f"<div class='badge {gate_cls}'>GATE: {gate_label}</div>")

    # ── Summary table ──
    parts.append("<table class='summary-table'>")
    parts.append(f"<tr><td>Total tests in repo</td><td>{report.total_tests:,}</td></tr>")
    parts.append(f"<tr><td>  Automated</td><td>{report.automated_count:,}</td></tr>")
    parts.append(f"<tr><td>  Unautomated (STD)</td><td>{report.unautomated_count:,}</td></tr>")
    parts.append(f"<tr><td>Executed in RP</td><td>{executed_count:,}</td></tr>")
    parts.append(f"<tr><td>  Passed</td><td>{len(report.passed):,}</td></tr>")
    parts.append(f"<tr><td>  Failed</td><td>{len(report.failed):,}</td></tr>")
    parts.append(f"<tr><td>  Skipped</td><td>{len(report.skipped):,}</td></tr>")
    parts.append(f"<tr><td>  Stale (&gt;{stale_days}d)</td><td>{len(report.stale):,}</td></tr>")
    parts.append(f"<tr><td>Never executed</td><td>{len(report.never_executed):,}</td></tr>")
    parts.append(f"<tr><td>  Automated</td><td>{len(report.never_executed_automated):,}</td></tr>")
    parts.append(f"<tr><td>  Manual (STD)</td><td>{len(report.never_executed_manual):,}</td></tr>")
    parts.append(f"<tr><td>Coverage</td><td>{coverage_pct:.1f}%</td></tr>")
    parts.append("</table>")

    # ── GATING section ──
    gating_gap_count = len(report.gating_never_executed) + len(report.gating_stale)
    if gating_gap_count > 0:
        parts.append("<details open class='section-gating'>")
        parts.append(f"<summary>⚠ GATING — never executed or stale ({gating_gap_count})</summary>")
        parts.append("<table><tr><th>Test</th><th>Status</th></tr>")
        for node_id in sorted(report.gating_never_executed):
            parts.append(f"<tr><td class='mono'>{esc(node_id)}</td><td>NEVER EXECUTED</td></tr>")
        for node_id, result in sorted(report.gating_stale, key=lambda entry: entry[0]):
            date_str = result.last_executed[:10] if result.last_executed else "unknown"
            parts.append(f"<tr><td class='mono'>{esc(node_id)}</td><td>STALE: {esc(date_str)}</td></tr>")
        parts.append("</table></details>")

    # ── FAILED TESTS section ──
    if report.failed:
        parts.append("<details open class='section-failed'>")
        parts.append(f"<summary>FAILED TESTS ({len(report.failed)})</summary>")

        defect_groups: dict[str, list[tuple[str, ItemResult]]] = {}
        for node_id, result in sorted(report.failed, key=lambda entry: entry[0]):
            group_key = result.defect_type or "Unclassified"
            defect_groups.setdefault(group_key, []).append((node_id, result))

        display_order = ["Product Bug", "Automation Bug", "System Issue", "To Investigate", "No Defect", "Not Issue"]
        sorted_groups: list[tuple[str, list[tuple[str, ItemResult]]]] = []
        for group_name in display_order:
            if group_name in defect_groups:
                sorted_groups.append((group_name, defect_groups.pop(group_name)))
        for group_name in sorted(defect_groups):
            sorted_groups.append((group_name, defect_groups[group_name]))

        for group_name, group_items in sorted_groups:
            parts.append(f"<div class='defect-group'>{esc(group_name)} ({len(group_items)}):</div>")
            parts.append(
                "<table><tr><th>Test</th><th>Bundle</th><th>Date</th>"
                "<th>Source</th><th>Polarion</th><th>Comment</th></tr>"
            )
            for node_id, result in group_items:
                raw_comment = result.defect_comment or ""
                comment = html_mod.escape(s=raw_comment)
                parts.append(_result_row(node_id=node_id, result=result, extra_col=f"<td>{comment}</td>"))
            parts.append("</table>")
        parts.append("</details>")

    # ── MANUAL TESTS section ──
    if report.never_executed_manual:
        parts.append("<details open class='section-manual'>")
        parts.append(f"<summary>MANUAL TESTS — never executed ({len(report.never_executed_manual)})</summary>")
        parts.append("<table><tr><th>Test</th></tr>")
        for node_id in sorted(report.never_executed_manual):
            parts.append(f"<tr><td class='mono'>{esc(node_id)}</td></tr>")
        parts.append("</table></details>")

    # ── NEVER EXECUTED section ──
    if report.never_executed:
        parts.append("<details class='section-never'>")
        parts.append(f"<summary>NEVER EXECUTED ({len(report.never_executed)})</summary>")
        parts.append("<table><tr><th>Test</th><th>Type</th></tr>")
        manual_set = set(report.never_executed_manual)
        for node_id in sorted(report.never_executed):
            label = "Manual" if node_id in manual_set else "Automated"
            parts.append(f"<tr><td class='mono'>{esc(node_id)}</td><td>{label}</td></tr>")
        parts.append("</table></details>")

    # ── STALE TESTS section ──
    if report.stale:
        parts.append("<details class='section-stale'>")
        parts.append(f"<summary>STALE TESTS ({len(report.stale)})</summary>")
        parts.append("<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th><th>Polarion</th></tr>")
        for node_id, result in sorted(report.stale, key=lambda entry: entry[0]):
            parts.append(_result_row(node_id=node_id, result=result))
        parts.append("</table></details>")

    # ── PASSED TESTS section (collapsed) ──
    if report.passed:
        parts.append("<details class='section-passed'>")
        parts.append(f"<summary>PASSED TESTS ({len(report.passed)})</summary>")
        parts.append("<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th><th>Polarion</th></tr>")
        for node_id, result in sorted(report.passed, key=lambda entry: entry[0]):
            parts.append(_result_row(node_id=node_id, result=result))
        parts.append("</table></details>")

    # ── SKIPPED TESTS section (collapsed) ──
    if report.skipped:
        parts.append("<details class='section-skipped'>")
        parts.append(f"<summary>SKIPPED TESTS ({len(report.skipped)})</summary>")
        parts.append("<table><tr><th>Test</th><th>Bundle</th><th>Date</th><th>Source</th><th>Polarion</th></tr>")
        for node_id, result in sorted(report.skipped, key=lambda entry: entry[0]):
            parts.append(_result_row(node_id=node_id, result=result))
        parts.append("</table></details>")

    parts.append(f"<div class='footer'>Generated by rp_coverage_gate · {generated_at}</div>")
    parts.append("</body></html>")

    return "\n".join(parts)
