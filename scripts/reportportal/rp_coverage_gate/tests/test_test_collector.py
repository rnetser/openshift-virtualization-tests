# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.reportportal.rp_coverage_gate.test_collector quarantine scanning."""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.reportportal.rp_coverage_gate.test_collector import scan_quarantined_tests


class TestScanQuarantinedTests:
    def test_xfail_quarantine_detected(self, tmp_path: Path) -> None:
        """Verify xfail quarantine with QUARANTINED reason is detected."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text(
            textwrap.dedent("""
            import pytest
            QUARANTINED = "QUARANTINED"

            @pytest.mark.xfail(reason=f"{QUARANTINED}: tracked in CNV-12345", run=False)
            def test_broken():
                pass
        """)
        )

        results = scan_quarantined_tests(tests_dir=tmp_path)
        assert len(results) == 1
        assert "test_broken" in results[0].node_id
        assert results[0].jira == "CNV-12345"

    def test_jira_run_false_detected(self, tmp_path: Path) -> None:
        """Verify jira marker with run=False is detected."""
        test_file = tmp_path / "test_jira.py"
        test_file.write_text(
            textwrap.dedent("""
            import pytest

            @pytest.mark.jira("CNV-99999", run=False)
            def test_blocked():
                pass
        """)
        )

        results = scan_quarantined_tests(tests_dir=tmp_path)
        assert len(results) == 1
        assert results[0].jira == "CNV-99999"

    def test_class_level_quarantine_expands_to_methods(self, tmp_path: Path) -> None:
        """Verify class-level quarantine generates entries for all test methods."""
        test_file = tmp_path / "test_class.py"
        test_file.write_text(
            textwrap.dedent("""
            import pytest
            QUARANTINED = "QUARANTINED"

            @pytest.mark.xfail(reason=f"{QUARANTINED}: class-wide issue CNV-11111", run=False)
            class TestBroken:
                def test_one(self):
                    pass

                def test_two(self):
                    pass

                def helper_not_test(self):
                    pass
        """)
        )

        results = scan_quarantined_tests(tests_dir=tmp_path)
        assert len(results) == 2
        node_ids = {r.node_id for r in results}
        assert any("test_one" in nid for nid in node_ids)
        assert any("test_two" in nid for nid in node_ids)
        assert not any("helper" in nid for nid in node_ids)

    def test_non_quarantine_xfail_ignored(self, tmp_path: Path) -> None:
        """Verify xfail without quarantine reason is not detected."""
        test_file = tmp_path / "test_normal.py"
        test_file.write_text(
            textwrap.dedent("""
            import pytest

            @pytest.mark.xfail(reason="known flaky", run=False)
            def test_flaky():
                pass
        """)
        )

        results = scan_quarantined_tests(tests_dir=tmp_path)
        assert len(results) == 0

    def test_jira_without_run_false_ignored(self, tmp_path: Path) -> None:
        """Verify jira marker without run=False is not detected."""
        test_file = tmp_path / "test_jira_active.py"
        test_file.write_text(
            textwrap.dedent("""
            import pytest

            @pytest.mark.jira("CNV-55555")
            def test_tracked():
                pass
        """)
        )

        results = scan_quarantined_tests(tests_dir=tmp_path)
        assert len(results) == 0

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Verify empty directory returns no results."""
        results = scan_quarantined_tests(tests_dir=tmp_path)
        assert len(results) == 0
