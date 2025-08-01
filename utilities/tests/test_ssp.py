"""Unit tests for ssp module"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.dynamic.exceptions import NotFoundError
from timeout_sampler import TimeoutExpiredError

# Need to mock additional circular imports for ssp
sys.modules["utilities.virt"] = MagicMock()
sys.modules["utilities.storage"] = MagicMock()

# Import after setting up mocks to avoid circular dependency
from utilities.ssp import (  # noqa: E402
    cluster_instance_type_for_hot_plug,
    create_custom_template_from_url,
    get_cim_instance_json,
    get_data_import_crons,
    get_ga_version,
    get_reg_product_name,
    get_ssp_resource,
    get_windows_os_info,
    get_windows_timezone,
    guest_agent_version_parser,
    is_ssp_pod_running,
    matrix_auto_boot_data_import_cron_prefixes,
    validate_os_info_vmi_vs_windows_os,
    verify_ssp_pod_is_running,
    wait_for_at_least_one_auto_update_data_import_cron,
    wait_for_condition_message_value,
    wait_for_deleted_data_import_crons,
    wait_for_ssp_conditions,
)


class TestWaitForDeletedDataImportCrons:
    """Test cases for wait_for_deleted_data_import_crons function"""

    @patch("utilities.ssp.matrix_auto_boot_data_import_cron_prefixes")
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_deleted_data_import_crons_success(self, mock_sampler, mock_matrix_prefixes):
        """Test successful deletion of data import crons"""
        mock_matrix_prefixes.return_value = ["rhel9", "fedora41"]

        # Mock data import crons
        mock_cron1 = MagicMock()
        mock_cron1.name = "rhel9-auto-update"
        mock_cron1.exists = False

        mock_cron2 = MagicMock()
        mock_cron2.name = "fedora41-auto-update"
        mock_cron2.exists = False

        data_import_crons = [mock_cron1, mock_cron2]

        # Mock sampler to return empty list (all deleted)
        mock_sampler.return_value = [[]]

        wait_for_deleted_data_import_crons(data_import_crons)

        mock_matrix_prefixes.assert_called_once()
        mock_sampler.assert_called_once()

    @patch("utilities.ssp.matrix_auto_boot_data_import_cron_prefixes")
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_deleted_data_import_crons_timeout(self, mock_sampler, mock_matrix_prefixes):
        """Test timeout when data import crons are not deleted"""
        mock_matrix_prefixes.return_value = ["rhel9"]

        mock_cron = MagicMock()
        mock_cron.name = "rhel9-auto-update"
        mock_cron.exists = True

        data_import_crons = [mock_cron]

        # Mock timeout
        mock_sampler.side_effect = TimeoutExpiredError("Timeout")

        with pytest.raises(TimeoutExpiredError):
            wait_for_deleted_data_import_crons(data_import_crons)

    @patch("utilities.ssp.matrix_auto_boot_data_import_cron_prefixes")
    @patch("utilities.ssp.TimeoutSampler")
    @patch("utilities.storage.DATA_IMPORT_CRON_SUFFIX", "-suffix")
    def test_wait_for_deleted_data_import_crons_with_existing_crons(self, mock_sampler, mock_matrix_prefixes):
        """Test deletion check with existing crons that match prefixes"""
        mock_matrix_prefixes.return_value = ["rhel9", "fedora41"]

        # Mock data import crons with exists=True and names that will be processed
        mock_cron1 = MagicMock()
        mock_cron1.name = "rhel9-suffix"  # Will match rhel9 prefix after suffix removal
        mock_cron1.exists = True

        mock_cron2 = MagicMock()
        mock_cron2.name = "fedora41-suffix"  # Will match fedora41 prefix after suffix removal
        mock_cron2.exists = True

        mock_cron3 = MagicMock()
        mock_cron3.name = "other-suffix"  # Won't match any prefix
        mock_cron3.exists = True

        data_import_crons = [mock_cron1, mock_cron2, mock_cron3]

        # Mock sampler to return list with matching crons, then empty list
        mock_sampler.return_value = [["rhel9-suffix", "fedora41-suffix"], []]

        wait_for_deleted_data_import_crons(data_import_crons)

        mock_matrix_prefixes.assert_called_once()
        mock_sampler.assert_called_once()

    @patch("utilities.ssp.TIMEOUT_2MIN", 1)  # Short timeout for test
    @patch("utilities.ssp.matrix_auto_boot_data_import_cron_prefixes")
    @patch("utilities.storage.DATA_IMPORT_CRON_SUFFIX", "-auto-update")
    def test_wait_for_deleted_data_import_crons_direct_execution(self, mock_matrix_prefixes):
        """Test that allows real execution to hit line 43"""
        mock_matrix_prefixes.return_value = ["rhel9"]

        # Mock crons that exist initially but then get deleted
        mock_cron = MagicMock()
        mock_cron.name = "rhel9-auto-update"
        mock_cron.exists = True  # Initially exists

        data_import_crons = [mock_cron]

        # Don't mock TimeoutSampler - let it run for real but with very short timeout
        # After first call, make the cron not exist anymore to simulate deletion
        call_count = [0]
        mock_cron.exists

        def side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return True  # First call: cron exists
            else:
                return False  # Subsequent calls: cron deleted

        mock_cron.exists = property(side_effect)

        # This should execute the real function and hit line 43
        # The function will timeout because we set cron.exists to always True initially
        from timeout_sampler import TimeoutExpiredError

        with pytest.raises(TimeoutExpiredError):
            wait_for_deleted_data_import_crons(data_import_crons)

        mock_matrix_prefixes.assert_called_once()


class TestWaitForAtLeastOneAutoUpdateDataImportCron:
    """Test cases for wait_for_at_least_one_auto_update_data_import_cron function"""

    @patch("utilities.ssp.get_data_import_crons")
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_at_least_one_auto_update_data_import_cron_success(self, mock_sampler, mock_get_crons):
        """Test successful wait for data import cron"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "test-namespace"

        mock_cron = MagicMock()
        mock_get_crons.return_value = [mock_cron]
        mock_sampler.return_value = [[mock_cron]]

        wait_for_at_least_one_auto_update_data_import_cron(mock_admin_client, mock_namespace)

        mock_sampler.assert_called_once()

    @patch("utilities.ssp.get_data_import_crons")
    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_at_least_one_auto_update_data_import_cron_timeout(self, mock_sampler, mock_get_crons):
        """Test timeout when no data import cron is found"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "test-namespace"

        mock_get_crons.return_value = []
        mock_sampler.side_effect = TimeoutExpiredError("Timeout")

        with pytest.raises(TimeoutExpiredError):
            wait_for_at_least_one_auto_update_data_import_cron(mock_admin_client, mock_namespace)


class TestMatrixAutoBootDataImportCronPrefixes:
    """Test cases for matrix_auto_boot_data_import_cron_prefixes function"""

    @patch(
        "utilities.ssp.py_config",
        {
            "auto_update_data_source_matrix": [
                {"rhel9": {"data_import_cron_prefix": "rhel9-prefix"}},
                {"fedora41": {"data_import_cron_prefix": "fedora41-prefix"}},
                {"ubuntu": {}},  # No prefix, should use key name
            ]
        },
    )
    def test_matrix_auto_boot_data_import_cron_prefixes(self):
        """Test extraction of data import cron prefixes"""
        result = matrix_auto_boot_data_import_cron_prefixes()

        assert len(result) == 3
        assert "rhel9-prefix" in result
        assert "fedora41-prefix" in result
        assert "ubuntu" in result


class TestGetDataImportCrons:
    """Test cases for get_data_import_crons function"""

    @patch("utilities.ssp.DataImportCron")
    def test_get_data_import_crons(self, mock_data_import_cron_class):
        """Test getting data import crons"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "test-namespace"

        mock_cron1 = MagicMock()
        mock_cron2 = MagicMock()
        mock_data_import_cron_class.get.return_value = [mock_cron1, mock_cron2]

        result = get_data_import_crons(mock_admin_client, mock_namespace)

        assert len(result) == 2
        assert result == [mock_cron1, mock_cron2]
        mock_data_import_cron_class.get.assert_called_once_with(
            dyn_client=mock_admin_client, namespace="test-namespace"
        )


