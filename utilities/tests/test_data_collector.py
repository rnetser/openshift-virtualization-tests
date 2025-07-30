"""Unit tests for data_collector module"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# Mock modules to break circular imports
sys.modules["utilities.hco"] = MagicMock()
sys.modules["utilities.infra"] = MagicMock()

from utilities.data_collector import (
    BASE_DIRECTORY_NAME,
    get_data_collector_base,
    get_data_collector_base_directory,
    get_data_collector_dir,
    prepare_pytest_item_data_dir,
    set_data_collector_directory,
    set_data_collector_values,
    write_to_file,
)


class TestGetDataCollectorBase:
    """Test cases for get_data_collector_base function"""

    def test_get_data_collector_base_with_base_dir(self):
        """Test get_data_collector_base with explicit base_dir"""
        base_dir = "/custom/path"
        result = get_data_collector_base(base_dir=base_dir)
        expected = "/custom/path/"
        assert result == expected

    def test_get_data_collector_base_with_base_dir_trailing_slash(self):
        """Test get_data_collector_base with base_dir that already has trailing slash"""
        base_dir = "/custom/path/"
        result = get_data_collector_base(base_dir=base_dir)
        expected = "/custom/path/"
        assert result == expected

    @patch.dict(os.environ, {"CNV_TESTS_CONTAINER": "true"})
    def test_get_data_collector_base_container_env(self):
        """Test get_data_collector_base in container environment"""
        # Clear cache to ensure fresh execution
        get_data_collector_base.cache_clear()
        result = get_data_collector_base()
        expected = "/data/"
        assert result == expected

    @patch.dict(os.environ, {}, clear=True)
    @patch("os.getcwd")
    def test_get_data_collector_base_current_working_directory(self, mock_getcwd):
        """Test get_data_collector_base uses current working directory"""
        mock_getcwd.return_value = "/current/working/dir"
        # Clear cache to ensure fresh execution
        get_data_collector_base.cache_clear()
        result = get_data_collector_base()
        expected = "/current/working/dir/"
        assert result == expected

    @patch("os.path.expanduser")
    @patch("os.path.normpath")
    def test_get_data_collector_base_path_normalization(self, mock_normpath, mock_expanduser):
        """Test get_data_collector_base normalizes and expands paths"""
        mock_expanduser.return_value = "/expanded/path"
        mock_normpath.return_value = "/normalized/path"

        # Clear cache to ensure fresh execution
        get_data_collector_base.cache_clear()
        result = get_data_collector_base(base_dir="~/test/path")

        mock_expanduser.assert_called_once_with("~/test/path")
        mock_normpath.assert_called_once_with("/expanded/path")
        assert result == "/normalized/path/"

    def test_get_data_collector_base_cached_result(self):
        """Test that get_data_collector_base returns cached results"""
        # Clear cache first
        get_data_collector_base.cache_clear()

        with patch("os.getcwd", return_value="/test/dir"):
            result1 = get_data_collector_base()
            result2 = get_data_collector_base()

            assert result1 == result2
            assert result1 == "/test/dir/"


class TestGetDataCollectorBaseDirectory:
    """Test cases for get_data_collector_base_directory function"""

    @patch(
        "utilities.data_collector.py_config",
        {"data_collector": {"data_collector_base_directory": "/test/base/dir"}},
    )
    def test_get_data_collector_base_directory(self):
        """Test get_data_collector_base_directory returns correct value from config"""
        result = get_data_collector_base_directory()
        assert result == "/test/base/dir"


class TestSetDataCollectorValues:
    """Test cases for set_data_collector_values function"""

    @patch("utilities.data_collector.py_config", {})
    @patch("utilities.data_collector.get_data_collector_base")
    def test_set_data_collector_values_default(self, mock_get_base):
        """Test set_data_collector_values with default parameters"""
        mock_get_base.return_value = "/test/base/"

        result = set_data_collector_values()

        mock_get_base.assert_called_once_with(base_dir=None)
        expected = {"data_collector_base_directory": "/test/base/tests-collected-info"}
        assert result == expected

    @patch("utilities.data_collector.py_config", {})
    @patch("utilities.data_collector.get_data_collector_base")
    def test_set_data_collector_values_with_base_dir(self, mock_get_base):
        """Test set_data_collector_values with custom base_dir"""
        mock_get_base.return_value = "/custom/base/"

        result = set_data_collector_values(base_dir="/custom/path")

        mock_get_base.assert_called_once_with(base_dir="/custom/path")
        expected = {"data_collector_base_directory": "/custom/base/tests-collected-info"}
        assert result == expected


class TestSetDataCollectorDirectory:
    """Test cases for set_data_collector_directory function"""

    @patch("utilities.data_collector.py_config", {"data_collector": {}})
    @patch("utilities.data_collector.prepare_pytest_item_data_dir")
    def test_set_data_collector_directory(self, mock_prepare_dir):
        """Test set_data_collector_directory sets collector_directory"""
        mock_prepare_dir.return_value = "/prepared/dir"
        mock_item = MagicMock()
        directory_path = "/test/directory"

        set_data_collector_directory(mock_item, directory_path)

        mock_prepare_dir.assert_called_once_with(item=mock_item, output_dir=directory_path)
        from utilities.data_collector import py_config

        assert py_config["data_collector"]["collector_directory"] == "/prepared/dir"


class TestGetDataCollectorDir:
    """Test cases for get_data_collector_dir function"""

    @patch(
        "utilities.data_collector.py_config",
        {
            "data_collector": {
                "collector_directory": "/specific/collector/dir",
                "data_collector_base_directory": "/base/dir",
            },
        },
    )
    def test_get_data_collector_dir_with_collector_directory(self):
        """Test get_data_collector_dir returns collector_directory when set"""
        result = get_data_collector_dir()
        assert result == "/specific/collector/dir"

    @patch(
        "utilities.data_collector.py_config",
        {
            "data_collector": {
                "data_collector_base_directory": "/base/dir",
            },
        },
    )
    def test_get_data_collector_dir_fallback_to_base(self):
        """Test get_data_collector_dir falls back to base directory"""
        result = get_data_collector_dir()
        assert result == "/base/dir"


class TestWriteToFile:
    """Test cases for write_to_file function"""

    def test_write_to_file_success(self):
        """Test write_to_file writes content successfully"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_name = "test_file.txt"
            content = "Test content"

            write_to_file(file_name, content, tmp_dir)

            file_path = os.path.join(tmp_dir, file_name)
            assert os.path.exists(file_path)

            with open(file_path) as f:
                assert f.read() == content

    def test_write_to_file_creates_directory(self):
        """Test write_to_file creates directory if it doesn't exist"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sub_dir = os.path.join(tmp_dir, "subdir", "nested")
            file_name = "test_file.txt"
            content = "Test content"

            write_to_file(file_name, content, sub_dir)

            assert os.path.exists(sub_dir)
            file_path = os.path.join(sub_dir, file_name)
            assert os.path.exists(file_path)

    def test_write_to_file_append_mode(self):
        """Test write_to_file in append mode"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_name = "test_file.txt"
            initial_content = "Initial content\n"
            append_content = "Appended content\n"

            # Write initial content
            write_to_file(file_name, initial_content, tmp_dir)
            # Append more content
            write_to_file(file_name, append_content, tmp_dir, mode="a")

            file_path = os.path.join(tmp_dir, file_name)
            with open(file_path) as f:
                result = f.read()
                assert result == initial_content + append_content

    @patch("utilities.data_collector.LOGGER")
    @patch("builtins.open", side_effect=OSError("Permission denied"))
    def test_write_to_file_exception_handling(self, mock_open, mock_logger):
        """Test write_to_file handles exceptions gracefully"""
        file_name = "test_file.txt"
        content = "Test content"
        base_directory = "/test/dir"

        # Should not raise exception, but log warning
        write_to_file(file_name, content, base_directory)

        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert "Failed to write extras to file" in warning_call
        assert "/test/dir/test_file.txt" in warning_call

    def test_write_to_file_with_json_content(self):
        """Test write_to_file with JSON content"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_name = "test_data.json"
            test_data = {"key": "value", "number": 42}
            content = json.dumps(test_data, indent=2)

            write_to_file(file_name, content, tmp_dir)

            file_path = os.path.join(tmp_dir, file_name)
            with open(file_path) as f:
                loaded_data = json.load(f)
                assert loaded_data == test_data


class TestPreparePytestItemDataDir:
    """Test cases for prepare_pytest_item_data_dir function"""

    def test_prepare_pytest_item_data_dir_basic(self):
        """Test prepare_pytest_item_data_dir creates correct directory structure"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Mock pytest item
            mock_item = MagicMock()
            mock_item.cls.__name__ = "TestClass"
            mock_item.name = "test_method"
            mock_item.fspath.dirname = "/path/to/tests/unit"
            mock_item.fspath.basename = "test_example.py"

            # Mock session config
            mock_session = MagicMock()
            mock_session.config.inicfg.get.return_value = "tests"
            mock_item.session = mock_session

            with patch("os.path.split", return_value=("", "unit")):
                result = prepare_pytest_item_data_dir(mock_item, tmp_dir)

                expected_path = os.path.join(tmp_dir, "unit", "test_example", "TestClass", "test_method")
                assert result == expected_path
                assert os.path.exists(result)

    def test_prepare_pytest_item_data_dir_no_class(self):
        """Test prepare_pytest_item_data_dir when item has no class"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Mock pytest item without class
            mock_item = MagicMock()
            mock_item.cls = None
            mock_item.name = "test_function"
            mock_item.fspath.dirname = "/path/to/tests/unit"
            mock_item.fspath.basename = "test_example.py"

            # Mock session config
            mock_session = MagicMock()
            mock_session.config.inicfg.get.return_value = "tests"
            mock_item.session = mock_session

            with patch("os.path.split", return_value=("", "unit")):
                result = prepare_pytest_item_data_dir(mock_item, tmp_dir)

                expected_path = os.path.join(tmp_dir, "unit", "test_example", "", "test_function")
                assert result == expected_path
                assert os.path.exists(result)

    def test_prepare_pytest_item_data_dir_assertion_error(self):
        """Test prepare_pytest_item_data_dir raises assertion when no testpaths"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Mock pytest item
            mock_item = MagicMock()
            mock_item.cls.__name__ = "TestClass"
            mock_item.name = "test_method"

            # Mock session config with no testpaths
            mock_session = MagicMock()
            mock_session.config.inicfg.get.return_value = None
            mock_item.session = mock_session

            with pytest.raises(AssertionError, match="pytest.ini must include testpaths"):
                prepare_pytest_item_data_dir(mock_item, tmp_dir)


class TestConstants:
    """Test cases for module constants"""

    def test_base_directory_name_constant(self):
        """Test BASE_DIRECTORY_NAME constant is set correctly"""
        assert BASE_DIRECTORY_NAME == "tests-collected-info"


# Integration tests for typical usage patterns
class TestDataCollectorIntegration:
    """Integration tests for data collector module"""

    def test_typical_setup_flow(self):
        """Test typical data collector setup flow"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Set up data collector with custom base directory
            result = set_data_collector_values(base_dir=tmp_dir)

            expected_base = f"{tmp_dir}/tests-collected-info"
            assert result["data_collector_base_directory"] == expected_base

            # Write a test file
            test_content = "Integration test content"
            write_to_file("integration_test.txt", test_content, expected_base)

            # Verify file was created
            file_path = os.path.join(expected_base, "integration_test.txt")
            assert os.path.exists(file_path)

            with open(file_path) as f:
                assert f.read() == test_content
