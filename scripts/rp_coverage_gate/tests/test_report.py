# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.rp_coverage_gate.report module."""

from __future__ import annotations

import html as html_mod
import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from scripts.rp_coverage_gate.report import (
    CoverageReport,
    ParametrizedTestSummary,
    TeamStats,
    VariantStatus,
    _clean_param_display,
    _get_team_from_node_id,
    _group_by_base,
    _matrix_primary_section,
    _parse_two_axis_params,
    _render_annotated_list,
    analyze_coverage,
    format_html_report,
    format_json_report,
    format_text_report,
)
from scripts.rp_coverage_gate.rp_checker import ItemResult
from scripts.rp_coverage_gate.test_collector import QuarantinedTest, _parse_pytest_collect_output


def _make_result(
    name: str,
    status: str = "PASSED",
    last_executed: str = "",
    bundle: str = "4.19.0",
    launch_name: str = "launch-1",
    source: str = "automated",
) -> ItemResult:
    """Helper to create an ItemResult with sensible defaults."""
    return ItemResult(
        name=name,
        status=status,
        last_executed=last_executed,
        bundle=bundle,
        launch_name=launch_name,
        source=source,
    )


def _recent_iso() -> str:
    """Return an ISO timestamp for 1 day ago (not stale)."""
    return (datetime.now(tz=UTC) - timedelta(days=1)).isoformat()