class TestGetSspResource:
    """Test cases for get_ssp_resource function"""

    @patch("utilities.ssp.SSP")
    def test_get_ssp_resource_success(self, mock_ssp_class):
        """Test successful SSP resource retrieval"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "test-namespace"

        mock_ssp = MagicMock()
        mock_ssp_class.get.return_value = [mock_ssp]

        result = get_ssp_resource(mock_admin_client, mock_namespace)

        assert result == mock_ssp
        mock_ssp_class.get.assert_called_once_with(
            dyn_client=mock_admin_client, name="ssp-kubevirt-hyperconverged", namespace="test-namespace"
        )

    @patch("utilities.ssp.SSP")
    def test_get_ssp_resource_not_found(self, mock_ssp_class):
        """Test SSP resource not found"""
        mock_admin_client = MagicMock()
        mock_namespace = MagicMock()
        mock_namespace.name = "test-namespace"

        # Create a proper mock exception with status attribute
        mock_error = MagicMock()
        mock_error.status = 404
        mock_ssp_class.get.side_effect = NotFoundError(mock_error)

        with pytest.raises(NotFoundError):
            get_ssp_resource(mock_admin_client, mock_namespace)


class TestWaitForSspConditions:
    """Test cases for wait_for_ssp_conditions function"""

    @patch("utilities.ssp.utilities")
    def test_wait_for_ssp_conditions_default(self, mock_utilities):
        """Test wait for SSP conditions with default parameters"""
        mock_admin_client = MagicMock()
        mock_hco_namespace = MagicMock()
        mock_hco_namespace.name = "hco-namespace"

        wait_for_ssp_conditions(mock_admin_client, mock_hco_namespace)

        mock_utilities.infra.wait_for_consistent_resource_conditions.assert_called_once()
        call_args = mock_utilities.infra.wait_for_consistent_resource_conditions.call_args
        assert call_args[1]["dynamic_client"] == mock_admin_client
        assert call_args[1]["namespace"] == "hco-namespace"

    @patch("utilities.ssp.utilities")
    def test_wait_for_ssp_conditions_custom(self, mock_utilities):
        """Test wait for SSP conditions with custom parameters"""
        mock_admin_client = MagicMock()
        mock_hco_namespace = MagicMock()
        mock_hco_namespace.name = "hco-namespace"
        custom_conditions = [{"type": "Ready", "status": "True"}]

        wait_for_ssp_conditions(
            mock_admin_client,
            mock_hco_namespace,
            polling_interval=10,
            consecutive_checks_count=5,
            expected_conditions=custom_conditions,
        )

        mock_utilities.infra.wait_for_consistent_resource_conditions.assert_called_once()
        call_args = mock_utilities.infra.wait_for_consistent_resource_conditions.call_args
        assert call_args[1]["expected_conditions"] == custom_conditions
        assert call_args[1]["polling_interval"] == 10
        assert call_args[1]["consecutive_checks_count"] == 5


class TestWaitForConditionMessageValue:
    """Test cases for wait_for_condition_message_value function"""

    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_condition_message_value_success(self, mock_sampler):
        """Test successful wait for condition message"""
        mock_resource = MagicMock()
        mock_resource.name = "test-resource"
        mock_resource.instance.status.conditions = [{"message": "Expected message", "type": "Ready"}]

        mock_sampler.return_value = [mock_resource.instance.status.conditions]

        wait_for_condition_message_value(mock_resource, "Expected message")

        mock_sampler.assert_called_once()

    @patch("utilities.ssp.TimeoutSampler")
    def test_wait_for_condition_message_value_timeout(self, mock_sampler):
        """Test timeout when condition message not found"""
        mock_resource = MagicMock()
        mock_resource.name = "test-resource"
        mock_resource.instance.status.conditions = [{"message": "Wrong message", "type": "Ready"}]

        mock_sampler.side_effect = TimeoutExpiredError("Timeout")

        with pytest.raises(TimeoutExpiredError):
            wait_for_condition_message_value(mock_resource, "Expected message")


class TestCreateCustomTemplateFromUrl:
    """Test cases for create_custom_template_from_url function"""

    @patch("utilities.ssp.urllib.request.urlretrieve")
    @patch("utilities.ssp.Template")
    def test_create_custom_template_from_url(self, mock_template_class, mock_urlretrieve):
        """Test creating custom template from URL"""
        mock_template = MagicMock()
        mock_template_class.return_value.__enter__.return_value = mock_template
        mock_template_class.return_value.__exit__.return_value = None

        url = "https://example.com/template.yaml"
        template_name = "test-template.yaml"
        template_dir = "/tmp/templates"
        mock_namespace = MagicMock()

        with create_custom_template_from_url(url, template_name, template_dir, mock_namespace) as template:
            assert template == mock_template

        expected_filepath = os.path.join(template_dir, template_name)
        mock_urlretrieve.assert_called_once_with(url=url, filename=expected_filepath)
        mock_template_class.assert_called_once_with(yaml_file=expected_filepath, namespace=mock_namespace)


class TestGuestAgentVersionParser:
    """Test cases for guest_agent_version_parser function"""

    def test_guest_agent_version_parser_standard(self):
        """Test parsing standard version format"""
        version_string = "qemu-guest-agent version 4.2.0-34"
        result = guest_agent_version_parser(version_string)
        assert result == "4.2.0-34"

    def test_guest_agent_version_parser_windows_build(self):
        """Test parsing Windows build version format"""
        version_string = "Qemu guest agent version 100.0.0.0"
        result = guest_agent_version_parser(version_string)
        assert result == "100.0.0.0"

    def test_guest_agent_version_parser_simple(self):
        """Test parsing simple version format"""
        version_string = "version 100.0.0"
        result = guest_agent_version_parser(version_string)
        assert result == "100.0.0"


class TestGetWindowsTimezone:
    """Test cases for get_windows_timezone function"""

    @patch("utilities.ssp.run_ssh_commands")
    def test_get_windows_timezone_full(self, mock_run_ssh):
        """Test getting full Windows timezone info"""
        mock_ssh_exec = MagicMock()
        mock_run_ssh.return_value = ["Timezone info output"]

        result = get_windows_timezone(mock_ssh_exec)

        assert result == "Timezone info output"
        mock_run_ssh.assert_called_once()
        # Check that the command contains Get-TimeZone
        call_args = mock_run_ssh.call_args[1]
        command_parts = call_args["commands"][0]
        command_str = " ".join(command_parts)
        assert "Get-TimeZone" in command_str

    @patch("utilities.ssp.run_ssh_commands")
    def test_get_windows_timezone_standard_name_only(self, mock_run_ssh):
        """Test getting Windows timezone standard name only"""
        mock_ssh_exec = MagicMock()
        mock_run_ssh.return_value = ["StandardName info"]

        result = get_windows_timezone(mock_ssh_exec, get_standard_name=True)

        assert result == "StandardName info"
        mock_run_ssh.assert_called_once()
        command_str = " ".join(mock_run_ssh.call_args[1]["commands"][0])
        assert "findstr" in command_str
        assert "StandardName" in command_str


class TestGetGaVersion:
    """Test cases for get_ga_version function"""

    @patch("utilities.ssp.run_ssh_commands")
    def test_get_ga_version(self, mock_run_ssh):
        """Test getting guest agent version"""
        mock_ssh_exec = MagicMock()
        mock_run_ssh.return_value = ["  4.2.0-34  "]

        result = get_ga_version(mock_ssh_exec)

        assert result == "4.2.0-34"
        mock_run_ssh.assert_called_once()
        commands = mock_run_ssh.call_args[1]["commands"]
        assert "powershell" in commands
        assert "qemu-ga.exe" in " ".join(commands)


class TestGetCimInstanceJson:
    """Test cases for get_cim_instance_json function"""

    @patch("utilities.ssp.run_ssh_commands")
    def test_get_cim_instance_json(self, mock_run_ssh):
        """Test getting CIM instance JSON"""
        mock_ssh_exec = MagicMock()
        test_json = '{"CSName": "test-host", "Caption": "Windows 10", "BuildNumber": "19041"}'
        mock_run_ssh.return_value = [test_json]

        result = get_cim_instance_json(mock_ssh_exec)

        assert result["CSName"] == "test-host"
        assert result["Caption"] == "Windows 10"
        assert result["BuildNumber"] == "19041"
        mock_run_ssh.assert_called_once()


class TestGetRegProductName:
    """Test cases for get_reg_product_name function"""

    @patch("utilities.ssp.run_ssh_commands")
    def test_get_reg_product_name(self, mock_run_ssh):
        """Test getting registry product name"""
        mock_ssh_exec = MagicMock()
        mock_run_ssh.return_value = ["Registry output"]

        result = get_reg_product_name(mock_ssh_exec)

        assert result == "Registry output"
        mock_run_ssh.assert_called_once()
        call_args = mock_run_ssh.call_args[1]
        # The command is passed as a list from shlex.split, let's check the actual command
        commands = call_args["commands"]
        # The command should be a list like ['REG', 'QUERY', 'HKEY_LOCAL_MACHINE\\SOFTWARE\\...', '/v', 'ProductName']
        assert "REG" in commands
        assert "QUERY" in commands
        assert any("ProductName" in cmd for cmd in commands)


class TestGetWindowsOsInfo:
    """Test cases for get_windows_os_info function"""

    @patch("utilities.ssp.get_cim_instance_json")
    @patch("utilities.ssp.get_ga_version")
    @patch("utilities.ssp.get_reg_product_name")
    @patch("utilities.ssp.get_windows_timezone")
    @patch("utilities.ssp.guest_agent_version_parser")
    def test_get_windows_os_info(self, mock_parser, mock_timezone, mock_reg, mock_ga, mock_cim):
        """Test getting complete Windows OS info"""
        mock_ssh_exec = MagicMock()

        # Mock return values
        mock_parser.return_value = "4.2.0-34"
        mock_timezone.return_value = "UTC"
        mock_reg.return_value = "    REG_SZ    Windows 10 Pro\r\n"
        mock_ga.return_value = "4.2.0-34"
        mock_cim.return_value = {
            "CSName": "test-host",
            "BuildNumber": "19041",
            "Caption": "Microsoft Windows 10 Pro",
            "Version": "10.0.19041",
            "OSArchitecture": "64-bit",
        }

        result = get_windows_os_info(mock_ssh_exec)

        assert result["guestAgentVersion"] == "4.2.0-34"
        assert result["hostname"] == "test-host"
        assert result["timezone"] == "UTC"
        assert result["os"]["name"] == "Microsoft Windows"
        assert result["os"]["kernelRelease"] == "19041"
        assert result["os"]["prettyName"] == "Windows 10 Pro"
        assert result["os"]["machine"] == "x86_64"
        assert result["os"]["id"] == "mswindows"


class TestValidateOsInfoVmiVsWindowsOs:
    """Test cases for validate_os_info_vmi_vs_windows_os function"""

    @patch("utilities.ssp.utilities")
    @patch("utilities.ssp.get_windows_os_info")
    def test_validate_os_info_vmi_vs_windows_os_success(self, mock_windows_info, mock_utilities):
        """Test successful OS info validation"""
        mock_vm = MagicMock()

        mock_utilities.virt.get_guest_os_info.return_value = {"name": "Microsoft Windows", "kernelRelease": "19041"}

        mock_windows_info.return_value = {"os": {"name": "Microsoft Windows Pro", "kernelRelease": "19041 Build"}}

        # Should not raise assertion error
        validate_os_info_vmi_vs_windows_os(mock_vm)

    @patch("utilities.ssp.utilities")
    @patch("utilities.ssp.get_windows_os_info")
    def test_validate_os_info_vmi_vs_windows_os_mismatch(self, mock_windows_info, mock_utilities):
        """Test OS info validation with mismatch"""
        mock_vm = MagicMock()

        mock_utilities.virt.get_guest_os_info.return_value = {"name": "Linux", "kernelRelease": "5.4.0"}

        mock_windows_info.return_value = {"os": {"name": "Microsoft Windows", "kernelRelease": "19041"}}

        with pytest.raises(AssertionError, match="Data mismatch"):
            validate_os_info_vmi_vs_windows_os(mock_vm)

    @patch("utilities.ssp.utilities")
    def test_validate_os_info_vmi_vs_windows_os_no_vmi_data(self, mock_utilities):
        """Test OS info validation when VMI has no guest agent data"""
        mock_vm = MagicMock()
        mock_utilities.virt.get_guest_os_info.return_value = None

        with pytest.raises(AssertionError, match="VMI doesn't have guest agent data"):
            validate_os_info_vmi_vs_windows_os(mock_vm)


class TestIsSspPodRunning:
    """Test cases for is_ssp_pod_running function"""

    @patch("utilities.ssp.utilities")
    def test_is_ssp_pod_running_true(self, mock_utilities):
        """Test SSP pod is running"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        mock_pod = MagicMock()
        mock_pod.status = "Running"
        mock_pod.Status.RUNNING = "Running"
        mock_pod.instance.status.containerStatuses = [{"ready": True}]
        mock_utilities.infra.get_pod_by_name_prefix.return_value = mock_pod

        result = is_ssp_pod_running(mock_dyn_client, mock_namespace)

        assert result is True

    @patch("utilities.ssp.utilities")
    def test_is_ssp_pod_running_false(self, mock_utilities):
        """Test SSP pod is not running"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        mock_pod = MagicMock()
        mock_pod.status = "Pending"
        mock_pod.Status.RUNNING = "Running"
        mock_utilities.infra.get_pod_by_name_prefix.return_value = mock_pod

        result = is_ssp_pod_running(mock_dyn_client, mock_namespace)

        assert result is False


class TestVerifySspPodIsRunning:
    """Test cases for verify_ssp_pod_is_running function"""

    @patch("utilities.ssp.TimeoutSampler")
    @patch("utilities.ssp.is_ssp_pod_running")
    def test_verify_ssp_pod_is_running_success(self, mock_is_running, mock_sampler):
        """Test successful SSP pod verification"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock consecutive successful checks
        mock_sampler.return_value = [True, True, True]

        verify_ssp_pod_is_running(mock_dyn_client, mock_namespace, consecutive_checks_count=3)

        mock_sampler.assert_called_once()

    @patch("utilities.ssp.TimeoutSampler")
    @patch("utilities.ssp.is_ssp_pod_running")
    def test_verify_ssp_pod_is_running_timeout(self, mock_is_running, mock_sampler):
        """Test SSP pod verification timeout"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        mock_sampler.side_effect = TimeoutExpiredError("Timeout")

        with pytest.raises(TimeoutExpiredError):
            verify_ssp_pod_is_running(mock_dyn_client, mock_namespace)

    @patch("utilities.ssp.TimeoutSampler")
    @patch("utilities.ssp.is_ssp_pod_running")
    @patch("utilities.ssp.LOGGER")
    def test_verify_ssp_pod_is_running_timeout_with_sample_true(self, mock_logger, mock_is_running, mock_sampler):
        """Test SSP pod verification timeout when sample is True (pod running but not consistently)"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock the sampler to return True values but then timeout
        mock_sampler_instance = MagicMock()
        # Simulate pod being up but not consistently for required checks
        mock_sampler_instance.__iter__.return_value = [True, True, False, True]
        mock_sampler.return_value = mock_sampler_instance

        # Make the sampler raise TimeoutExpiredError after iteration
        def side_effect():
            # Iterate through some values first
            for val in [True, True, False, True]:
                yield val
            # Then raise timeout
            raise TimeoutExpiredError("Timeout")

        mock_sampler.return_value = side_effect()

        # The function should NOT raise because it handles the TimeoutExpiredError internally
        # when sample is True (meaning pod was running, just not consistently)
        verify_ssp_pod_is_running(mock_dyn_client, mock_namespace, consecutive_checks_count=3)

        # Should log warning about inconsistent checks
        mock_logger.warning.assert_called_once()
        assert "SSP pod is up, but not for the last" in mock_logger.warning.call_args[0][0]

    @patch("utilities.ssp.TimeoutSampler")
    @patch("utilities.ssp.is_ssp_pod_running")
    @patch("utilities.ssp.LOGGER")
    @patch("utilities.ssp.TIMEOUT_6MIN", 360)
    def test_verify_ssp_pod_is_running_timeout_with_sample_false(self, mock_logger, mock_is_running, mock_sampler):
        """Test SSP pod verification timeout when sample is False (pod not running)"""
        mock_dyn_client = MagicMock()
        mock_namespace = MagicMock()

        # Mock the sampler to return False values and then timeout
        def side_effect():
            # Return False values
            for val in [False, False, False]:
                yield val
            # Then raise timeout
            raise TimeoutExpiredError("Timeout")

        mock_sampler.return_value = side_effect()

        # Should raise TimeoutExpiredError when sample is False
        with pytest.raises(TimeoutExpiredError):
            verify_ssp_pod_is_running(mock_dyn_client, mock_namespace)

        # Should log error about pod not running
        mock_logger.error.assert_called_once()
        assert "SSP pod was not running for last 360 seconds" in mock_logger.error.call_args[0][0]


