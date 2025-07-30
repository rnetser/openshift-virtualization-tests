"""Unit tests for bitwarden module"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from bitwarden import (
    get_all_cnv_tests_secrets,
    get_bitwarden_secrets_client,
    get_cnv_tests_secret_by_name,
)


class TestGetBitwardenSecretsClient:
    """Test cases for get_bitwarden_secrets_client function"""

    @patch("bitwarden.BitwardenClient")
    def test_get_bitwarden_secrets_client_success(self, mock_client_class):
        """Test successful Bitwarden client creation"""
        with patch.dict(os.environ, {"BW_ACCESS_TOKEN": "test-token"}):
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            result = get_bitwarden_secrets_client()

            assert result == mock_client
            mock_client_class.assert_called_once_with(
                settings={"api_url": "https://vault.bitwarden.com/api"}
            )
            mock_client.access_token_login.assert_called_once_with("test-token")

    def test_get_bitwarden_secrets_client_no_token(self):
        """Test when BW_ACCESS_TOKEN is not set"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                get_bitwarden_secrets_client()


class TestGetAllCnvTestsSecrets:
    """Test cases for get_all_cnv_tests_secrets function"""

    def test_get_all_cnv_tests_secrets(self):
        """Test getting all CNV test secrets"""
        mock_client = MagicMock()
        
        # Mock secret response
        mock_secret = MagicMock()
        mock_secret.key = "test-secret"
        mock_secret.value = "secret-value"
        mock_secret.note = "Test note"
        
        mock_client.secrets.list.return_value.data.data = [mock_secret]

        result = get_all_cnv_tests_secrets(mock_client)

        assert len(result) == 1
        assert result[0] == mock_secret
        mock_client.secrets.list.assert_called_once()


class TestGetCnvTestsSecretByName:
    """Test cases for get_cnv_tests_secret_by_name function"""

    @patch("bitwarden.get_bitwarden_secrets_client")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_found(self, mock_get_all, mock_get_client):
        """Test getting secret by name when it exists"""
        # Mock client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock secrets
        mock_secret1 = MagicMock()
        mock_secret1.key = "secret1"
        mock_secret1.value = "value1"
        
        mock_secret2 = MagicMock()
        mock_secret2.key = "secret2"
        mock_secret2.value = "value2"
        
        mock_get_all.return_value = [mock_secret1, mock_secret2]

        result = get_cnv_tests_secret_by_name("secret2")

        assert result == "value2"

    @patch("bitwarden.get_bitwarden_secrets_client")
    @patch("bitwarden.get_all_cnv_tests_secrets")
    def test_get_cnv_tests_secret_by_name_not_found(self, mock_get_all, mock_get_client):
        """Test getting secret by name when it doesn't exist"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_secret = MagicMock()
        mock_secret.key = "existing-secret"
        mock_secret.value = "value"
        
        mock_get_all.return_value = [mock_secret]

        with pytest.raises(ValueError, match="The secret nonexistent was not found"):
            get_cnv_tests_secret_by_name("nonexistent") 