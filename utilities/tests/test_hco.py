"""Unit tests for hco module"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock modules to break circular imports
sys.modules["utilities.virt"] = MagicMock()
sys.modules["utilities.infra"] = MagicMock()

import pytest
from timeout_sampler import TimeoutExpiredError

from utilities.hco import (
    ResourceEditorValidateHCOReconcile,
    add_labels_to_nodes,
    get_hco_spec,
    get_hco_version,
    get_installed_hco_csv,
    get_json_patch_annotation_values,
    update_common_boot_image_import_spec,
    wait_for_hco_conditions,
)


class TestResourceEditorValidateHCOReconcile:
    """Test cases for ResourceEditorValidateHCOReconcile class"""

    @pytest.mark.unit
    def test_enter_patches_resource(self):
        """Test that __enter__ patches the resource correctly"""
        mock_patches = [{"op": "add", "path": "/spec/test", "value": "test"}]
        mock_resource = Mock()
        mock_resource.name = "test-hco"

        editor = ResourceEditorValidateHCOReconcile(
            patches=mock_patches,
            resource=mock_resource,
            action="add",
        )

        with patch.object(editor, "resource_editor") as mock_resource_editor:
            mock_context = Mock()
            mock_resource_editor.__enter__.return_value = mock_context

            result = editor.__enter__()

            assert result == mock_context
            mock_resource_editor.__enter__.assert_called_once()


class TestWaitForHcoConditions:
    """Test cases for wait_for_hco_conditions function"""

    @pytest.mark.unit
    @patch("utilities.hco.TimeoutSampler")
    def test_wait_for_hco_conditions_success(self, mock_sampler_class):
        """Test successful HCO conditions wait"""
        mock_hco = Mock()
        mock_hco.name = "kubevirt-hyperconverged"
        mock_hco.status = {
            "conditions": [
                {"type": "Available", "status": "True"},
                {"type": "Progressing", "status": "False"},
                {"type": "Degraded", "status": "False"},
            ],
        }
        expected_conditions = {
            "Available": "True",
            "Progressing": "False",
            "Degraded": "False",
        }

        # Mock sampler to succeed immediately
        mock_sampler = Mock()
        mock_sampler.__iter__.return_value = iter([True])
        mock_sampler_class.return_value = mock_sampler

        wait_for_hco_conditions(
            hco=mock_hco,
            expected_conditions=expected_conditions,
        )

        mock_sampler_class.assert_called_once()

    @pytest.mark.unit
    @patch("utilities.hco.LOGGER")
    @patch("utilities.hco.TimeoutSampler")
    def test_wait_for_hco_conditions_timeout(self, mock_sampler_class, mock_logger):
        """Test HCO conditions wait timeout"""
        mock_hco = Mock()
        mock_hco.name = "kubevirt-hyperconverged"
        expected_conditions = {"Available": "True"}

        # Mock sampler to timeout
        mock_sampler = Mock()
        mock_sampler.__iter__.side_effect = TimeoutExpiredError("Timeout")
        mock_sampler_class.return_value = mock_sampler

        with pytest.raises(TimeoutExpiredError):
            wait_for_hco_conditions(
                hco=mock_hco,
                expected_conditions=expected_conditions,
            )

        mock_logger.error.assert_called()


class TestAddLabelsToNodes:
    """Test cases for add_labels_to_nodes function"""

    @pytest.mark.unit
    @patch("utilities.hco.ResourceEditor")
    def test_add_labels_to_nodes_single_node(self, mock_editor_class):
        """Test adding labels to a single node"""
        mock_node = Mock()
        mock_node.metadata = {"name": "node1"}
        nodes = [mock_node]
        node_labels = {"test-label": "test-value"}

        mock_editor_instance = Mock()
        mock_editor_class.return_value = mock_editor_instance

        add_labels_to_nodes(nodes, node_labels)

        # Verify ResourceEditor was called with correct patches
        mock_editor_class.assert_called_once()
        patches = mock_editor_class.call_args[1]["patches"]
        assert len(patches) == 1
        assert patches[0]["op"] == "add"
        assert patches[0]["path"] == "/metadata/labels/test-label"
        assert patches[0]["value"] == "test-value"

    @pytest.mark.unit
    @patch("utilities.hco.ResourceEditor")
    def test_add_labels_to_nodes_multiple_labels(self, mock_editor_class):
        """Test adding multiple labels to nodes"""
        mock_node = Mock()
        nodes = [mock_node]
        node_labels = {
            "label1": "value1",
            "label2": "value2",
            "label3": "value3",
        }

        add_labels_to_nodes(nodes, node_labels)

        # Verify all labels were added
        patches = mock_editor_class.call_args[1]["patches"]
        assert len(patches) == 3
        assert all(p["op"] == "add" for p in patches)


class TestGetHcoSpec:
    """Test cases for get_hco_spec function"""

    @pytest.mark.unit
    @patch("utilities.hco.HyperConverged")
    def test_get_hco_spec_success(self, mock_hco_class):
        """Test successfully getting HCO spec"""
        mock_admin_client = Mock()
        mock_hco_namespace = Mock()
        mock_hco_namespace.name = "openshift-cnv"

        mock_hco_instance = Mock()
        mock_hco_instance.instance = Mock(spec={"test": "spec"})
        mock_hco_class.return_value = mock_hco_instance

        result = get_hco_spec(mock_admin_client, mock_hco_namespace)

        assert result == {"test": "spec"}
        mock_hco_class.assert_called_once_with(
            client=mock_admin_client,
            name="kubevirt-hyperconverged",
            namespace=mock_hco_namespace.name,
        )


class TestGetInstalledHcoCsv:
    """Test cases for get_installed_hco_csv function"""

    @pytest.mark.unit
    @patch("utilities.hco.ClusterServiceVersion")
    def test_get_installed_hco_csv_found(self, mock_csv_class):
        """Test finding installed HCO CSV"""
        mock_admin_client = Mock()
        mock_hco_namespace = Mock()
        mock_hco_namespace.name = "openshift-cnv"

        # Mock CSV objects
        mock_csv1 = Mock()
        mock_csv1.name = "other-operator.v1.0.0"
        mock_csv1.instance.status.phase = "Succeeded"

        mock_csv2 = Mock()
        mock_csv2.name = "kubevirt-hyperconverged-operator.v4.14.0"
        mock_csv2.instance.status.phase = "Succeeded"

        mock_csv_class.get.return_value = [mock_csv1, mock_csv2]

        result = get_installed_hco_csv(mock_admin_client, mock_hco_namespace)

        assert result == mock_csv2

    @pytest.mark.unit
    @patch("utilities.hco.ClusterServiceVersion")
    def test_get_installed_hco_csv_not_found(self, mock_csv_class):
        """Test when no HCO CSV is found"""
        mock_admin_client = Mock()
        mock_hco_namespace = Mock()

        mock_csv_class.get.return_value = []

        result = get_installed_hco_csv(mock_admin_client, mock_hco_namespace)

        assert result is None


class TestGetHcoVersion:
    """Test cases for get_hco_version function"""

    @pytest.mark.unit
    @patch("utilities.hco.get_installed_hco_csv")
    def test_get_hco_version_success(self, mock_get_csv):
        """Test successfully getting HCO version"""
        mock_client = Mock()
        hco_ns_name = "openshift-cnv"

        mock_csv = Mock()
        mock_csv.instance.spec.version = "4.14.0"
        mock_get_csv.return_value = mock_csv

        result = get_hco_version(mock_client, hco_ns_name)

        assert result == "4.14.0"

    @pytest.mark.unit
    @patch("utilities.hco.get_installed_hco_csv")
    def test_get_hco_version_no_csv(self, mock_get_csv):
        """Test when no CSV is found"""
        mock_get_csv.return_value = None

        result = get_hco_version(Mock(), "openshift-cnv")

        assert result is None


class TestGetJsonPatchAnnotationValues:
    """Test cases for get_json_patch_annotation_values function"""

    @pytest.mark.unit
    def test_get_json_patch_annotation_values_add(self):
        """Test creating JSON patch annotation for add operation"""
        result = get_json_patch_annotation_values(
            component="kubevirt",
            path="/spec/configuration/testConfig",
            value="testValue",
            op="add",
        )

        expected = [{"op": "add", "path": "/spec/configuration/testConfig", "value": "testValue"}]
        assert json.loads(result) == expected

    @pytest.mark.unit
    def test_get_json_patch_annotation_values_remove(self):
        """Test creating JSON patch annotation for remove operation"""
        result = get_json_patch_annotation_values(
            component="cdi",
            path="/spec/config/testConfig",
            op="remove",
        )

        expected = [{"op": "remove", "path": "/spec/config/testConfig"}]
        assert json.loads(result) == expected

    @pytest.mark.unit
    def test_get_json_patch_annotation_values_replace(self):
        """Test creating JSON patch annotation for replace operation"""
        result = get_json_patch_annotation_values(
            component="ssp",
            path="/spec/commonTemplates",
            value=["template1", "template2"],
            op="replace",
        )

        expected = [{"op": "replace", "path": "/spec/commonTemplates", "value": ["template1", "template2"]}]
        assert json.loads(result) == expected


class TestUpdateCommonBootImageImportSpec:
    """Test cases for update_common_boot_image_import_spec function"""

    @pytest.mark.unit
    @patch("utilities.hco.ResourceEditor")
    def test_update_common_boot_image_import_spec_enable(self, mock_editor_class):
        """Test enabling common boot image import"""
        mock_hco = Mock()
        mock_hco.instance.spec = {}

        update_common_boot_image_import_spec(mock_hco, enable=True)

        # Verify ResourceEditor was called with correct patch
        patches = mock_editor_class.call_args[1]["patches"]
        assert len(patches) == 1
        assert patches[0]["op"] == "add"
        assert patches[0]["path"] == "/spec/featureGates/enableCommonBootImageImport"
        assert patches[0]["value"] is True

    @pytest.mark.unit
    @patch("utilities.hco.ResourceEditor")
    def test_update_common_boot_image_import_spec_disable(self, mock_editor_class):
        """Test disabling common boot image import"""
        mock_hco = Mock()
        mock_hco.instance.spec = {"featureGates": {"enableCommonBootImageImport": True}}

        update_common_boot_image_import_spec(mock_hco, enable=False)

        # Verify ResourceEditor was called with correct patch
        patches = mock_editor_class.call_args[1]["patches"]
        assert len(patches) == 1
        assert patches[0]["op"] == "add"
        assert patches[0]["path"] == "/spec/featureGates/enableCommonBootImageImport"
        assert patches[0]["value"] is False
