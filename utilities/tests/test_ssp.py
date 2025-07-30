"""Unit tests for ssp module"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from timeout_sampler import TimeoutExpiredError

# Mock modules to break circular imports
sys.modules["utilities.virt"] = MagicMock()
sys.modules["utilities.infra"] = MagicMock()
sys.modules["utilities.hco"] = MagicMock()

from utilities.ssp import (
    cluster_instance_type_for_hot_plug,
    get_data_import_crons,
    get_ga_version,
    get_ssp_resource,
    get_windows_os_info,
    get_windows_timezone,
    guest_agent_version_parser,
    is_ssp_pod_running,
    matrix_auto_boot_data_import_cron_prefixes,
    wait_for_at_least_one_auto_update_data_import_cron,
    wait_for_deleted_data_import_crons,
    wait_for_ssp_conditions,
)


class TestWaitForDeletedDataImportCrons:
    """Test cases for wait_for_deleted_data_import_crons function"""

    @pytest.mark.unit
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_deleted_data_import_crons_success(self, mock_sampler_class):
        """Test successful deletion of data import crons"""
        # Mock data import crons
        mock_cron1 = MagicMock()
        mock_cron1.name = "centos-stream8-auto-import"
        mock_cron1.exists = False

        mock_cron2 = MagicMock()
        mock_cron2.name = "fedora-auto-import"
        mock_cron2.exists = False

        data_import_crons = [mock_cron1, mock_cron2]

        # Mock sampler to return empty list (all deleted)
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([[]])
        mock_sampler_class.return_value = mock_sampler

        wait_for_deleted_data_import_crons(data_import_crons)

        mock_sampler_class.assert_called_once()

    @pytest.mark.unit
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_deleted_data_import_crons_timeout(self, mock_sampler_class):
        """Test timeout when crons are not deleted"""
        mock_cron = MagicMock()
        mock_cron.name = "centos-stream8-auto-import"
        mock_cron.exists = True

        # Mock sampler to timeout
        mock_sampler = MagicMock()
        mock_sampler.__iter__.side_effect = TimeoutExpiredError("Timeout")
        mock_sampler_class.return_value = mock_sampler

        with pytest.raises(TimeoutExpiredError):
            wait_for_deleted_data_import_crons([mock_cron])


class TestWaitForAtLeastOneAutoUpdateDataImportCron:
    """Test cases for wait_for_at_least_one_auto_update_data_import_cron function"""

    @patch("ssp.TimeoutSampler")
    @patch("ssp.get_data_import_crons")
    def test_wait_for_auto_update_cron_success(self, mock_get_crons, mock_sampler_class):
        """Test successful wait for auto update data import cron"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock data import cron
        mock_cron = MagicMock()
        mock_cron.name = "centos-stream8-auto-import"
        mock_get_crons.return_value = [mock_cron]

        # Mock sampler to find cron immediately
        mock_sampler = MagicMock()
        mock_sampler.__iter__ = lambda self: iter([[mock_cron]])
        mock_sampler_class.return_value = mock_sampler

        # The function doesn't return anything, just waits
        wait_for_at_least_one_auto_update_data_import_cron(mock_admin_client, mock_namespace)

        mock_sampler_class.assert_called_once()


class TestMatrixAutoBootDataImportCronPrefixes:
    """Test cases for matrix_auto_boot_data_import_cron_prefixes function"""

    @patch("ssp.py_config")
    def test_matrix_auto_boot_data_import_cron_prefixes(self, mock_config):
        """Test getting auto boot data import cron prefixes"""
        # Mock config with test data
        mock_config.__getitem__.return_value = [
            {"image_family": "centos-stream8", "common_templates": True},
            {"image_family": "fedora", "common_templates": True},
            {"image_family": "custom", "common_templates": False},
        ]

        result = matrix_auto_boot_data_import_cron_prefixes()

        # Should return only entries with common_templates=True
        assert "centos-stream8" in result
        assert "fedora" in result
        assert "custom" not in result


