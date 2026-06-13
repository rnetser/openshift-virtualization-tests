# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.rp_coverage_gate.rp_checker module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.rp_coverage_gate.rp_checker import _classify_defect, _extract_attribute, check_coverage


class TestExtractAttribute:
    def test_extract_attribute_found(self) -> None:
        """Verify attribute value is returned when key matches."""
        attributes = [
            {"key": "BUNDLE", "value": "4.19"},
            {"key": "MANUAL", "value": "true"},
        ]
        result = _extract_attribute(attributes=attributes, key="BUNDLE")
        assert result == "4.19"

    def test_extract_attribute_not_found(self) -> None:
        """Verify None returned when key is not present."""
        attributes = [{"key": "BUNDLE", "value": "4.19"}]
        result = _extract_attribute(attributes=attributes, key="MISSING")
        assert result is None


@pytest.fixture()
def mock_rp_client() -> MagicMock:
    """Create a mock RPClient for testing check_coverage."""
    return MagicMock()


class TestClassifyDefect:
    @pytest.mark.parametrize(
        ("issue_type", "expected"),
        [
            ("pb001", "Product Bug"),
            ("PB_custom", "Product Bug"),
            ("ab002", "Automation Bug"),
            ("si003", "System Issue"),
            ("ti004", "To Investigate"),
            ("nd005", "No Defect"),
            ("NOT_ISSUE", "Not Issue"),
            ("xx999", "Unknown"),
        ],
    )
    def test_classify_defect_mapping(self, issue_type: str, expected: str) -> None:
        """Verify defect type prefix maps to correct label."""
        assert _classify_defect(issue_type=issue_type) == expected


class TestCheckCoverage:
    def test_check_coverage_basic(self, mock_rp_client: MagicMock) -> None:
        """Verify result map with 1 launch and 2 test items."""
        mock_rp_client.get_launches.return_value = [
            {
                "id": 1,
                "name": "launch-1",
                "startTime": 1000,
                "attributes": [{"key": "BUNDLE", "value": "4.19.0"}],
            },
        ]
        mock_rp_client.get_test_items.return_value = [
            {
                "name": "tests.network.test_a.TestA.test_one",
                "status": "PASSED",
                "endTime": "2025-01-01T00:00:00Z",
                "attributes": [],
            },
            {
                "name": "tests.network.test_a.TestA.test_two",
                "status": "FAILED",
                "endTime": "2025-01-01T00:00:00Z",
                "attributes": [],
            },
        ]

        result_map = check_coverage(
            rp_client=mock_rp_client,
            bundle_prefix="4.19",
        )

        assert len(result_map) == 2
        assert result_map["tests.network.test_a.TestA.test_one"].status == "PASSED"
        assert result_map["tests.network.test_a.TestA.test_two"].status == "FAILED"

    def test_check_coverage_most_recent_wins(self, mock_rp_client: MagicMock) -> None:
        """Verify that when same test appears in 2 launches, newer result wins."""
        mock_rp_client.get_launches.return_value = [
            {
                "id": 1,
                "name": "older-launch",
                "startTime": 1000,
                "attributes": [{"key": "BUNDLE", "value": "4.19.0"}],
            },
            {
                "id": 2,
                "name": "newer-launch",
                "startTime": 2000,
                "attributes": [{"key": "BUNDLE", "value": "4.19.1"}],
            },
        ]

        def get_items_side_effect(launch_id: int, page_size: int = 300) -> list:
            if launch_id == 1:
                return [
                    {
                        "name": "tests.net.test_x.TestX.test_dup",
                        "status": "FAILED",
                        "endTime": "2025-01-01T00:00:00Z",
                        "attributes": [],
                    },
                ]
            return [
                {
                    "name": "tests.net.test_x.TestX.test_dup",
                    "status": "PASSED",
                    "endTime": "2025-02-01T00:00:00Z",
                    "attributes": [],
                },
            ]

        mock_rp_client.get_test_items.side_effect = get_items_side_effect

        result_map = check_coverage(
            rp_client=mock_rp_client,
            bundle_prefix="4.19",
        )

        assert result_map["tests.net.test_x.TestX.test_dup"].status == "PASSED"
        assert result_map["tests.net.test_x.TestX.test_dup"].launch_name == "newer-launch"

    def test_check_coverage_manual_source(self, mock_rp_client: MagicMock) -> None:
        """Verify source='manual' when launch has MANUAL=true attribute."""
        mock_rp_client.get_launches.return_value = [
            {
                "id": 1,
                "name": "manual-launch",
                "startTime": 1000,
                "attributes": [
                    {"key": "BUNDLE", "value": "4.19.0"},
                    {"key": "MANUAL", "value": "true"},
                ],
            },
        ]
        mock_rp_client.get_test_items.return_value = [
            {
                "name": "tests.storage.test_s.TestS.test_manual",
                "status": "PASSED",
                "endTime": "2025-01-01T00:00:00Z",
                "attributes": [],
            },
        ]

        result_map = check_coverage(
            rp_client=mock_rp_client,
            bundle_prefix="4.19",
        )

        assert result_map["tests.storage.test_s.TestS.test_manual"].source == "manual"

    def test_check_coverage_defect_extraction(self, mock_rp_client: MagicMock) -> None:
        """Verify defect type and comment extracted from item issue field."""
        mock_rp_client.get_launches.return_value = [
            {
                "id": 1,
                "name": "launch-1",
                "startTime": 1000,
                "attributes": [{"key": "BUNDLE", "value": "4.19.0"}],
            },
        ]
        mock_rp_client.get_test_items.return_value = [
            {
                "name": "tests.net.test_d.TestD.test_defect",
                "status": "FAILED",
                "endTime": "2025-01-01T00:00:00Z",
                "attributes": [],
                "issue": {
                    "issueType": "pb001",
                    "comment": "CNV-12345: VM migration fails on SRIOV",
                },
            },
        ]

        result_map = check_coverage(
            rp_client=mock_rp_client,
            bundle_prefix="4.19",
        )

        result = result_map["tests.net.test_d.TestD.test_defect"]
        assert result.defect_type == "Product Bug"
        assert result.defect_comment == "CNV-12345: VM migration fails on SRIOV"

    def test_check_coverage_empty_launches(self, mock_rp_client: MagicMock) -> None:
        """Verify empty dict returned when no launches match."""
        mock_rp_client.get_launches.return_value = []

        result_map = check_coverage(
            rp_client=mock_rp_client,
            bundle_prefix="4.99",
        )

        assert result_map == {}
