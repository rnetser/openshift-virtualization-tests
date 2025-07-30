"""Unit tests for console module"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from console import Console


class TestConsole:
    """Test cases for Console class"""

    def test_console_init_with_defaults(self):
        """Test Console initialization with default values"""
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.username = "default-user"
        mock_vm.password = "default-pass"

        console = Console(vm=mock_vm)

        assert console.vm == mock_vm
        assert console.username == "default-user"
        assert console.password == "default-pass"
        assert console.timeout == 30
        assert console.child is None
        assert console.login_prompt == "login:"
        assert console.prompt == [r"\$"]

    def test_console_init_with_custom_values(self):
        """Test Console initialization with custom values"""
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"

        console = Console(
            vm=mock_vm,
            username="custom-user",
            password="custom-pass",
            timeout=60,
            prompt=["#", ">"]
        )

        assert console.username == "custom-user"
        assert console.password == "custom-pass"
        assert console.timeout == 60
        assert console.prompt == ["#", ">"]

    def test_console_init_with_login_params(self):
        """Test Console initialization with VM login_params"""
        mock_vm = MagicMock()
        mock_vm.login_params = {
            "username": "login-user",
            "password": "login-pass"
        }
        mock_vm.username = "default-user"
        mock_vm.password = "default-pass"

        console = Console(vm=mock_vm)

        # Should prefer login_params over default vm attributes
        assert console.username == "login-user"
        assert console.password == "login-pass"

    @patch("console.pexpect")
    @patch("console.get_data_collector_base_directory")
    def test_console_connect(self, mock_get_dir, mock_pexpect):
        """Test console connect method"""
        mock_get_dir.return_value = "/tmp/data"
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.username = "user"
        mock_vm.password = "pass"

        mock_child = MagicMock()
        mock_pexpect.spawn.return_value = mock_child

        console = Console(vm=mock_vm)
        
        with patch.object(console, 'console_eof_sampler') as mock_sampler:
            with patch.object(console, '_connect') as mock_connect:
                result = console.connect()

                assert result == console.child
                mock_sampler.assert_called_once()
                mock_connect.assert_called_once()

    @patch("console.virtctl_command")
    def test_console_generate_cmd(self, mock_virtctl):
        """Test _generate_cmd method"""
        mock_virtctl.return_value = "virtctl"
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.namespace = "test-ns"
        mock_vm.username = "user"
        mock_vm.password = "pass"

        console = Console(vm=mock_vm)
        
        # The cmd should be set during init
        assert console.cmd is not None
        assert "virtctl" in console.cmd
        assert "console" in console.cmd
        assert mock_vm.name in console.cmd

    @patch("console.virtctl_command")
    def test_console_enter(self, mock_virtctl):
        """Test context manager __enter__ method"""
        mock_virtctl.return_value = "virtctl"
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.username = "user"
        mock_vm.password = "pass"

        console = Console(vm=mock_vm)
        
        with patch.object(console, 'connect') as mock_connect:
            result = console.__enter__()
            
            assert result == console
            mock_connect.assert_called_once()

    @patch("console.virtctl_command")
    def test_console_exit(self, mock_virtctl):
        """Test context manager __exit__ method"""
        mock_virtctl.return_value = "virtctl"
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.username = "user"  
        mock_vm.password = "pass"

        console = Console(vm=mock_vm)
        console.child = MagicMock()
        
        console.__exit__(None, None, None)
        
        console.child.close.assert_called_once()

    @patch("console.virtctl_command")
    def test_console_sendline(self, mock_virtctl):
        """Test sendline method"""
        mock_virtctl.return_value = "virtctl"
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.username = "user"
        mock_vm.password = "pass"

        console = Console(vm=mock_vm)
        console.child = MagicMock()
        
        console.sendline("test command")
        
        console.child.sendline.assert_called_once_with("test command")

    @patch("console.virtctl_command")
    def test_console_expect(self, mock_virtctl):
        """Test expect method"""
        mock_virtctl.return_value = "virtctl"
        mock_vm = MagicMock()
        mock_vm.name = "test-vm"
        mock_vm.username = "user"
        mock_vm.password = "pass"

        console = Console(vm=mock_vm)
        console.child = MagicMock()
        console.child.expect.return_value = 0
        
        result = console.expect("test pattern")
        
        assert result == 0
        console.child.expect.assert_called_once_with("test pattern", timeout=30) 