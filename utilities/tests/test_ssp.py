"""Unit tests for ssp module"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock modules to break circular imports
sys.modules['utilities.virt'] = MagicMock()
sys.modules['utilities.infra'] = MagicMock()
sys.modules['utilities.hco'] = MagicMock()

import pytest
from timeout_sampler import TimeoutExpiredError

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

    @pytest.mark.unit
    @patch("utilities.ssp.get_data_import_crons")
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_auto_update_cron_success(self, mock_sampler_class, mock_get_crons):
        """Test successful wait for auto update data import cron"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock data import cron
        mock_cron = MagicMock()
        mock_cron.name = "centos-stream8-auto-import"
        mock_get_crons.return_value = [mock_cron]

        # Mock sampler to find cron immediately
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([mock_cron])
        mock_sampler_class.return_value = mock_sampler

        result = wait_for_at_least_one_auto_update_data_import_cron(
            mock_admin_client,
            mock_namespace,
        )

        assert result == mock_cron


class TestMatrixAutoBootDataImportCronPrefixes:
    """Test cases for matrix_auto_boot_data_import_cron_prefixes function"""

    @pytest.mark.unit
    @patch("utilities.ssp.DataImportCron")
    def test_matrix_auto_boot_data_import_cron_prefixes(self, mock_cron_class):
        """Test getting auto boot data import cron prefixes"""
        # Mock data import crons
        mock_cron1 = MagicMock()
        mock_cron1.name = "centos-stream8-auto-import"
        mock_cron2 = MagicMock()
        mock_cron2.name = "fedora-auto-import"
        mock_cron3 = MagicMock()
        mock_cron3.name = "custom-import"  # Not auto-boot

        mock_cron_class.get.return_value = [mock_cron1, mock_cron2, mock_cron3]

        result = matrix_auto_boot_data_import_cron_prefixes()

        # Should only include auto-boot prefixes
        assert "centos-stream8" in result
        assert "fedora" in result
        assert len(result) == 2


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

    @pytest.mark.unit
    @patch("utilities.ssp.SSP")
    def test_get_ssp_resource_kubevirt_hyperconverged(self, mock_ssp_class):
        """Test getting SSP resource for kubevirt-hyperconverged"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "openshift-cnv"

        mock_ssp = MagicMock()
        mock_ssp_class.return_value = mock_ssp

        result = get_ssp_resource(mock_admin_client, mock_namespace)

        assert result == mock_ssp
        mock_ssp_class.assert_called_once_with(
            client=mock_admin_client,
            name="ssp-kubevirt-hyperconverged",
            namespace=mock_namespace.name,
        )

    @pytest.mark.unit
    @patch("utilities.ssp.SSP")
    def test_get_ssp_resource_ssp_operator(self, mock_ssp_class):
        """Test getting SSP resource for ssp-operator"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "kubevirt-ssp-operator"

        mock_ssp = MagicMock()
        mock_ssp_class.return_value = mock_ssp

        result = get_ssp_resource(mock_admin_client, mock_namespace)

        assert result == mock_ssp
        mock_ssp_class.assert_called_once_with(
            client=mock_admin_client,
            name="ssp-kubevirt-ssp-operator",
            namespace=mock_namespace.name,
        )


class TestWaitForSspConditions:
    """Test cases for wait_for_ssp_conditions function"""

    @pytest.mark.unit
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_ssp_conditions_success(self, mock_sampler_class):
        """Test successful SSP conditions wait"""
        mock_ssp = MagicMock()
        mock_ssp.instance.status.conditions = [
            {"type": "Available", "status": "True"},
            {"type": "Progressing", "status": "False"},
            {"type": "Degraded", "status": "False"},
        ]

        expected_conditions = {
            "Available": "True",
            "Progressing": "False",
            "Degraded": "False",
        }

        # Mock sampler to succeed immediately
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([True])
        mock_sampler_class.return_value = mock_sampler

        wait_for_ssp_conditions(
            ssp=mock_ssp,
            expected_conditions=expected_conditions,
        )

        mock_sampler_class.assert_called_once()


class TestGuestAgentVersionParser:
    """Test cases for guest_agent_version_parser function"""

    @pytest.mark.unit
    def test_guest_agent_version_parser_standard(self):
        """Test parsing standard guest agent version"""
        version_string = "2.5.0"
        result = guest_agent_version_parser(version_string)
        assert result == "2.5.0"

    @pytest.mark.unit
    def test_guest_agent_version_parser_with_release(self):
        """Test parsing guest agent version with release info"""
        version_string = "2.5.0-1.el8"
        result = guest_agent_version_parser(version_string)
        assert result == "2.5.0"

    @pytest.mark.unit
    def test_guest_agent_version_parser_complex(self):
        """Test parsing complex guest agent version"""
        version_string = "2.5.0-1.el8.x86_64"
        result = guest_agent_version_parser(version_string)
        assert result == "2.5.0"


