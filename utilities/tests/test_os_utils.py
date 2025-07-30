"""Unit tests for os_utils module"""

# Import from parent directory
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from os_utils import (
    RHEL_OS_MAPPING,
    WINDOWS_OS_MAPPING,
    generate_instance_type_rhel_os_matrix,
    generate_os_matrix_dict,
)


class TestGenerateOsMatrixDict:
    """Test cases for generate_os_matrix_dict function"""

    @pytest.mark.unit
    def test_generate_os_matrix_dict_rhel(self):
        """Test generating OS matrix for RHEL"""
        os_name = "rhel"
        supported_os = ["rhel-8-10", "rhel-9-5"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert isinstance(result, list)
        assert len(result) == 2

        # Check first OS
        assert result[0]["os_version"] == "8.10"
        assert result[0]["os"] == "rhel8.10"
        assert result[0]["image_name"] == "RHEL8_10_IMG"

        # Check second OS
        assert result[1]["os_version"] == "9.5"
        assert result[1]["os"] == "rhel9.5"
        assert result[1]["image_name"] == "RHEL9_5_IMG"

    @pytest.mark.unit
    def test_generate_os_matrix_dict_windows(self):
        """Test generating OS matrix for Windows"""
        os_name = "windows"
        supported_os = ["windows-11", "windows-10"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert isinstance(result, list)
        assert len(result) == 2

        # Check that Windows-specific fields are included
        for item in result:
            assert "virtio_win_image" in item
            assert "os_version" in item
            assert "template_labels" in item

    @pytest.mark.unit
    def test_generate_os_matrix_dict_empty_list(self):
        """Test generating OS matrix with empty supported OS list"""
        os_name = "rhel"
        supported_os = []

        result = generate_os_matrix_dict(os_name, supported_os)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.unit
    def test_generate_os_matrix_dict_unsupported_os(self):
        """Test generating OS matrix with unsupported OS names"""
        os_name = "rhel"
        supported_os = ["rhel-99-99", "nonexistent-os"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.unit
    def test_generate_os_matrix_dict_mixed_supported_unsupported(self):
        """Test generating OS matrix with mix of supported and unsupported OS"""
        os_name = "rhel"
        supported_os = ["rhel-8-10", "rhel-99-99", "rhel-9-5"]

        result = generate_os_matrix_dict(os_name, supported_os)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["os_version"] == "8.10"
        assert result[1]["os_version"] == "9.5"

    @pytest.mark.unit
    @patch("os_utils.Images")
    def test_generate_os_matrix_dict_with_arch_images(self, mock_images):
        """Test that arch-specific images are properly set"""
        os_name = "rhel"
        supported_os = ["rhel-8-10"]
        mock_images.Rhel.RHEL8_10 = "mocked_rhel_8_10_image"

        result = generate_os_matrix_dict(os_name, supported_os)

        assert len(result) == 1
        assert result[0]["image_path"] == "mocked_rhel_8_10_image"


class TestGenerateInstanceTypeRhelOsMatrix:
    """Test cases for generate_instance_type_rhel_os_matrix function"""

    @pytest.mark.unit
    def test_generate_instance_type_rhel_os_matrix_basic(self):
        """Test generating instance type matrix for RHEL with basic preferences"""
        preferences = ["rhel.8", "rhel.9"]

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert isinstance(result, list)
        assert len(result) == 2

        # Check structure
        for item in result:
            assert "preference" in item
            assert "os_data" in item
            assert isinstance(item["os_data"], list)

    @pytest.mark.unit
    def test_generate_instance_type_rhel_os_matrix_empty_preferences(self):
        """Test generating instance type matrix with empty preferences"""
        preferences = []

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.unit
    def test_generate_instance_type_rhel_os_matrix_invalid_preferences(self):
        """Test generating instance type matrix with invalid preferences"""
        preferences = ["invalid.preference", "rhel.8"]

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["preference"] == "rhel.8"

    @pytest.mark.unit
    @patch("os_utils.py_config")
    def test_generate_instance_type_rhel_os_matrix_with_config(self, mock_config):
        """Test generating instance type matrix with py_config"""
        preferences = ["rhel.8"]
        mock_config.__getitem__.return_value = {
            "rhel_os_dict": {
                "rhel-8-10": {"some": "data"},
            },
        }

        result = generate_instance_type_rhel_os_matrix(preferences)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["preference"] == "rhel.8"

    @pytest.mark.unit
    def test_generate_instance_type_rhel_os_matrix_rhel_versions(self):
        """Test that correct RHEL versions are selected based on preference"""
        preferences = ["rhel.8", "rhel.9"]

        result = generate_instance_type_rhel_os_matrix(preferences)

        # RHEL 8 preference should include RHEL 8.x versions
        rhel8_item = next(item for item in result if item["preference"] == "rhel.8")
        rhel8_versions = [os["os"] for os in rhel8_item["os_data"]]
        for version in rhel8_versions:
            assert version.startswith("rhel8.")

        # RHEL 9 preference should include RHEL 9.x versions
        rhel9_item = next(item for item in result if item["preference"] == "rhel.9")
        rhel9_versions = [os["os"] for os in rhel9_item["os_data"]]
        for version in rhel9_versions:
            assert version.startswith("rhel9.")

    @pytest.mark.unit
    @patch("os_utils.generate_os_matrix_dict")
    def test_generate_instance_type_rhel_os_matrix_calls_generate_os_matrix(self, mock_generate):
        """Test that generate_os_matrix_dict is called correctly"""
        preferences = ["rhel.8"]
        mock_generate.return_value = [{"os": "rhel8.10"}]

        result = generate_instance_type_rhel_os_matrix(preferences)

        # Verify generate_os_matrix_dict was called
        mock_generate.assert_called()
        assert result[0]["os_data"] == [{"os": "rhel8.10"}]

    @pytest.mark.unit
    def test_rhel_os_mapping_structure(self):
        """Test that RHEL_OS_MAPPING has expected structure"""
        # Check common fields
        assert "workload" in RHEL_OS_MAPPING
        assert "flavor" in RHEL_OS_MAPPING

        # Check OS entries
        for key, value in RHEL_OS_MAPPING.items():
            if key.startswith("rhel-"):
                assert isinstance(value, dict)
                assert "image_name" in value
                assert "os_version" in value
                assert "os" in value

    @pytest.mark.unit
    def test_windows_os_mapping_structure(self):
        """Test that WINDOWS_OS_MAPPING has expected structure"""
        # Check common fields
        assert "workload" in WINDOWS_OS_MAPPING
        assert "flavor" in WINDOWS_OS_MAPPING

        # Check Windows entries
        for key, value in WINDOWS_OS_MAPPING.items():
            if key.startswith("windows-"):
                assert isinstance(value, dict)
                assert "virtio_win_image" in value
                assert "os_version" in value
                assert "template_labels" in value