def _old_iso(days: int = 60) -> str:
    """Return an ISO timestamp for N days ago (stale)."""
    return (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()


class TestGetTeamFromNodeId:
    def test_get_team_from_node_id(self) -> None:
        """Verify team name extracted from node ID."""
        result = _get_team_from_node_id(node_id="tests/network/foo/test_bar.py::TestClass::test_method")
        assert result == "network"

    @pytest.mark.parametrize(
        ("node_id", "expected"),
        [
            ("tests/storage/test_x.py::test_func", "storage"),
            ("something/else.py::test_func", ""),
            ("test_foo.py::test_func", ""),
        ],
    )
    def test_get_team_from_node_id_edge_cases(self, node_id: str, expected: str) -> None:
        """Verify team extraction for various node ID formats."""
        assert _get_team_from_node_id(node_id=node_id) == expected


class TestAnalyzeCoverage:
    def test_analyze_coverage_all_passed(self) -> None:
        """Verify gate passes when all tests are found in RP with PASSED status."""
        recent = _recent_iso()
        automated_ids = [
            "tests/network/test_a.py::TestA::test_one",
            "tests/network/test_a.py::TestA::test_two",
        ]
        rp_results = {
            "tests.network.test_a.TestA.test_one": _make_result(
                name="tests.network.test_a.TestA.test_one",
                status="PASSED",
                last_executed=recent,
            ),
            "tests.network.test_a.TestA.test_two": _make_result(
                name="tests.network.test_a.TestA.test_two",
                status="PASSED",
                last_executed=recent,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
        )

        assert report.gate_passed is True
        assert len(report.passed) == 2
        assert len(report.never_executed) == 0

    def test_analyze_coverage_never_executed(self) -> None:
        """Verify gate fails when some tests have no RP results."""
        recent = _recent_iso()
        automated_ids = [
            "tests/network/test_a.py::TestA::test_one",
            "tests/network/test_a.py::TestA::test_missing",
        ]
        rp_results = {
            "tests.network.test_a.TestA.test_one": _make_result(
                name="tests.network.test_a.TestA.test_one",
                status="PASSED",
                last_executed=recent,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
        )

        assert report.gate_passed is False
        assert len(report.never_executed) == 1
        assert "test_missing" in report.never_executed[0]

    def test_analyze_coverage_stale(self) -> None:
        """Verify stale list is populated for tests with old execution dates."""
        old = _old_iso(days=60)
        automated_ids = [
            "tests/network/test_a.py::TestA::test_old",
        ]
        rp_results = {
            "tests.network.test_a.TestA.test_old": _make_result(
                name="tests.network.test_a.TestA.test_old",
                status="PASSED",
                last_executed=old,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            stale_days=30,
        )

        assert len(report.stale) == 1
        assert report.gate_passed is False

    def test_analyze_coverage_team_filter(self) -> None:
        """Verify only tests matching team filter are included."""
        recent = _recent_iso()
        automated_ids = [
            "tests/network/test_a.py::TestA::test_net",
            "tests/storage/test_b.py::TestB::test_stor",
        ]
        rp_results = {
            "tests.network.test_a.TestA.test_net": _make_result(
                name="tests.network.test_a.TestA.test_net",
                status="PASSED",
                last_executed=recent,
            ),
            "tests.storage.test_b.TestB.test_stor": _make_result(
                name="tests.storage.test_b.TestB.test_stor",
                status="PASSED",
                last_executed=recent,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            team_filter="network",
        )

        assert report.total_tests == 1
        assert len(report.passed) == 1

    def test_analyze_coverage_fail_on_stale_false(self) -> None:
        """Verify stale tests don't fail gate when fail_on_stale=False."""
        old = _old_iso(days=60)
        automated_ids = [
            "tests/network/test_a.py::TestA::test_old",
        ]
        rp_results = {
            "tests.network.test_a.TestA.test_old": _make_result(
                name="tests.network.test_a.TestA.test_old",
                status="PASSED",
                last_executed=old,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            stale_days=30,
            fail_on_stale=False,
        )

        assert len(report.stale) == 1
        assert report.gate_passed is True


class TestFormatTextReport:
    def test_format_text_report(self) -> None:
        """Verify text report contains key sections and data."""
        report = CoverageReport(
            total_tests=10,
            automated_count=8,
            unautomated_count=2,
            passed=[("tests/net/test_a.py::TestA::test_one", _make_result(name="t1"))],
            failed=[("tests/net/test_a.py::TestA::test_two", _make_result(name="t2", status="FAILED"))],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_three"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_three"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(
            report=report,
            bundle_prefix="4.19",
            stale_days=30,
            full=True,
        )

        assert "Test Coverage Gate" in text
        assert "4.19" in text
        assert "Total tests in repo:" in text
        assert "NEVER EXECUTED:" in text
        assert "GATE: FAILED" in text


class TestFormatJsonReport:
    def test_format_json_report(self) -> None:
        """Verify JSON report is valid and contains expected keys."""
        report = CoverageReport(
            total_tests=5,
            automated_count=4,
            unautomated_count=1,
            passed=[("tests/net/test_a.py::TestA::test_one", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        json_str = format_json_report(
            report=report,
            bundle_prefix="4.19",
            stale_days=30,
        )

        data = json.loads(json_str)
        assert data["bundle_prefix"] == "4.19"
        assert data["stale_days"] == 30
        assert data["gate_passed"] is True
        assert "summary" in data
        assert data["summary"]["total_tests"] == 5
        assert "passed" in data
        assert "failed" in data
        assert "never_executed" in data


class TestGatingCoverage:
    def test_analyze_coverage_gating_never_executed(self) -> None:
        """Verify gating tests are tracked separately when never executed."""
        recent = _recent_iso()
        automated_ids = [
            "tests/network/test_a.py::TestA::test_gated",
            "tests/network/test_a.py::TestA::test_normal",
        ]
        gating_ids = {"tests/network/test_a.py::TestA::test_gated"}
        rp_results = {
            "tests.network.test_a.TestA.test_normal": _make_result(
                name="tests.network.test_a.TestA.test_normal",
                status="PASSED",
                last_executed=recent,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            gating_ids=gating_ids,
        )

        assert len(report.never_executed) == 1  # only test_gated is missing
        assert len(report.gating_never_executed) == 1
        assert "test_gated" in report.gating_never_executed[0]

    def test_analyze_coverage_gating_stale(self) -> None:
        """Verify gating tests are tracked separately when stale."""
        old = _old_iso(days=60)
        automated_ids = [
            "tests/network/test_a.py::TestA::test_gated",
        ]
        gating_ids = {"tests/network/test_a.py::TestA::test_gated"}
        rp_results = {
            "tests.network.test_a.TestA.test_gated": _make_result(
                name="tests.network.test_a.TestA.test_gated",
                status="PASSED",
                last_executed=old,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            stale_days=30,
            gating_ids=gating_ids,
        )

        assert len(report.gating_stale) == 1
        assert "test_gated" in report.gating_stale[0][0]

    def test_gating_section_in_text_report(self) -> None:
        """Verify GATING section appears in text report when there are gating gaps."""
        report = CoverageReport(
            total_tests=5,
            automated_count=5,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_gated", "tests/net/test_a.py::TestA::test_other"],
            never_executed_automated=[
                "tests/net/test_a.py::TestA::test_gated",
                "tests/net/test_a.py::TestA::test_other",
            ],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=["tests/net/test_a.py::TestA::test_gated"],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22.0", stale_days=30)

        assert "GATING" in text
        assert "⚠" in text
        assert "NEVER EXECUTED" in text
        assert "test_gated" in text

    def test_gating_in_json_report(self) -> None:
        """Verify gating field present in JSON report."""
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_gated"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_gated"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=["tests/net/test_a.py::TestA::test_gated"],
            gating_stale=[],
            quarantined=[],
        )

        json_str = format_json_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        data = json.loads(json_str)

        assert "gating" in data
        assert len(data["gating"]["never_executed"]) == 1

    def test_no_gating_section_when_all_gating_covered(self) -> None:
        """Verify GATING section does not appear when all gating tests are covered."""
        recent = _recent_iso()
        automated_ids = [
            "tests/network/test_a.py::TestA::test_gated",
        ]
        gating_ids = {"tests/network/test_a.py::TestA::test_gated"}
        rp_results = {
            "tests.network.test_a.TestA.test_gated": _make_result(
                name="tests.network.test_a.TestA.test_gated",
                status="PASSED",
                last_executed=recent,
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            gating_ids=gating_ids,
        )

        assert len(report.gating_never_executed) == 0
        assert len(report.gating_stale) == 0

        text = format_text_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        assert "GATING" not in text


class TestFailedTestsAlwaysShown:
    def test_failed_tests_shown_without_full_flag(self) -> None:
        """Verify FAILED TESTS section appears in default (non-full) mode."""
        recent = _recent_iso()
        report = CoverageReport(
            total_tests=3,
            automated_count=3,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_ok", _make_result(name="t1", last_executed=recent))],
            failed=[
                (
                    "tests/net/test_a.py::TestA::test_broken",
                    _make_result(name="t2", status="FAILED", last_executed=recent, bundle="v4.22.0"),
                )
            ],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22.0", stale_days=30, full=False)

        assert "FAILED TESTS" in text
        assert "test_broken" in text

    def test_failed_tests_grouped_by_defect_type(self) -> None:
        """Verify FAILED TESTS section groups tests by defect type."""
        recent = _recent_iso()
        report = CoverageReport(
            total_tests=5,
            automated_count=5,
            unautomated_count=0,
            passed=[],
            failed=[
                (
                    "tests/net/test_a.py::TestA::test_pb",
                    _make_result(
                        name="t_pb",
                        status="FAILED",
                        last_executed=recent,
                        bundle="v4.22.0",
                    ),
                ),
                (
                    "tests/net/test_a.py::TestA::test_ab",
                    _make_result(
                        name="t_ab",
                        status="FAILED",
                        last_executed=recent,
                        bundle="v4.22.0",
                    ),
                ),
                (
                    "tests/net/test_a.py::TestA::test_ti",
                    _make_result(
                        name="t_ti",
                        status="FAILED",
                        last_executed=recent,
                        bundle="v4.22.0",
                    ),
                ),
            ],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )
        # Set defect types directly on results
        report.failed[0][1].defect_type = "Product Bug"
        report.failed[0][1].defect_comment = "CNV-12345: VM migration fails on SRIOV"
        report.failed[1][1].defect_type = "Automation Bug"
        report.failed[1][1].defect_comment = "Framework timeout in teardown"
        report.failed[2][1].defect_type = "To Investigate"

        text = format_text_report(report=report, bundle_prefix="v4.22.0", stale_days=30, full=False)

        assert "FAILED TESTS (3):" in text
        assert "Product Bug (1):" in text
        assert "Automation Bug (1):" in text
        assert "To Investigate (1):" in text
        assert "CNV-12345: VM migration fails on SRIOV" in text
        assert "Framework timeout in teardown" in text
        # Verify Product Bug appears before Automation Bug in output
        pb_pos = text.index("Product Bug")
        ab_pos = text.index("Automation Bug")
        assert pb_pos < ab_pos


class TestNeverExecutedSplit:
    def test_analyze_splits_never_executed_by_type(self) -> None:
        """Verify never-executed tests are split into automated and manual."""
        automated_ids = [
            "tests/network/test_a.py::TestA::test_auto_missing",
        ]
        unautomated_ids = [
            "tests/network/test_a.py::TestA::test_manual_missing",
        ]

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=unautomated_ids,
            rp_results={},
        )

        assert len(report.never_executed) == 2
        assert len(report.never_executed_automated) == 1
        assert len(report.never_executed_manual) == 1
        assert "test_auto_missing" in report.never_executed_automated[0]
        assert "test_manual_missing" in report.never_executed_manual[0]

    def test_manual_section_in_text_report(self) -> None:
        """Verify MANUAL TESTS section appears in default mode."""
        report = CoverageReport(
            total_tests=3,
            automated_count=2,
            unautomated_count=1,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[
                "tests/net/test_a.py::TestA::test_auto",
                "tests/net/test_a.py::TestA::test_manual",
            ],
            never_executed_automated=["tests/net/test_a.py::TestA::test_auto"],
            never_executed_manual=["tests/net/test_a.py::TestA::test_manual"],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30, full=False)

        assert "MANUAL TESTS" in text
        assert "test_manual" in text
        # Automated never-executed should NOT appear in default mode
        assert "NEVER EXECUTED:" not in text

    def test_full_mode_labels_manual(self) -> None:
        """Verify full mode labels manual tests with [MANUAL] tag."""
        report = CoverageReport(
            total_tests=3,
            automated_count=2,
            unautomated_count=1,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[
                "tests/net/test_a.py::TestA::test_auto",
                "tests/net/test_a.py::TestA::test_manual",
            ],
            never_executed_automated=["tests/net/test_a.py::TestA::test_auto"],
            never_executed_manual=["tests/net/test_a.py::TestA::test_manual"],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30, full=True)

        assert "NEVER EXECUTED:" in text
        assert "[MANUAL]" in text
        # Auto test should not have [MANUAL] label
        auto_line = [line for line in text.split("\n") if "test_auto" in line and "MANUAL TESTS" not in line][0]
        assert "[MANUAL]" not in auto_line

    def test_summary_shows_split_counts(self) -> None:
        """Verify summary section shows automated and manual never-executed counts."""
        report = CoverageReport(
            total_tests=10,
            automated_count=8,
            unautomated_count=2,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=["a", "b", "c", "d", "e"],
            never_executed_automated=["a", "b", "c"],
            never_executed_manual=["d", "e"],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30)

        assert "Never executed:          5" in text
        assert "Automated:             3" in text
        assert "Manual (STD):          2" in text

    def test_json_report_includes_split(self) -> None:
        """Verify JSON report contains never_executed_automated and never_executed_manual."""
        report = CoverageReport(
            total_tests=3,
            automated_count=2,
            unautomated_count=1,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=["auto_test", "manual_test"],
            never_executed_automated=["auto_test"],
            never_executed_manual=["manual_test"],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        json_str = format_json_report(report=report, bundle_prefix="v4.22", stale_days=30)
        data = json.loads(json_str)

        assert data["never_executed_automated"] == ["auto_test"]
        assert data["never_executed_manual"] == ["manual_test"]

    def test_no_manual_section_when_empty(self) -> None:
        """Verify MANUAL TESTS section does not appear when no manual tests are missing."""
        report = CoverageReport(
            total_tests=5,
            automated_count=5,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::test_auto"],
            never_executed_automated=["tests/net/test_a.py::test_auto"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30)

        assert "MANUAL TESTS" not in text


class TestFormatHtmlReport:
    def test_html_report_contains_key_elements(self) -> None:
        """Verify HTML report contains gate status, sections, and test names."""
        recent = _recent_iso()
        report = CoverageReport(
            total_tests=10,
            automated_count=8,
            unautomated_count=2,
            passed=[("tests/net/test_a.py::TestA::test_ok", _make_result(name="t1", last_executed=recent))],
            failed=[
                (
                    "tests/net/test_a.py::TestA::test_broken",
                    _make_result(name="t2", status="FAILED", last_executed=recent, bundle="v4.22.0"),
                )
            ],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_missing", "tests/net/test_a.py::TestA::test_manual"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_missing"],
            never_executed_manual=["tests/net/test_a.py::TestA::test_manual"],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
            team_stats={
                "net": TeamStats(
                    total=10, passed=1, failed=1, skipped=0, never_executed=2, stale=0, quarantined=0, coverage_pct=20.0
                )
            },
        )

        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)

        assert "<!DOCTYPE html>" in html
        assert "Test Coverage Gate" in html
        assert "v4.22.0" in html
        assert "GATE: FAILED" in html
        assert "badge-fail" in html
        assert "FAILED TESTS" in html
        assert "test_broken" in html
        assert "MANUAL TESTS" in html
        assert "test_manual" in html
        assert "NEVER EXECUTED" in html
        assert "PASSED TESTS" in html
        assert "test_ok" in html
        # Tab structure
        assert "tab-btn" in html
        assert "tab-content" in html
        assert "openTab" in html
        assert "net" in html

    def test_html_report_gate_passed(self) -> None:
        """Verify HTML report shows PASSED badge when gate passes."""
        recent = _recent_iso()
        report = CoverageReport(
            total_tests=1,
            automated_count=1,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_ok", _make_result(name="t1", last_executed=recent))],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
            team_stats={
                "net": TeamStats(
                    total=1, passed=1, failed=0, skipped=0, never_executed=0, stale=0, quarantined=0, coverage_pct=100.0
                )
            },
        )

        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)

        assert "GATE: PASSED" in html
        assert "badge-pass" in html
        assert "FAILED TESTS" not in html
        assert "MANUAL TESTS" not in html

    def test_html_report_gating_section(self) -> None:
        """Verify GATING section appears in team tab when gating gaps exist."""
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_gated"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_gated"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=["tests/net/test_a.py::TestA::test_gated"],
            gating_stale=[],
            quarantined=[],
            team_stats={
                "net": TeamStats(
                    total=2, passed=0, failed=0, skipped=0, never_executed=1, stale=0, quarantined=0, coverage_pct=0.0
                )
            },
        )

        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)

        assert "GATING" in html
        assert "test_gated" in html
        assert "NEVER EXECUTED" in html

    def test_filters_warning_lines(self) -> None:
        """Verify WARNING lines from pytest-order are filtered out."""

        stdout = (
            "tests/network/test_a.py::TestA::test_one\n"
            "WARNING: cannot execute test relative to others: "
            "tests/network/test_a.py::TestA::test_one tests/network/test_a.py::TestA::test_two\n"
            "tests/network/test_a.py::TestA::test_two\n"
        )
        result = _parse_pytest_collect_output(stdout=stdout)

        assert len(result) == 2
        assert "tests/network/test_a.py::TestA::test_one" in result
        assert "tests/network/test_a.py::TestA::test_two" in result

    def test_filters_error_and_hint_lines(self) -> None:
        """Verify ERROR and HINT lines are filtered out."""

        stdout = (
            "tests/virt/test_b.py::test_func\nERROR: some plugin error with :: in it\nHINT: try fixing :: something\n"
        )
        result = _parse_pytest_collect_output(stdout=stdout)

        assert result == ["tests/virt/test_b.py::test_func"]

    def test_filters_lines_with_spaces_in_path(self) -> None:
        """Verify lines with spaces before :: are filtered out."""

        stdout = "tests/network/test_a.py::TestA::test_one\nsome random text tests/foo.py::test_bar\n"
        result = _parse_pytest_collect_output(stdout=stdout)

        assert result == ["tests/network/test_a.py::TestA::test_one"]

    def test_skips_empty_and_summary_lines(self) -> None:
        """Verify empty and summary lines (no ::) are skipped."""

        stdout = "tests/net/test_a.py::test_one\n\n  \n3 tests collected in 0.5s\n"
        result = _parse_pytest_collect_output(stdout=stdout)

        assert result == ["tests/net/test_a.py::test_one"]


class TestParametrizedGrouping:
    def test_group_by_base_parametrized(self) -> None:
        """Verify parametrized tests are grouped by base name."""

        items = [
            "tests/infra/test_rhel.py::TestVM::test_create[rhel10-hcb]",
            "tests/infra/test_rhel.py::TestVM::test_create[rhel10-ocs]",
            "tests/infra/test_rhel.py::TestVM::test_create[rhel8-hcb]",
            "tests/infra/test_rhel.py::TestVM::test_delete",
        ]
        grouped = _group_by_base(items=items)

        assert len(grouped) == 2
        base_create, params_create = grouped[0]
        assert base_create == "tests/infra/test_rhel.py::TestVM::test_create"
        assert len(params_create) == 3
        base_delete, params_delete = grouped[1]
        assert base_delete == "tests/infra/test_rhel.py::TestVM::test_delete"
        assert params_delete == [""]

    def test_text_report_groups_never_executed(self) -> None:
        """Verify text report groups parametrized never-executed tests."""
        report = CoverageReport(
            total_tests=4,
            automated_count=4,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[
                "tests/net/test_a.py::TestA::test_one[param1]",
                "tests/net/test_a.py::TestA::test_one[param2]",
                "tests/net/test_a.py::TestA::test_one[param3]",
                "tests/net/test_a.py::TestA::test_two",
            ],
            never_executed_automated=[
                "tests/net/test_a.py::TestA::test_one[param1]",
                "tests/net/test_a.py::TestA::test_one[param2]",
                "tests/net/test_a.py::TestA::test_one[param3]",
                "tests/net/test_a.py::TestA::test_two",
            ],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30, full=True)

        assert "test_one (3 variants)" in text
        assert "[param1]" in text
        assert "[param2]" in text
        assert "test_two" in text

    def test_json_report_has_grouped_key(self) -> None:
        """Verify JSON report contains grouped view."""
        recent = _recent_iso()
        report = CoverageReport(
            total_tests=3,
            automated_count=3,
            unautomated_count=0,
            passed=[
                ("tests/net/test_a.py::TestA::test_one[p1]", _make_result(name="t1", last_executed=recent)),
                ("tests/net/test_a.py::TestA::test_one[p2]", _make_result(name="t2", last_executed=recent)),
            ],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        json_str = format_json_report(report=report, bundle_prefix="v4.22", stale_days=30)
        data = json.loads(json_str)

        assert "grouped" in data
        grouped_passed = data["grouped"]["passed"]
        assert len(grouped_passed) == 1
        assert grouped_passed[0]["base_test"] == "tests/net/test_a.py::TestA::test_one"
        assert grouped_passed[0]["variant_count"] == 2


class TestExcludeTeam:
    def test_exclude_team_filters_out_tests(self) -> None:
        """Verify exclude_teams removes tests from excluded teams."""
        recent = _recent_iso()
        automated_ids = [
            "tests/network/test_a.py::TestA::test_net",
            "tests/chaos/test_b.py::TestB::test_chaos",
            "tests/storage/test_c.py::TestC::test_stor",
        ]
        rp_results = {
            "tests.network.test_a.TestA.test_net": _make_result(
                name="tests.network.test_a.TestA.test_net", status="PASSED", last_executed=recent
            ),
            "tests.chaos.test_b.TestB.test_chaos": _make_result(
                name="tests.chaos.test_b.TestB.test_chaos", status="PASSED", last_executed=recent
            ),
            "tests.storage.test_c.TestC.test_stor": _make_result(
                name="tests.storage.test_c.TestC.test_stor", status="PASSED", last_executed=recent
            ),
        }

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results=rp_results,
            exclude_teams=("chaos",),
        )

        assert report.total_tests == 2
        assert len(report.passed) == 2
        node_ids = [nid for nid, _ in report.passed]
        assert all("chaos" not in nid for nid in node_ids)

    def test_exclude_multiple_teams(self) -> None:
        """Verify multiple teams can be excluded."""
        automated_ids = [
            "tests/network/test_a.py::test_net",
            "tests/chaos/test_b.py::test_chaos",
            "tests/deprecated_api/test_c.py::test_dep",
            "tests/storage/test_d.py::test_stor",
        ]

        report = analyze_coverage(
            automated_ids=automated_ids,
            unautomated_ids=[],
            rp_results={},
            exclude_teams=("chaos", "deprecated_api"),
        )

        assert report.total_tests == 2
        assert len(report.never_executed) == 2


class TestTeamGrouping:
    def test_text_report_shows_team_headers(self) -> None:
        """Verify text report groups tests by team within sections."""
        report = CoverageReport(
            total_tests=3,
            automated_count=3,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[
                "tests/network/test_a.py::TestA::test_net",
                "tests/storage/test_b.py::TestB::test_stor",
                "tests/network/test_c.py::TestC::test_net2",
            ],
            never_executed_automated=[
                "tests/network/test_a.py::TestA::test_net",
                "tests/storage/test_b.py::TestB::test_stor",
                "tests/network/test_c.py::TestC::test_net2",
            ],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30, full=True)

        assert "\u2500\u2500 network (2) \u2500\u2500" in text
        assert "\u2500\u2500 storage (1) \u2500\u2500" in text

    def test_json_report_has_by_team_key(self) -> None:
        """Verify JSON report contains by_team grouping."""
        recent = _recent_iso()
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[
                ("tests/network/test_a.py::TestA::test_one", _make_result(name="t1", last_executed=recent)),
                ("tests/storage/test_b.py::TestB::test_two", _make_result(name="t2", last_executed=recent)),
            ],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )

        json_str = format_json_report(report=report, bundle_prefix="v4.22", stale_days=30)
        data = json.loads(json_str)

        assert "by_team" in data
        assert "network" in data["by_team"]["passed"]
        assert "storage" in data["by_team"]["passed"]
        assert len(data["by_team"]["passed"]["network"]) == 1
        assert len(data["by_team"]["passed"]["storage"]) == 1

    def test_gating_groups_parametrized(self) -> None:
        """Verify gating section groups parametrized tests."""
        report = CoverageReport(
            total_tests=4,
            automated_count=4,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[
                "tests/network/test_a.py::TestA::test_gating[p1]",
                "tests/network/test_a.py::TestA::test_gating[p2]",
                "tests/network/test_a.py::TestA::test_gating[p3]",
                "tests/network/test_a.py::TestA::test_other",
            ],
            never_executed_automated=[
                "tests/network/test_a.py::TestA::test_gating[p1]",
                "tests/network/test_a.py::TestA::test_gating[p2]",
                "tests/network/test_a.py::TestA::test_gating[p3]",
                "tests/network/test_a.py::TestA::test_other",
            ],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[
                "tests/network/test_a.py::TestA::test_gating[p1]",
                "tests/network/test_a.py::TestA::test_gating[p2]",
                "tests/network/test_a.py::TestA::test_gating[p3]",
            ],
            gating_stale=[],
            quarantined=[],
        )

        text = format_text_report(report=report, bundle_prefix="v4.22", stale_days=30)

        assert "test_gating (3 variants) [NEVER EXECUTED]" in text
        assert "[p1]" in text
        assert "[p2]" in text


class TestQuarantineReporting:
    def test_quarantined_excluded_from_never_executed(self) -> None:
        """Verify quarantined tests are not counted as never-executed."""
        quarantined = [
            QuarantinedTest(
                node_id="tests/net/test_a.py::TestA::test_quarantined",
                reason="QUARANTINED: tracked in CNV-12345",
                jira="CNV-12345",
            ),
        ]
        report = analyze_coverage(
            automated_ids=[
                "tests/net/test_a.py::TestA::test_ok",
                "tests/net/test_a.py::TestA::test_quarantined",
            ],
            unautomated_ids=[],
            rp_results={
                "tests.net.test_a.TestA.test_ok": _make_result(name="tests.net.test_a.TestA.test_ok"),
            },
            quarantined=quarantined,
        )
        assert len(report.never_executed) == 0
        assert len(report.quarantined) == 1
        assert report.gate_passed is True

    def test_quarantined_in_html_report(self) -> None:
        """Verify quarantined section appears in HTML per-team tab."""
        quarantined = [
            QuarantinedTest(
                node_id="tests/net/test_a.py::TestA::test_broken",
                reason="QUARANTINED: flaky, tracked in CNV-99999",
                jira="CNV-99999",
            ),
        ]
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_ok", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=quarantined,
            team_stats={
                "net": TeamStats(
                    total=2,
                    passed=1,
                    failed=0,
                    skipped=0,
                    never_executed=0,
                    stale=0,
                    quarantined=1,
                    coverage_pct=50.0,
                ),
            },
        )
        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        assert "QUARANTINED" in html
        assert "CNV-99999" in html
        assert "issues.redhat.com/browse/CNV-99999" in html
        assert "section-quarantined" in html

    def test_quarantined_in_text_report(self) -> None:
        """Verify quarantined section appears in text report."""
        quarantined = [
            QuarantinedTest(
                node_id="tests/net/test_a.py::TestA::test_broken",
                reason="QUARANTINED: tracked in CNV-99999",
                jira="CNV-99999",
            ),
        ]
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_ok", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=quarantined,
        )
        text = format_text_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        assert "QUARANTINED" in text
        assert "CNV-99999" in text
        assert "test_broken" in text

    def test_quarantined_in_json_report(self) -> None:
        """Verify quarantined appears in JSON report."""
        quarantined = [
            QuarantinedTest(
                node_id="tests/net/test_a.py::TestA::test_broken",
                reason="tracked in CNV-99999",
                jira="CNV-99999",
            ),
        ]
        report = CoverageReport(
            total_tests=1,
            automated_count=1,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=quarantined,
        )
        json_str = format_json_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        data = json.loads(json_str)
        assert data["summary"]["quarantined_count"] == 1
        assert len(data["quarantined"]) == 1
        assert data["quarantined"][0]["jira"] == "CNV-99999"


class TestMatrixRendering:
    def test_parse_two_axis_params(self) -> None:
        """Verify 2-axis parameter parsing."""
        result = _parse_two_axis_params(params="[#rhel.10#-#hostpath-csi-basic#]")
        assert result == ("rhel.10", "hostpath-csi-basic")

    def test_parse_two_axis_params_single_axis(self) -> None:
        """Verify single-axis params return None."""
        result = _parse_two_axis_params(params="[simple_param]")
        assert result is None

    def test_parametrized_summaries_built(self) -> None:
        """Verify parametrized summaries are built in analyze_coverage."""
        recent = _recent_iso()
        result_passed = _make_result(name="t1", last_executed=recent)
        result_failed = _make_result(name="t2", status="FAILED", last_executed=recent)

        report = analyze_coverage(
            automated_ids=[
                "tests/net/test_a.py::TestA::test_vm[#rhel.10#-#hostpath#]",
                "tests/net/test_a.py::TestA::test_vm[#rhel.10#-#ocs-rbd#]",
                "tests/net/test_a.py::TestA::test_vm[#rhel.8#-#hostpath#]",
                "tests/net/test_a.py::TestA::test_vm[#rhel.8#-#ocs-rbd#]",
            ],
            unautomated_ids=[],
            rp_results={
                "tests.net.test_a.TestA.test_vm[#rhel.10#-#hostpath#]": result_passed,
                "tests.net.test_a.TestA.test_vm[#rhel.10#-#ocs-rbd#]": result_failed,
                "tests.net.test_a.TestA.test_vm[#rhel.8#-#hostpath#]": result_passed,
            },
        )

        assert report.parametrized_summaries is not None
        assert "net" in report.parametrized_summaries
        summaries = report.parametrized_summaries["net"]
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.is_two_axis is True
        assert set(summary.axis1_values) == {"rhel.10", "rhel.8"}
        assert set(summary.axis2_values) == {"hostpath", "ocs-rbd"}
        assert len(summary.variants) == 4

    def test_matrix_in_html_report(self) -> None:
        """Verify matrix table appears in HTML for 2-axis parametrized tests."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#rhel.10#-#hostpath#]", status="PASSED", result=None),
                VariantStatus(params="[#rhel.10#-#ocs-rbd#]", status="NEVER_EXECUTED", result=None),
                VariantStatus(params="[#rhel.8#-#hostpath#]", status="NEVER_EXECUTED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["rhel.10", "rhel.8"],
            axis2_values=["hostpath", "ocs-rbd"],
        )

        report = CoverageReport(
            total_tests=3,
            automated_count=3,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_vm[#rhel.10#-#hostpath#]", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_vm[#rhel.8#-#hostpath#]"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_vm[#rhel.8#-#hostpath#]"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
            parametrized_summaries={"net": [summary]},
            team_stats={
                "net": TeamStats(
                    total=3,
                    passed=1,
                    failed=0,
                    skipped=0,
                    never_executed=1,
                    stale=0,
                    quarantined=0,
                    coverage_pct=33.3,
                ),
            },
        )

        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        assert "matrix-table" in html
        assert "rhel.10" in html
        assert "hostpath" in html
        assert "status-passed" in html
        assert "status-never" in html


class TestLegendAndDeduplication:
    def test_legend_in_html_report(self) -> None:
        """Verify legend section appears in HTML summary tab."""
        report = CoverageReport(
            total_tests=1,
            automated_count=1,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::test_ok", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=[],
            never_executed_automated=[],
            never_executed_manual=[],
            stale=[],
            gate_passed=True,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
        )
        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        assert "class='legend'" in html or 'class="legend"' in html
        assert "Legend" in html
        assert "Product Bug" in html
        assert "Auto Bug" in html
        assert "Status Icons" in html
        assert "Defect Classifications" in html
        assert "status-passed" in html
        assert "status-quarantined" in html
        # Legend is outside tab-content (collapsible, always visible)
        assert "<details>" in html

    def test_matrix_deduplicates_list(self) -> None:
        """Verify tests in matrix don't also appear in list view."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#rhel.10#-#hostpath#]", status="NEVER_EXECUTED", result=None),
                VariantStatus(params="[#rhel.8#-#hostpath#]", status="NEVER_EXECUTED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["rhel.10", "rhel.8"],
            axis2_values=["hostpath"],
        )
        report = CoverageReport(
            total_tests=3,
            automated_count=3,
            unautomated_count=0,
            passed=[],
            failed=[],
            skipped=[],
            never_executed=[
                "tests/net/test_a.py::TestA::test_vm[#rhel.10#-#hostpath#]",
                "tests/net/test_a.py::TestA::test_vm[#rhel.8#-#hostpath#]",
                "tests/net/test_a.py::TestA::test_standalone",
            ],
            never_executed_automated=[
                "tests/net/test_a.py::TestA::test_vm[#rhel.10#-#hostpath#]",
                "tests/net/test_a.py::TestA::test_vm[#rhel.8#-#hostpath#]",
                "tests/net/test_a.py::TestA::test_standalone",
            ],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
            parametrized_summaries={"net": [summary]},
            team_stats={
                "net": TeamStats(
                    total=3,
                    passed=0,
                    failed=0,
                    skipped=0,
                    never_executed=3,
                    stale=0,
                    quarantined=0,
                    coverage_pct=0.0,
                ),
            },
        )
        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        # Matrix should appear
        assert "matrix-table" in html
        # The standalone test should appear in list
        assert "test_standalone" in html
        # The parametrized variants should NOT appear as individual list rows
        # (they're in the matrix instead)
        # Count occurrences of test_vm - should only be in matrix header, not in list rows
        # The matrix header has the base_test, but no individual <tr><td> for each variant
        list_rows = re.findall(r"<tr><td class='mono'>[^<]*test_vm\[", html)
        assert len(list_rows) == 0, f"Found {len(list_rows)} list rows for matrix test: {list_rows}"


class TestMatrixPrimarySection:
    def test_matrix_appears_in_worst_section_only(self) -> None:
        """Verify matrix with mixed statuses appears only in the worst section."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#rhel.10#-#hostpath#]", status="PASSED", result=None),
                VariantStatus(params="[#rhel.10#-#ocs#]", status="NEVER_EXECUTED", result=None),
                VariantStatus(params="[#rhel.8#-#hostpath#]", status="PASSED", result=None),
                VariantStatus(params="[#rhel.8#-#ocs#]", status="PASSED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["rhel.10", "rhel.8"],
            axis2_values=["hostpath", "ocs"],
        )
        assert _matrix_primary_section(summary=summary) == "never_executed"

    def test_failed_takes_priority(self) -> None:
        """Verify FAILED status takes priority over never-executed."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#a#-#b#]", status="FAILED", result=None),
                VariantStatus(params="[#a#-#c#]", status="NEVER_EXECUTED", result=None),
                VariantStatus(params="[#d#-#b#]", status="PASSED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["a", "d"],
            axis2_values=["b", "c"],
        )
        assert _matrix_primary_section(summary=summary) == "failed"

    def test_all_passed_goes_to_passed_section(self) -> None:
        """Verify all-passed matrix goes to passed section."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#a#-#b#]", status="PASSED", result=None),
                VariantStatus(params="[#a#-#c#]", status="PASSED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["a"],
            axis2_values=["b", "c"],
        )
        assert _matrix_primary_section(summary=summary) == "passed"

    def test_matrix_not_duplicated_across_sections(self) -> None:
        """Verify a matrix test does not appear in both NEVER EXECUTED and PASSED."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#rhel.10#-#hostpath#]", status="PASSED", result=None),
                VariantStatus(params="[#rhel.10#-#ocs#]", status="NEVER_EXECUTED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["rhel.10"],
            axis2_values=["hostpath", "ocs"],
        )
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_vm[#rhel.10#-#hostpath#]", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_vm[#rhel.10#-#ocs#]"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_vm[#rhel.10#-#ocs#]"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
            parametrized_summaries={"net": [summary]},
            team_stats={
                "net": TeamStats(
                    total=2,
                    passed=1,
                    failed=0,
                    skipped=0,
                    never_executed=1,
                    stale=0,
                    quarantined=0,
                    coverage_pct=50.0,
                ),
            },
        )
        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        # Matrix table element should appear exactly once (excludes CSS/legend mentions)
        matrix_count = html.count("<table class='matrix-table'>")
        assert matrix_count == 1, f"Expected 1 matrix-table element, found {matrix_count}"
        # It should be in NEVER EXECUTED section (worst status)
        ne_sections = [i for i, c in enumerate(html) if html[i : i + 14] == "NEVER EXECUTED"]
        matrix_pos = html.index("<table class='matrix-table'>")
        assert any(matrix_pos > s for s in ne_sections), "Matrix should be in NEVER EXECUTED section"

    def test_gating_takes_priority(self) -> None:
        """Verify gating status takes priority over other statuses."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#a#-#b#]", status="NEVER_EXECUTED", result=None),
                VariantStatus(params="[#a#-#c#]", status="PASSED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["a"],
            axis2_values=["b", "c"],
        )
        gating = {"tests/net/test_a.py::TestA::test_vm[#a#-#b#]"}
        assert _matrix_primary_section(summary=summary, gating_ids=gating) == "gating"

    def test_no_gating_ids_falls_through(self) -> None:
        """Verify without gating_ids, normal priority applies."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_vm",
            variants=[
                VariantStatus(params="[#a#-#b#]", status="NEVER_EXECUTED", result=None),
            ],
            is_two_axis=True,
            axis1_values=["a"],
            axis2_values=["b"],
        )
        assert _matrix_primary_section(summary=summary) == "never_executed"


class TestAnnotatedList:
    def test_non_2axis_renders_annotated_list(self) -> None:
        """Verify non-2-axis parametrized tests render annotated list in HTML."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_foo",
            variants=[
                VariantStatus(params="[hostpath]", status="PASSED", result=None),
                VariantStatus(params="[ocs-rbd]", status="NEVER_EXECUTED", result=None),
            ],
            is_two_axis=False,
            axis1_values=[],
            axis2_values=[],
        )
        report = CoverageReport(
            total_tests=2,
            automated_count=2,
            unautomated_count=0,
            passed=[("tests/net/test_a.py::TestA::test_foo[hostpath]", _make_result(name="t1"))],
            failed=[],
            skipped=[],
            never_executed=["tests/net/test_a.py::TestA::test_foo[ocs-rbd]"],
            never_executed_automated=["tests/net/test_a.py::TestA::test_foo[ocs-rbd]"],
            never_executed_manual=[],
            stale=[],
            gate_passed=False,
            gating_never_executed=[],
            gating_stale=[],
            quarantined=[],
            parametrized_summaries={"net": [summary]},
            team_stats={
                "net": TeamStats(
                    total=2,
                    passed=1,
                    failed=0,
                    skipped=0,
                    never_executed=1,
                    stale=0,
                    quarantined=0,
                    coverage_pct=50.0,
                ),
            },
        )
        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)
        # Should contain horizontal 1-row matrix for single-axis params
        assert "matrix-table" in html
        assert "test_foo" in html
        assert "hostpath" in html
        assert "ocs-rbd" in html
        assert "status-passed" in html
        assert "status-never" in html

    def test_annotated_list_appears_in_worst_section(self) -> None:
        """Verify non-2-axis annotated list appears only in worst-status section."""
        recent = _recent_iso()
        report = analyze_coverage(
            automated_ids=[
                "tests/net/test_a.py::TestA::test_foo[hostpath]",
                "tests/net/test_a.py::TestA::test_foo[ocs-rbd]",
            ],
            unautomated_ids=[],
            rp_results={
                "tests.net.test_a.TestA.test_foo[hostpath]": _make_result(
                    name="t1",
                    last_executed=recent,
                ),
            },
        )
        assert report.parametrized_summaries is not None
        assert "net" in report.parametrized_summaries
        summaries = report.parametrized_summaries["net"]
        assert len(summaries) == 1
        assert summaries[0].is_two_axis is False
        # Should be in never_executed section (worst status)
        assert _matrix_primary_section(summary=summaries[0]) == "never_executed"

    def test_failed_defect_in_annotated_list(self) -> None:
        """Verify failed variant shows defect abbreviation in annotated list."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_foo",
            variants=[
                VariantStatus(
                    params="[hostpath]",
                    status="FAILED",
                    result=None,
                    defect_type="Product Bug",
                ),
                VariantStatus(params="[ocs-rbd]", status="PASSED", result=None),
            ],
            is_two_axis=False,
            axis1_values=[],
            axis2_values=[],
        )
        parts = _render_annotated_list(summary=summary, esc=html_mod.escape)
        html = "\n".join(parts)
        # Horizontal table shows defect label in cell (same as 2-axis matrix)
        assert "Product Bug" in html
        assert "status-failed" in html
        assert "status-passed" in html
        assert "matrix-table" in html

    def test_clean_param_display_strips_fixture(self) -> None:
        """Verify fixture suffixes are stripped from param display."""
        result = _clean_param_display(
            params="[#hostpath-csi-basic#-golden_image_data_volume_multi_storage_scope_function0]",
        )
        assert result == "[hostpath-csi-basic]"

    def test_clean_param_display_preserves_plain(self) -> None:
        """Verify params without # delimiters are kept as-is."""
        result = _clean_param_display(params="[ipv4]")
        assert result == "[ipv4]"

    def test_clean_param_display_two_axis(self) -> None:
        """Verify two #value# groups are joined with em-dash."""
        result = _clean_param_display(params="[#rhel.10#-#hostpath-csi-basic#]")
        assert "rhel.10" in result
        assert "hostpath-csi-basic" in result
        assert "\u2014" in result  # em-dash separator

    def test_annotated_list_uses_clean_params(self) -> None:
        """Verify horizontal table renders cleaned param names as headers."""
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_foo",
            variants=[
                VariantStatus(
                    params="[#hostpath-csi-basic#-fixture_name0]",
                    status="PASSED",
                    result=None,
                ),
                VariantStatus(
                    params="[#ocs-rbd#-fixture_name0]",
                    status="NEVER_EXECUTED",
                    result=None,
                ),
            ],
            is_two_axis=False,
            axis1_values=[],
            axis2_values=[],
        )
        parts = _render_annotated_list(summary=summary, esc=html_mod.escape)
        html = "\n".join(parts)
        assert "hostpath-csi-basic" in html
        assert "fixture_name0" not in html
        assert "matrix-table" in html

    def test_annotated_list_fallback_vertical(self) -> None:
        """Verify >10 variants fall back to vertical badge list."""
        variants = [
            VariantStatus(
                params=f"[param{i}]",
                status="PASSED",
                result=None,
            )
            for i in range(11)
        ]
        summary = ParametrizedTestSummary(
            base_test="tests/net/test_a.py::TestA::test_many",
            variants=variants,
            is_two_axis=False,
            axis1_values=[],
            axis2_values=[],
        )
        parts = _render_annotated_list(summary=summary, esc=html_mod.escape)
        html = "\n".join(parts)
        assert "param-variant" in html
        assert "badge-passed" in html
        assert "matrix-table" not in html