class TestGetWindowsTimezone:
    """Test cases for get_windows_timezone function"""

    @pytest.mark.unit
    def test_get_windows_timezone_display_name(self):
        """Test getting Windows timezone display name"""
        mock_ssh_exec = MagicMock()
        mock_ssh_exec.run_command.return_value = [
            0,
            '{"DisplayName": "(UTC-05:00) Eastern Time (US & Canada)"}',
            "",
        ]

        result = get_windows_timezone(mock_ssh_exec)

        assert result == "(UTC-05:00) Eastern Time (US & Canada)"
        mock_ssh_exec.run_command.assert_called_once()

    @pytest.mark.unit
    def test_get_windows_timezone_standard_name(self):
        """Test getting Windows timezone standard name"""
        mock_ssh_exec = MagicMock()
        mock_ssh_exec.run_command.return_value = [
            0,
            '{"StandardName": "Eastern Standard Time"}',
            "",
        ]

        result = get_windows_timezone(mock_ssh_exec, get_standard_name=True)

        assert result == "Eastern Standard Time"


class TestGetGaVersion:
    """Test cases for get_ga_version function"""

    @pytest.mark.unit
    def test_get_ga_version_success(self):
        """Test getting guest agent version successfully"""
        mock_ssh_exec = MagicMock()
        mock_ssh_exec.run_command.return_value = [
            0,
            '{"FileVersion": "103.2.2.0"}',
            "",
        ]

        result = get_ga_version(mock_ssh_exec)

        assert result == "103.2.2.0"

    @pytest.mark.unit
    def test_get_ga_version_with_description(self):
        """Test getting guest agent version with file description"""
        mock_ssh_exec = MagicMock()
        mock_ssh_exec.run_command.return_value = [
            0,
            '{"FileVersion": null, "FileDescription": "QEMU Guest Agent VSS Provider 103.2.2"}',
            "",
        ]

        result = get_ga_version(mock_ssh_exec)

        assert result == "103.2.2"


class TestGetWindowsOsInfo:
    """Test cases for get_windows_os_info function"""

    @pytest.mark.unit
    def test_get_windows_os_info_all_fields(self):
        """Test getting complete Windows OS info"""
        mock_ssh_exec = MagicMock()

        # Mock get_reg_product_name
        with patch("ssp.get_reg_product_name", return_value="Windows 10 Pro"):
            # Mock get_cim_instance_json
            with patch("ssp.get_cim_instance_json") as mock_cim:
                mock_cim.return_value = {
                    "BuildNumber": "19043",
                    "Version": "10.0.19043",
                }

                result = get_windows_os_info(mock_ssh_exec)

                assert result["product_name"] == "Windows 10 Pro"
                assert result["build_number"] == "19043"
                assert result["version"] == "10.0.19043"

    @pytest.mark.unit
    def test_get_windows_os_info_partial(self):
        """Test getting partial Windows OS info"""
        mock_ssh_exec = MagicMock()

        with patch("ssp.get_reg_product_name", return_value="Windows Server 2019"):
            with patch("ssp.get_cim_instance_json", return_value={}):
                result = get_windows_os_info(mock_ssh_exec)

                assert result["product_name"] == "Windows Server 2019"
                assert result.get("build_number") is None
                assert result.get("version") is None


class TestIsSspPodRunning:
    """Test cases for is_ssp_pod_running function"""

    @pytest.mark.unit
    @patch("utilities.ssp.get_ssp_resource")
    @patch("utilities.ssp.Pod")
    def test_is_ssp_pod_running_true(self, mock_pod_class, mock_get_ssp):
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

    @pytest.mark.unit
    @patch("utilities.ssp.get_ssp_resource")
    @patch("utilities.ssp.Pod")
    def test_is_ssp_pod_running_false(self, mock_pod_class, mock_get_ssp):
        """Test when SSP pod is not running"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        mock_ssp = MagicMock()
        mock_get_ssp.return_value = mock_ssp

        # No pods found
        mock_pod_class.get.return_value = []

        result = is_ssp_pod_running(mock_dyn_client, mock_namespace)

        assert result is False


class TestClusterInstanceTypeForHotPlug:
    """Test cases for cluster_instance_type_for_hot_plug function"""

    @pytest.mark.unit
    @patch("utilities.ssp.VirtualMachineClusterInstancetype")
    def test_cluster_instance_type_for_hot_plug_basic(self, mock_instancetype_class):
        """Test creating cluster instance type for hot plug"""
        guest_sockets = 4
        cpu_model = "Haswell"

        mock_instance = MagicMock()
        mock_instancetype_class.return_value = mock_instance

        result = cluster_instance_type_for_hot_plug(guest_sockets, cpu_model)

        assert result == mock_instance

        # Verify the instance type was created with correct parameters
        mock_instancetype_class.assert_called_once()
        call_kwargs = mock_instancetype_class.call_args[1]
        assert call_kwargs["name"] == "cx1.4xlarge"
        assert call_kwargs["cpu"]["guest"] == 4
        assert call_kwargs["cpu"]["model"] == "Haswell"
        assert call_kwargs["memory"]["guest"] == "4Gi"