class TestGetDataImportCrons:
    """Test cases for get_data_import_crons function"""

    @pytest.mark.unit
    @patch("utilities.ssp.DataImportCron")
    def test_get_data_import_crons(self, mock_cron_class):
        """Test getting data import crons"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "openshift-virtualization-os-images"

        expected_crons = [MagicMock(), MagicMock()]
        mock_cron_class.get.return_value = expected_crons

        result = get_data_import_crons(mock_admin_client, mock_namespace)

        assert result == expected_crons
        mock_cron_class.get.assert_called_once_with(
            dyn_client=mock_admin_client,
            namespace=mock_namespace.name,
        )


class TestGetSspResource:
    """Test cases for get_ssp_resource function"""

    @patch("ssp.SSP")
    def test_get_ssp_resource_kubevirt_hyperconverged(self, mock_ssp_class):
        """Test getting SSP resource for kubevirt-hyperconverged"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "openshift-cnv"

        mock_ssp = MagicMock()
        mock_ssp_class.get.return_value = [mock_ssp]

        result = get_ssp_resource(mock_admin_client, mock_namespace)

        assert result == mock_ssp
        mock_ssp_class.get.assert_called_once_with(
            dyn_client=mock_admin_client,
            name="ssp-kubevirt-hyperconverged",
            namespace="openshift-cnv",
        )

    @patch("ssp.SSP")
    def test_get_ssp_resource_ssp_operator(self, mock_ssp_class):
        """Test getting SSP resource when not found raises error"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "kubevirt-ssp-operator"

        # Mock to raise NotFoundError
        from ocp_resources.utils import NotFoundError

        mock_ssp_class.get.side_effect = NotFoundError("Not found")

        with pytest.raises(NotFoundError):
            get_ssp_resource(mock_admin_client, mock_namespace)


class TestWaitForSspConditions:
    """Test cases for wait_for_ssp_conditions function"""

    @pytest.mark.unit
    @patch("ssp.TimeoutSampler")
    def test_wait_for_ssp_conditions_success(self, mock_sampler_class):
        """Test successful SSP conditions wait"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock SSP resource
        mock_ssp = MagicMock()
        mock_ssp.instance.status.conditions = [
            {"type": "Available", "status": "True"},
            {"type": "Progressing", "status": "False"},
            {"type": "Degraded", "status": "False"},
        ]

        # Mock sampler to succeed immediately
        mock_sampler = MagicMock()
        mock_sampler.__iter__ = lambda self: iter([True])
        mock_sampler_class.return_value = mock_sampler

        # Mock get_ssp_resource
        with patch("ssp.get_ssp_resource", return_value=mock_ssp):
            wait_for_ssp_conditions(mock_admin_client, mock_namespace)

        mock_sampler_class.assert_called_once()


class TestGuestAgentVersionParser:
    """Test cases for guest_agent_version_parser function"""

    def test_guest_agent_version_parser_standard(self):
        """Test parsing standard version string"""
        version_string = "qemu-guest-agent-2.11.0-2.el7"
        result = guest_agent_version_parser(version_string)
        assert result == "2.11.0-2"

    def test_guest_agent_version_parser_with_release(self):
        """Test parsing version with release number"""
        version_string = "2.5.0-1.el7"
        result = guest_agent_version_parser(version_string)
        # The function includes the build number after hyphen
        assert result == "2.5.0-1"

    def test_guest_agent_version_parser_complex(self):
        """Test parsing complex version string"""
        version_string = "qemu-guest-agent-2.5.0-1.el7.x86_64"
        result = guest_agent_version_parser(version_string)
        # The function includes the build number after hyphen
        assert result == "2.5.0-1"


class TestGetWindowsTimezone:
    """Test cases for get_windows_timezone function"""

    @patch("ssp.run_ssh_commands")
    def test_get_windows_timezone_display_name(self, mock_run_ssh):
        """Test getting Windows timezone display name"""
        mock_ssh_exec = MagicMock()
        expected_timezone = "(UTC-08:00) Pacific Time (US & Canada)"

        # Mock run_ssh_commands to return the expected output
        mock_run_ssh.return_value = [expected_timezone]

        result = get_windows_timezone(mock_ssh_exec)

        assert result == expected_timezone
        mock_run_ssh.assert_called_once()

    @patch("ssp.run_ssh_commands")
    def test_get_windows_timezone_standard_name(self, mock_run_ssh):
        """Test getting Windows timezone standard name"""
        mock_ssh_exec = MagicMock()
        expected_timezone = "Pacific Standard Time"

        # Mock run_ssh_commands to return the expected output
        mock_run_ssh.return_value = [expected_timezone]

        result = get_windows_timezone(mock_ssh_exec, get_standard_name=True)

        assert result == expected_timezone


