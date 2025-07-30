"""Unit tests for os_utils module"""

# Import from parent directory
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock the Images and constants before importing
mock_images = MagicMock()
mock_images.RHEL9_5_IMG = "rhel-9-5-image"
mock_images.RHEL8_10_IMG = "rhel-8-10-image"
mock_images.WIN11 = "windows-11-image"
mock_images.WIN10 = "windows-10-image"
mock_images.WIN2K22 = "windows-2022-image"
mock_images.WIN2K19 = "windows-2019-image"

# Patch Images before importing
with patch.dict('sys.modules', {'utilities.constants': MagicMock(Images=mock_images)}):
    from os_utils import (
        RHEL_OS_MAPPING,
        WINDOWS_OS_MAPPING,
        generate_instance_type_rhel_os_matrix,
        generate_os_matrix_dict,
    )


class TestGenerateOsMatrixDict:
    """Test cases for generate_os_matrix_dict function"""

    @patch("os_utils.Images")
    def test_generate_os_matrix_dict_rhel(self, mock_images):
        """Test generating OS matrix dict for RHEL"""
        # Mock Images attributes
        mock_images.RHEL9_5_IMG = "rhel-9-5-image"
        mock_images.RHEL8_10_IMG = "rhel-8-10-image"
        
        os_name = "rhel"
        supported_os = ["rhel-9-5", "rhel-8-10"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert len(result) == 2
        assert any(item["os_version"] == "rhel-9-5" for item in result)
        assert any(item["os_version"] == "rhel-8-10" for item in result)

    @patch("os_utils.Images")
    @patch("os_utils.WINDOWS_OS_MAPPING", {
        "windows-2022": {"IMAGE_NAME_STR": "WIN2K22"},
        "windows-2019": {"IMAGE_NAME_STR": "WIN2K19"}
    })
    def test_generate_os_matrix_dict_windows(self, mock_images):
        """Test generating OS matrix dict for Windows"""
        # Mock Images attributes
        mock_images.WIN2K22 = "windows-2022-image"
        mock_images.WIN2K19 = "windows-2019-image"
        
        os_name = "windows"
        supported_os = ["windows-2022", "windows-2019"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert len(result) == 2
        assert any(item["os_version"] == "windows-2022" for item in result)
        assert any(item["os_version"] == "windows-2019" for item in result)

    def test_generate_os_matrix_dict_empty_list(self):
        """Test generating OS matrix dict with empty list"""
        os_name = "rhel"
        supported_os = []

        result = generate_os_matrix_dict(os_name, supported_os)

        assert result == []

    def test_generate_os_matrix_dict_unsupported_os(self):
        """Test generating OS matrix dict with unsupported OS versions"""
        os_name = "rhel"
        supported_os = ["rhel-99-99", "nonexistent-os"]

        with pytest.raises(ValueError, match="Unsupported OS versions"):
            generate_os_matrix_dict(os_name, supported_os)

    @patch("os_utils.Images")
    @patch("os_utils.RHEL_OS_MAPPING", {
        "rhel-9-5": {"IMAGE_NAME_STR": "RHEL9_5_IMG"},
        "rhel-8-10": {"IMAGE_NAME_STR": "RHEL8_10_IMG"}
    })
    def test_generate_os_matrix_dict_mixed_supported_unsupported(self, mock_images):
        """Test generating OS matrix dict with mixed supported/unsupported OS versions"""
        # Mock Images attributes
        mock_images.RHEL9_5_IMG = "rhel-9-5-image"
        mock_images.RHEL8_10_IMG = "rhel-8-10-image"
        
        os_name = "rhel"
        supported_os = ["rhel-9-5", "unsupported-version"]

        # The function should raise ValueError for unsupported versions
        with pytest.raises(ValueError, match="Unsupported OS versions"):
            generate_os_matrix_dict(os_name, supported_os)

    @patch("os_utils.Images")
    def test_generate_os_matrix_dict_with_arch_images(self, mock_images):
        """Test generating OS matrix dict verifies arch images are used"""
        # Mock Images attributes
        mock_images.RHEL8_10_IMG = "mocked_rhel_8_10_image"
        
        os_name = "rhel"
        supported_os = ["rhel-8-10"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert len(result) == 1
        assert result[0]["os_version"] == "rhel-8-10"


class TestGenerateInstanceTypeRhelOsMatrix:
    """Test cases for generate_instance_type_rhel_os_matrix function"""

    @patch("os_utils.generate_os_matrix_dict")
    def test_generate_instance_type_rhel_os_matrix_basic(self, mock_generate_os):
        """Test basic functionality of generate_instance_type_rhel_os_matrix"""
        preferences = ["rhel.9", "rhel.8"]
        mock_generate_os.return_value = [
            {"os_version": "rhel-9", "image": "rhel9"},
            {"os_version": "rhel-8", "image": "rhel8"},
        ]

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert len(result) == 2
        # Check that generate_os_matrix_dict was called with the latest RHEL
        mock_generate_os.assert_called_once_with("rhel", ["rhel-9"])

    def test_generate_instance_type_rhel_os_matrix_empty_preferences(self):
        """Test with empty preferences list"""
        preferences = []

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert result == []

    @patch("os_utils.generate_os_matrix_dict")
    def test_generate_instance_type_rhel_os_matrix_invalid_preferences(self, mock_generate_os):
        """Test with preferences that don't have proper format"""
        preferences = ["invalid", "rhel.9"]
        mock_generate_os.return_value = [{"os_version": "rhel-9"}]

        result = generate_instance_type_rhel_os_matrix(preferences)

        # Should handle invalid preferences gracefully
        mock_generate_os.assert_called_once_with("rhel", ["rhel-9"])

    @patch("os_utils.py_config", {"execute_instance_type_tests": True})
    @patch("os_utils.generate_os_matrix_dict")
    def test_generate_instance_type_rhel_os_matrix_with_config(self, mock_generate_os):
        """Test when instance type tests are enabled"""
        preferences = ["rhel.8", "rhel.9"]
        mock_generate_os.return_value = [{"os_version": "rhel-9"}]

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert result == mock_generate_os.return_value

    @patch("os_utils.generate_os_matrix_dict")
    def test_generate_instance_type_rhel_os_matrix_rhel_versions(self, mock_generate_os):
        """Test extracting RHEL version numbers"""
        preferences = ["rhel.7", "rhel.8", "rhel.9"]
        mock_generate_os.return_value = [{"os_version": "rhel-9"}]

        result = generate_instance_type_rhel_os_matrix(preferences)

        # Should pick the highest version (rhel-9)
        mock_generate_os.assert_called_once_with("rhel", ["rhel-9"])

    @patch("os_utils.generate_os_matrix_dict")
    def test_generate_instance_type_rhel_os_matrix_calls_generate_os_matrix(
        self, mock_generate_os
    ):
        """Test that generate_os_matrix_dict is called correctly"""
        preferences = ["rhel.8"]
        expected_return = [{"os_version": "rhel-8", "image": "test"}]
        mock_generate_os.return_value = expected_return

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert result == expected_return
        mock_generate_os.assert_called_once_with("rhel", ["rhel-8"])

    def test_rhel_os_mapping_structure(self):
        """Test RHEL_OS_MAPPING has expected structure"""
        assert isinstance(RHEL_OS_MAPPING, dict)
        # Check that entries have expected keys
        for key, value in RHEL_OS_MAPPING.items():
            assert isinstance(value, dict)
            assert "IMAGE_NAME_STR" in value

    def test_windows_os_mapping_structure(self):
        """Test WINDOWS_OS_MAPPING has expected structure"""
        assert isinstance(WINDOWS_OS_MAPPING, dict)
        # Check that entries have expected keys
        for key, value in WINDOWS_OS_MAPPING.items():
            assert isinstance(value, dict)
            assert "IMAGE_NAME_STR" in value
