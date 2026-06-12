"""Tests for scripts.rp_utils.rp_client module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.rp_utils.rp_client import RPClient, _utc_now_iso


@pytest.fixture()
def rp_client() -> RPClient:
    """Create an RPClient instance with test credentials."""
    return RPClient(
        base_url="https://rp.example.com",
        project="test-project",
        token="test-token",
    )


class TestUtcNowIso:
    def test_utc_now_iso(self) -> None:
        """Verify _utc_now_iso returns string ending with Z."""
        result = _utc_now_iso()
        assert isinstance(result, str)
        assert result.endswith("Z")


class TestApiUrl:
    def test_api_url(self, rp_client: RPClient) -> None:
        """Verify _api_url builds the correct URL from base, project, and path."""
        url = rp_client._api_url(path="launch")
        assert url == "https://rp.example.com/api/v1/test-project/launch"


class TestCreateLaunch:
    def test_create_launch(self, rp_client: RPClient) -> None:
        """Verify create_launch sends correct POST body and returns launch ID."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 42}
        mock_response.raise_for_status = MagicMock()

        with patch.object(rp_client.session, "post", return_value=mock_response) as mock_post:
            result = rp_client.create_launch(
                name="test-launch",
                attributes=[{"key": "BUNDLE", "value": "4.19"}],
                description="my desc",
            )

        assert result == 42
        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs["json"]
        assert body["name"] == "test-launch"
        assert body["attributes"] == [{"key": "BUNDLE", "value": "4.19"}]
        assert body["description"] == "my desc"
        assert body["mode"] == "DEFAULT"

    def test_create_launch_http_error(self, rp_client: RPClient) -> None:
        """Verify create_launch raises HTTPError on 500 response."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

        with patch.object(rp_client.session, "post", return_value=mock_response):
            with pytest.raises(requests.HTTPError, match="500 Server Error"):
                rp_client.create_launch(
                    name="fail-launch",
                    attributes=[],
                )


class TestFinishLaunch:
    def test_finish_launch(self, rp_client: RPClient) -> None:
        """Verify finish_launch sends PUT to the correct endpoint."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch.object(rp_client.session, "put", return_value=mock_response) as mock_put:
            rp_client.finish_launch(launch_id=99)

        call_kwargs = mock_put.call_args
        url = call_kwargs.kwargs["url"]
        assert url.endswith("/launch/99/finish")


class TestCreateTestItem:
    def test_create_test_item_without_attributes(self, rp_client: RPClient) -> None:
        """Verify create_test_item omits attributes key when not provided."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 7}
        mock_response.raise_for_status = MagicMock()

        with patch.object(rp_client.session, "post", return_value=mock_response) as mock_post:
            rp_client.create_test_item(
                launch_id=1,
                name="test_foo",
                status="passed",
            )

        body = mock_post.call_args.kwargs["json"]
        assert "attributes" not in body

    def test_create_test_item_with_attributes(self, rp_client: RPClient) -> None:
        """Verify create_test_item includes attributes when provided."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 8}
        mock_response.raise_for_status = MagicMock()

        attrs = [{"key": "polarion-testcase-id", "value": "CNV-1234"}]
        with patch.object(rp_client.session, "post", return_value=mock_response) as mock_post:
            rp_client.create_test_item(
                launch_id=1,
                name="test_bar",
                status="failed",
                attributes=attrs,
            )

        body = mock_post.call_args.kwargs["json"]
        assert body["attributes"] == attrs
        assert body["status"] == "FAILED"


class TestGetLaunches:
    def test_get_launches(self, rp_client: RPClient) -> None:
        """Verify get_launches paginates across 2 pages and returns all items."""
        page1_response = MagicMock()
        page1_response.json.return_value = {
            "content": [{"id": 1, "name": "launch-1"}],
            "page": {"totalPages": 2},
        }
        page1_response.raise_for_status = MagicMock()

        page2_response = MagicMock()
        page2_response.json.return_value = {
            "content": [{"id": 2, "name": "launch-2"}],
            "page": {"totalPages": 2},
        }
        page2_response.raise_for_status = MagicMock()

        with patch.object(rp_client.session, "get", side_effect=[page1_response, page2_response]):
            launches = rp_client.get_launches(bundle_prefix="4.19")

        assert len(launches) == 2
        assert launches[0]["id"] == 1
        assert launches[1]["id"] == 2

    def test_paginate_empty_results(self, rp_client: RPClient) -> None:
        """Verify pagination with empty content returns empty list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [],
            "page": {"totalPages": 1},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(rp_client.session, "get", return_value=mock_response):
            launches = rp_client.get_launches(bundle_prefix="4.99")

        assert launches == []


class TestGetTestItems:
    def test_get_test_items(self, rp_client: RPClient) -> None:
        """Verify get_test_items passes correct filter params."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"id": 10, "name": "test_foo"}],
            "page": {"totalPages": 1},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(rp_client.session, "get", return_value=mock_response) as mock_get:
            items = rp_client.get_test_items(launch_id=5)

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs["params"]
        assert params["filter.eq.launchId"] == 5
        assert len(items) == 1


class TestUpdateLaunch:
    def test_update_launch(self, rp_client: RPClient) -> None:
        """Verify update_launch sends correct PUT body."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        attrs = [{"key": "BUNDLE", "value": "4.20"}]
        with patch.object(rp_client.session, "put", return_value=mock_response) as mock_put:
            rp_client.update_launch(
                launch_id=10,
                attributes=attrs,
                description="updated",
            )

        call_kwargs = mock_put.call_args
        body = call_kwargs.kwargs["json"]
        assert body["attributes"] == attrs
        assert body["description"] == "updated"
        assert body["mode"] == "DEFAULT"
