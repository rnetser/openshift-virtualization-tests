"""Tests for scripts.rp_coverage_gate.report module."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.rp_coverage_gate.report import (
    CoverageReport,
    _get_team_from_node_id,
    analyze_coverage,
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
