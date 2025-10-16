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
    get_cnv_tests_secret_by_name,
)

from utilities.exceptions import MissingEnvironmentVariableError


class TestGetAllCnvTestsSecrets:
    """Test cases for get_all_cnv_tests_secrets function"""

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets(self, mock_get, mock_post):
        """Test getting all CNV test secrets"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
        ):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {
                "access_token": "test-token",
                "expires_in": 3600,
            }
            mock_token_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_token_response

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
            # Verify request was made correctly
            assert mock_get.call_count == 1
            call_args = mock_get.call_args
            assert call_args.kwargs["url"] == "https://api.bitwarden.com/organizations/test-org/secrets"
            assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
            assert call_args.kwargs["timeout"] == 30
            assert call_args.kwargs["verify"] is True

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets_http_error(self, mock_get, mock_post):
        """Test HTTP error handling for get_all_cnv_tests_secrets"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
        ):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {"access_token": "test-token", "expires_in": 3600}
            mock_token_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_token_response

            # Mock HTTP error
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
            mock_get.return_value = mock_response

            with pytest.raises(requests.HTTPError):
                get_all_cnv_tests_secrets()

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets_network_error(self, mock_get, mock_post):
        """Test network error handling for get_all_cnv_tests_secrets"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
        ):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {"access_token": "test-token", "expires_in": 3600}
            mock_token_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_token_response

            # Mock network error
            mock_get.side_effect = requests.ConnectionError("Network error")

            with pytest.raises(requests.ConnectionError):
                get_all_cnv_tests_secrets()

    def test_get_all_cnv_tests_secrets_missing_organization_id(self):
        """Test error when ORGANIZATION_ID is not set"""
        with patch.dict(
            os.environ,
            {"BITWARDEN_CLIENT_ID": "client-id", "BITWARDEN_CLIENT_SECRET": "client-secret"},
            clear=True,
        ):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            with pytest.raises(
                MissingEnvironmentVariableError,
                match="Bitwarden client needs ORGANIZATION_ID environment variables set up",
            ):
                get_all_cnv_tests_secrets()

    def test_get_all_cnv_tests_secrets_missing_client_credentials(self):
        """Test error when BITWARDEN_CLIENT_ID or BITWARDEN_CLIENT_SECRET are not set"""
        with patch.dict(os.environ, {"ORGANIZATION_ID": "test-org"}, clear=True):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            with pytest.raises(
                MissingEnvironmentVariableError,
                match="Bitwarden client needs BITWARDEN_CLIENT_ID and BITWARDEN_CLIENT_SECRET environment variables set up",
            ):
                get_all_cnv_tests_secrets()

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    def test_get_all_cnv_tests_secrets_with_oauth(self, mock_get, mock_post):
        """Test getting secrets using OAuth2 client credentials flow"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
            clear=True,
        ):
            # Clear cache before test
            get_all_cnv_tests_secrets.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {
                "access_token": "oauth-token-12345",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
            mock_token_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_token_response

            # Mock API response
            mock_api_response = MagicMock()
            mock_api_response.json.return_value = {
                "data": [
                    {"key": "test-secret-1", "id": "uuid-1"},
                ]
            }
            mock_api_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_api_response

            result = get_all_cnv_tests_secrets()

            assert result == {"test-secret-1": "uuid-1"}

            # Verify OAuth token request
            assert mock_post.call_count == 1
            token_call_args = mock_post.call_args
            assert token_call_args.args[0] == "https://identity.bitwarden.com/connect/token"
            assert token_call_args.kwargs["data"]["grant_type"] == "client_credentials"
            assert token_call_args.kwargs["data"]["scope"] == "api.organization"
            assert token_call_args.kwargs["data"]["client_id"] == "client-id"
            assert token_call_args.kwargs["data"]["client_secret"] == "client-secret"

            # Verify API request used OAuth token
            assert mock_get.call_count == 1
            api_call_args = mock_get.call_args
            assert api_call_args.kwargs["headers"]["Authorization"] == "Bearer oauth-token-12345"


class TestGetCnvTestsSecretByName:
    """Test cases for get_cnv_tests_secret_by_name function"""

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_found(self, mock_get_all, mock_requests_get, mock_requests_post):
        """Test getting secret by name when it exists"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
        ):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {"access_token": "test-token", "expires_in": 3600}
            mock_token_response.raise_for_status = MagicMock()
            mock_requests_post.return_value = mock_token_response

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
            # Verify request was made correctly
            assert mock_requests_get.call_count == 1
            call_args = mock_requests_get.call_args
            assert call_args.kwargs["url"] == "https://api.bitwarden.com/secrets/uuid-2"
            assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
            assert call_args.kwargs["timeout"] == 30
            assert call_args.kwargs["verify"] is True

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

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_invalid_json(self, mock_get_all, mock_requests_get, mock_requests_post):
        """Test getting secret by name when JSON is invalid"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
        ):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {"access_token": "test-token", "expires_in": 3600}
            mock_token_response.raise_for_status = MagicMock()
            mock_requests_post.return_value = mock_token_response

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

    @patch("bitwarden.requests.post")
    @patch("bitwarden.requests.get")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_http_error(self, mock_get_all, mock_requests_get, mock_requests_post):
        """Test HTTP error handling for get_cnv_tests_secret_by_name"""
        with patch.dict(
            os.environ,
            {
                "ORGANIZATION_ID": "test-org",
                "BITWARDEN_CLIENT_ID": "client-id",
                "BITWARDEN_CLIENT_SECRET": "client-secret",
            },
        ):
            # Clear cache before test
            get_cnv_tests_secret_by_name.cache_clear()

            # Clear OAuth token cache
            import bitwarden

            bitwarden._oauth_token_cache.clear()

            # Mock OAuth token response
            mock_token_response = MagicMock()
            mock_token_response.json.return_value = {"access_token": "test-token", "expires_in": 3600}
            mock_token_response.raise_for_status = MagicMock()
            mock_requests_post.return_value = mock_token_response

            # Mock secrets dictionary
            mock_get_all.return_value = {
                "secret1": "uuid-1",
            }

            # Mock HTTP error
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
            mock_requests_get.return_value = mock_response

            with pytest.raises(requests.HTTPError):
                get_cnv_tests_secret_by_name("secret1")