class TestClusterInstanceTypeForHotPlug:
    """Test cases for cluster_instance_type_for_hot_plug function"""

    @patch("utilities.ssp.VirtualMachineClusterInstancetype")
    def test_cluster_instance_type_for_hot_plug_with_cpu_model(self, mock_instance_type_class):
        """Test creating cluster instance type with CPU model"""
        mock_instance = MagicMock()
        mock_instance_type_class.return_value = mock_instance

        result = cluster_instance_type_for_hot_plug(4, "host-model")

        assert result == mock_instance
        mock_instance_type_class.assert_called_once_with(
            name="hot-plug-4-cpu-instance-type",
            memory={"guest": "4Gi"},
            cpu={
                "guest": 4,
                "model": "host-model",
                "maxSockets": 8,
            },
        )

    @patch("utilities.ssp.VirtualMachineClusterInstancetype")
    def test_cluster_instance_type_for_hot_plug_without_cpu_model(self, mock_instance_type_class):
        """Test creating cluster instance type without CPU model"""
        mock_instance = MagicMock()
        mock_instance_type_class.return_value = mock_instance

        result = cluster_instance_type_for_hot_plug(2, None)

        assert result == mock_instance
        mock_instance_type_class.assert_called_once_with(
            name="hot-plug-2-cpu-instance-type",
            memory={"guest": "4Gi"},
            cpu={
                "guest": 2,
                "model": None,
                "maxSockets": 8,
            },
        )