class TestGetGaVersion:
    """Test cases for get_ga_version function"""

    @patch("ssp.run_ssh_commands")
    def test_get_ga_version_success(self, mock_run_ssh):
        """Test getting guest agent version successfully"""
        mock_ssh_exec = MagicMock()
        expected_version = "FileVersion:    2.5.0.0"

        # Mock run_ssh_commands to return the expected output
        mock_run_ssh.return_value = [expected_version]

        result = get_ga_version(mock_ssh_exec)

        assert result == expected_version

    @patch("ssp.run_ssh_commands")
    def test_get_ga_version_with_description(self, mock_run_ssh):
        """Test getting guest agent version with file description"""
        mock_ssh_exec = MagicMock()
        version_output = "FileDescription: QEMU Guest Agent\nFileVersion:     2.5.0.0"

        # Mock run_ssh_commands to return the expected output
        mock_run_ssh.return_value = [version_output]

        result = get_ga_version(mock_ssh_exec)

        assert result == version_output


class TestGetWindowsOsInfo:
    """Test cases for get_windows_os_info function"""

    @patch("ssp.get_cim_instance_json")
    @patch("ssp.get_reg_product_name")
    def test_get_windows_os_info_all_fields(self, mock_get_reg, mock_get_cim):
        """Test getting complete Windows OS info"""
        mock_ssh_exec = MagicMock()

        # Mock get_reg_product_name
        mock_get_reg.return_value = "Windows Server 2019 Datacenter"

        # Mock get_cim_instance_json
        mock_get_cim.return_value = {
            "Name": "Microsoft Windows Server 2019 Datacenter",
            "Version": "10.0.17763",
            "CurrentBuildNumber": "17763",
        }

        result = get_windows_os_info(mock_ssh_exec)

        assert result["product_name"] == "Windows Server 2019 Datacenter"
        assert result["os_version"] == "10.0.17763"
        assert result["current_build"] == "17763"

    @patch("ssp.get_cim_instance_json")
    @patch("ssp.get_reg_product_name")
    def test_get_windows_os_info_partial(self, mock_get_reg, mock_get_cim):
        """Test getting partial Windows OS info"""
        mock_ssh_exec = MagicMock()

        mock_get_reg.return_value = "Windows Server 2019"
        mock_get_cim.return_value = {"Version": "10.0.17763"}

        result = get_windows_os_info(mock_ssh_exec)

        assert result["product_name"] == "Windows Server 2019"
        assert result["os_version"] == "10.0.17763"
        assert result.get("current_build") is None


class TestIsSspPodRunning:
    """Test cases for is_ssp_pod_running function"""

    @patch("ssp.Pod")
    @patch("ssp.get_ssp_resource")
    def test_is_ssp_pod_running_true(self, mock_get_ssp, mock_pod_class):
        """Test when SSP pod is running"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock SSP resource
        mock_ssp = MagicMock()
        mock_ssp.name = "ssp-kubevirt-hyperconverged"
        mock_get_ssp.return_value = mock_ssp

        # Mock pod
        mock_pod = MagicMock()
        mock_pod.instance.status.phase = "Running"
        mock_pod_class.get.return_value = [mock_pod]

        result = is_ssp_pod_running(mock_dyn_client, mock_namespace)

        assert result is True
        mock_pod_class.get.assert_called_once()

    @patch("ssp.Pod")
    @patch("ssp.get_ssp_resource")
    def test_is_ssp_pod_running_false(self, mock_get_ssp, mock_pod_class):
        """Test when SSP pod is not running"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        mock_ssp = MagicMock()
        mock_get_ssp.return_value = mock_ssp

        # Mock pod that's not running
        mock_pod = MagicMock()
        mock_pod.instance.status.phase = "Pending"
        mock_pod_class.get.return_value = [mock_pod]

        result = is_ssp_pod_running(mock_dyn_client, mock_namespace)

        assert result is False


class TestClusterInstanceTypeForHotPlug:
    """Test cases for cluster_instance_type_for_hot_plug function"""

    @patch("ssp.VirtualMachineClusterInstancetype")
    def test_cluster_instance_type_for_hot_plug_basic(self, mock_instancetype_class):
        """Test creating cluster instance type for hot plug"""
        guest_sockets = 4
        cpu_model = "Haswell"

        mock_instance = MagicMock()
        mock_instancetype_class.return_value = mock_instance

        result = cluster_instance_type_for_hot_plug(guest_sockets, cpu_model)

        assert result == mock_instance

        # Verify it was called with correct arguments
        call_kwargs = mock_instancetype_class.call_args[1]
        assert call_kwargs["name"] == "hot-plug-4-cpu-instance-type"
        assert call_kwargs["cpu"]["guest"] == 4
        assert call_kwargs["cpu"]["model"] == "Haswell"
        assert call_kwargs["cpu"]["maxSockets"] == 8
