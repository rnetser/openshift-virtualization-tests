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
