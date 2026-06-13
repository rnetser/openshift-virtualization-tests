# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.rp_coverage_gate.report module."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.rp_coverage_gate.report import (
    CoverageReport,
    _get_team_from_node_id,
    analyze_coverage,
    format_html_report,
    format_json_report,
    format_text_report,
)
from scripts.rp_coverage_gate.rp_checker import ItemResult


def _make_result(
    name: str,
    status: str = "PASSED",
    last_executed: str = "",
    bundle: str = "4.19.0",
    launch_name: str = "launch-1",
    polarion_id: str | None = None,
    source: str = "automated",
) -> ItemResult:
    """Helper to create an ItemResult with sensible defaults."""
    return ItemResult(
        name=name,
        status=status,
        last_executed=last_executed,
        bundle=bundle,
        launch_name=launch_name,
        polarion_id=polarion_id,
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
        )

        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)

        assert "GATE: PASSED" in html
        assert "badge-pass" in html
        assert "FAILED TESTS" not in html
        assert "MANUAL TESTS" not in html

    def test_html_report_gating_section(self) -> None:
        """Verify GATING section appears in HTML when gating gaps exist."""
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
        )

        html = format_html_report(report=report, bundle_prefix="v4.22.0", stale_days=30)

        assert "GATING" in html
        assert "test_gated" in html
        assert "section-gating" in html
