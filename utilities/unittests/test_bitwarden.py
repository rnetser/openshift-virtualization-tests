# Generated using Claude cli

"""Unit tests for bitwarden module"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from bitwarden import (
    get_all_cnv_tests_secrets,
    get_bitwarden_secrets_client,
    get_cnv_tests_secret_by_name,
)

from utilities.exceptions import MissingEnvironmentVariableError


class TestGetBitwardenSecretsClient:
    """Test cases for get_bitwarden_secrets_client function"""

    def test_get_bitwarden_secrets_client_success(self):
        """Test successful Bitwarden client headers creation"""
        with patch.dict(os.environ, {"ACCESS_TOKEN": "test-token", "ORGANIZATION_ID": "test-org"}):
            result = get_bitwarden_secrets_client()

            assert result == {
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            }

    def test_get_bitwarden_secrets_client_no_token(self):
        """Test when ACCESS_TOKEN or ORGANIZATION_ID is not set"""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(
                MissingEnvironmentVariableError,
                match="Bitwarden client needs ORGANIZATION_ID and ACCESS_TOKEN environment variables set up",
            ),
        ):
            get_bitwarden_secrets_client()


class TestGetAllCnvTestsSecrets:
    """Test cases for get_all_cnv_tests_secrets function"""

    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets(self, mock_get):
        """Test getting all CNV test secrets"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Mock API response
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [
                    {"key": "test-secret-1", "id": "uuid-1"},
                    {"key": "test-secret-2", "id": "uuid-2"},
                ]
            }
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = get_all_cnv_tests_secrets()

            assert len(result) == 2
            assert result == {"test-secret-1": "uuid-1", "test-secret-2": "uuid-2"}
            mock_get.assert_called_once_with(
                "https://api.bitwarden.com/organizations/test-org/secrets",
                headers={
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
                timeout=30,
                verify=True,
            )

    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets_http_error(self, mock_get):
        """Test HTTP error handling for get_all_cnv_tests_secrets"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Mock HTTP error
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
            mock_get.return_value = mock_response

            with pytest.raises(
                MissingEnvironmentVariableError,
                match="Failed to access Bitwarden API \\(HTTP 401\\)",
            ):
                get_all_cnv_tests_secrets()

    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets_network_error(self, mock_get):
        """Test network error handling for get_all_cnv_tests_secrets"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Mock network error
            mock_get.side_effect = requests.ConnectionError("Network error")

            with pytest.raises(
                MissingEnvironmentVariableError,
                match="Failed to connect to Bitwarden API",
            ):
                get_all_cnv_tests_secrets()


class TestGetCnvTestsSecretByName:
    """Test cases for get_cnv_tests_secret_by_name function"""

    @patch("bitwarden.requests.get")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_found(self, mock_get_all, mock_requests_get):
        """Test getting secret by name when it exists"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Mock secrets dictionary
            mock_get_all.return_value = {
                "secret1": "uuid-1",
                "secret2": "uuid-2",
            }

            # Mock the API response for getting specific secret
            mock_response = MagicMock()
            mock_response.json.return_value = {"value": json.dumps({"key": "value2"})}
            mock_response.raise_for_status = MagicMock()
            mock_requests_get.return_value = mock_response

            result = get_cnv_tests_secret_by_name("secret2")

            assert result == {"key": "value2"}
            mock_requests_get.assert_called_once_with(
                "https://api.bitwarden.com/secrets/uuid-2",
                headers={
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
                timeout=30,
                verify=True,
            )

    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_not_found(self, mock_get_all):
        """Test getting secret by name when it doesn't exist"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Mock secrets dictionary without the requested secret
            mock_get_all.return_value = {
                "existing-secret": "uuid-1",
            }

            with pytest.raises(
                ValueError,
                match="Secret 'nonexistent' not found in Bitwarden",
            ):
                get_cnv_tests_secret_by_name("nonexistent")

    @patch("bitwarden.requests.get")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_invalid_json(self, mock_get_all, mock_requests_get):
        """Test getting secret by name when JSON is invalid"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Mock secrets dictionary
            mock_get_all.return_value = {
                "invalid-secret": "uuid-1",
            }

            # Mock the API response with invalid JSON
            mock_response = MagicMock()
            mock_response.json.return_value = {"value": "invalid json {"}
            mock_response.raise_for_status = MagicMock()
            mock_requests_get.return_value = mock_response

            with pytest.raises(
                ValueError,
                match="Invalid JSON in secret 'invalid-secret'",
            ):
                get_cnv_tests_secret_by_name("invalid-secret")

    @patch("bitwarden.requests.get")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_http_error(self, mock_get_all, mock_requests_get):
        """Test HTTP error handling for get_cnv_tests_secret_by_name"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org", "ACCESS_TOKEN": "test-token"}):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Mock secrets dictionary
            mock_get_all.return_value = {
                "secret1": "uuid-1",
            }

            # Mock HTTP error
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
            mock_requests_get.return_value = mock_response

            with pytest.raises(
                MissingEnvironmentVariableError,
                match="Failed to access Bitwarden API \\(HTTP 404\\)",
            ):
                get_cnv_tests_secret_by_name("secret1")
