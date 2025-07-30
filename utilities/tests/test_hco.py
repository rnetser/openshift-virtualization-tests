"""Unit tests for hco module"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from timeout_sampler import TimeoutExpiredError

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock modules to break circular imports
sys.modules["utilities.virt"] = MagicMock()
sys.modules["utilities.infra"] = MagicMock()

from utilities.hco import (  # noqa: E402
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

    @patch("utilities.hco.ResourceEditor")
    def test_enter_patches_resource(self, mock_resource_editor):
        """Test that __enter__ patches the resource correctly"""
        mock_resource = MagicMock()
        mock_resource.instance.spec = {"certConfig": {"some": "config"}}
        mock_reconcile_complete = MagicMock()

        editor = ResourceEditorValidateHCOReconcile(
            patches={"spec": {"certConfig": {"new": "config"}}},
            resource=mock_resource,
        )

        # Call __enter__
        result = editor.__enter__()

        assert result == editor
        mock_reconcile_complete.assert_called_once()


class TestWaitForHcoConditions:
    """Test cases for wait_for_hco_conditions function"""

    @patch("hco.TimeoutSampler")
    def test_wait_for_hco_conditions_success(self, mock_sampler_class):
        """Test successful HCO conditions wait"""
        mock_hco = MagicMock()
        mock_hco.instance.status.conditions = [
            {"type": "Available", "status": "True"},
            {"type": "Progressing", "status": "False"},
            {"type": "Degraded", "status": "False"},
        ]

        # Mock sampler to succeed immediately
        mock_sampler = MagicMock()

        def sampler_iterator():
            yield True

        mock_sampler.__iter__ = sampler_iterator
        mock_sampler_class.return_value = mock_sampler

        wait_for_hco_conditions(mock_hco, "openshift-cnv")

        mock_sampler_class.assert_called_once()

    @patch("hco.TimeoutSampler")
    def test_wait_for_hco_conditions_timeout(self, mock_sampler_class):
        """Test HCO conditions wait timeout"""
        mock_hco = MagicMock()
        mock_hco.instance.status.conditions = [
            {"type": "Available", "status": "False"},
        ]

        # Mock sampler to timeout
        mock_sampler = MagicMock()

        def sampler_iterator():
            raise TimeoutExpiredError("Timeout")

        mock_sampler.__iter__ = sampler_iterator
        mock_sampler_class.return_value = mock_sampler

        with pytest.raises(TimeoutExpiredError):
            wait_for_hco_conditions(mock_hco, "openshift-cnv")


class TestAddLabelsToNodes:
    """Test cases for add_labels_to_nodes function"""

    @patch("utilities.hco.ResourceEditor")
    def test_add_labels_to_nodes_single_node(self, mock_editor_class):
        """Test adding labels to a single node"""
        mock_node = MagicMock()
        mock_node.name = "test-node"
        mock_node.labels = {"existing": "label"}
        labels = {"new-label": "new-value"}

        result = add_labels_to_nodes([mock_node], labels)

        # Verify ResourceEditor was called with correct patches
        mock_editor_class.assert_called_once()
        args, kwargs = mock_editor_class.call_args
        expected_patches = {mock_node: {"metadata": {"labels": {"new-label": "new-value1"}}}}
        assert kwargs["patches"] == expected_patches
        assert isinstance(result, dict)

    @patch("utilities.hco.ResourceEditor")
    def test_add_labels_to_nodes_multiple_labels(self, mock_editor_class):
        """Test adding multiple labels to nodes"""
        mock_node = MagicMock()
        mock_node.name = "test-node"
        labels = {"label1": "value1", "label2": "value2"}

        result = add_labels_to_nodes([mock_node], labels)

        args, kwargs = mock_editor_class.call_args
        expected_patches = {mock_node: {"metadata": {"labels": {"label1": "value11", "label2": "value21"}}}}
        assert kwargs["patches"] == expected_patches
        assert isinstance(result, dict)


class TestGetHcoSpec:
    """Test cases for get_hco_spec function"""

    @patch("hco.utilities")
    def test_get_hco_spec_success(self, mock_utilities):
        """Test getting HCO spec successfully"""
        mock_admin_client = MagicMock()
        mock_hco_namespace = MagicMock()
        mock_hco_namespace.name = "openshift-cnv"
        expected_spec = {"certConfig": {"test": "config"}}

        mock_hco = MagicMock()
        mock_hco.instance.spec = expected_spec
        mock_utilities.infra.get_hyperconverged_resource.return_value = mock_hco

        result = get_hco_spec(mock_admin_client, mock_hco_namespace)

        assert result == expected_spec
        mock_utilities.infra.get_hyperconverged_resource.assert_called_once_with(
            client=mock_admin_client,
            hco_ns_name=mock_hco_namespace.name,
        )


class TestGetInstalledHcoCsv:
    """Test cases for get_installed_hco_csv function"""

    @patch("hco.utilities")
    @patch("hco.ClusterServiceVersion")
    def test_get_installed_hco_csv_found(self, mock_csv_class, mock_utilities):
        """Test finding installed HCO CSV"""
        mock_admin_client = MagicMock()
        mock_hco_namespace = MagicMock()
        mock_hco_namespace.name = "openshift-cnv"

        # Mock subscription
        mock_subscription = MagicMock()
        mock_subscription.instance.status.installedCSV = "hco-operator.v4.14.0"
        mock_utilities.infra.get_subscription.return_value = mock_subscription

        # Mock CSV
        mock_csv = MagicMock()
        mock_csv_class.return_value = mock_csv

        result = get_installed_hco_csv(mock_admin_client, mock_hco_namespace)

        assert result == mock_csv
        mock_csv_class.assert_called_once_with(
            client=mock_admin_client,
            name="hco-operator.v4.14.0",
            namespace=mock_hco_namespace.name,
        )

    @patch("hco.utilities")
    def test_get_installed_hco_csv_not_found(self, mock_utilities):
        """Test when subscription has no installed CSV"""
        mock_admin_client = MagicMock()
        mock_hco_namespace = MagicMock()

        # Mock subscription without installedCSV
        mock_subscription = MagicMock()
        mock_subscription.instance.status.installedCSV = None
        mock_utilities.infra.get_subscription.return_value = mock_subscription

        result = get_installed_hco_csv(mock_admin_client, mock_hco_namespace)

        assert result is None


class TestGetHcoVersion:
    """Test cases for get_hco_version function"""

    @patch("hco.utilities")
    @patch("hco.get_installed_hco_csv")
    def test_get_hco_version_success(self, mock_get_csv, mock_utilities):
        """Test getting HCO version successfully"""
        mock_client = MagicMock()
        hco_ns_name = "openshift-cnv"

        # Mock HCO resource
        mock_hco = MagicMock()
        mock_utilities.infra.get_hyperconverged_resource.return_value = mock_hco

        # Mock CSV
        mock_csv = MagicMock()
        mock_csv.instance.spec.version = "4.14.0"
        mock_get_csv.return_value = mock_csv

        result = get_hco_version(mock_client, hco_ns_name)

        assert result == "4.14.0"

    @patch("hco.utilities")
    @patch("hco.get_installed_hco_csv")
    def test_get_hco_version_no_csv(self, mock_get_csv, mock_utilities):
        """Test getting HCO version when no CSV found"""
        mock_client = MagicMock()
        mock_utilities.infra.get_hyperconverged_resource.return_value = MagicMock()
        mock_get_csv.return_value = None

        result = get_hco_version(mock_client, "openshift-cnv")

        assert result is None


class TestGetJsonPatchAnnotationValues:
    """Test cases for get_json_patch_annotation_values function"""

    def test_get_json_patch_annotation_values_add(self):
        """Test creating JSON patch for add operation"""
        result = get_json_patch_annotation_values(
            operation_type="add",
            annotation_path="/metadata/annotations/test",
            annotation_value="test-value",
        )

        assert isinstance(result, str)
        patches = json.loads(result)
        assert len(patches) == 1
        assert patches[0]["op"] == "add"
        assert patches[0]["path"] == "/metadata/annotations/test"
        assert patches[0]["value"] == "test-value"

    def test_get_json_patch_annotation_values_remove(self):
        """Test creating JSON patch for remove operation"""
        result = get_json_patch_annotation_values(
            operation_type="remove",
            annotation_path="/metadata/annotations/test",
        )

        assert isinstance(result, str)
        patches = json.loads(result)
        assert len(patches) == 1
        assert patches[0]["op"] == "remove"
        assert patches[0]["path"] == "/metadata/annotations/test"

    def test_get_json_patch_annotation_values_replace(self):
        """Test creating JSON patch for replace operation"""
        result = get_json_patch_annotation_values(
            operation_type="replace",
            annotation_path="/metadata/annotations/test",
            annotation_value="new-value",
        )

        assert isinstance(result, str)
        patches = json.loads(result)
        assert len(patches) == 1
        assert patches[0]["op"] == "replace"
        assert patches[0]["path"] == "/metadata/annotations/test"
        assert patches[0]["value"] == "new-value"


class TestUpdateCommonBootImageImportSpec:
    """Test cases for update_common_boot_image_import_spec function"""

    @patch("utilities.hco.ResourceEditor")
    @patch("hco.TimeoutSampler")
    def test_update_common_boot_image_import_spec_enable(
        self,
        mock_sampler_class,
        mock_editor_class,
    ):
        """Test enabling common boot image import"""
        mock_hco = MagicMock()
        mock_hco.instance.spec = {"dataImportCronTemplates": []}

        # Mock sampler to succeed
        mock_sampler = MagicMock()
        mock_sampler.__iter__ = lambda self: iter([True])
        mock_sampler_class.return_value = mock_sampler

        update_common_boot_image_import_spec(mock_hco, enable=True)

        # Verify ResourceEditor was called
        mock_editor_class.assert_called_once()
        args, kwargs = mock_editor_class.call_args
        assert kwargs["patches"]["spec"]["enableCommonBootImageImport"] is True

    @patch("utilities.hco.ResourceEditor")
    @patch("hco.TimeoutSampler")
    def test_update_common_boot_image_import_spec_disable(
        self,
        mock_sampler_class,
        mock_editor_class,
    ):
        """Test disabling common boot image import"""
        mock_hco = MagicMock()
        mock_hco.instance.spec = {"dataImportCronTemplates": []}

        # Mock sampler to succeed
        mock_sampler = MagicMock()
        mock_sampler.__iter__ = lambda self: iter([True])
        mock_sampler_class.return_value = mock_sampler

        update_common_boot_image_import_spec(mock_hco, enable=False)

        # Verify ResourceEditor was called
        mock_editor_class.assert_called_once()
        args, kwargs = mock_editor_class.call_args
        assert kwargs["patches"]["spec"]["enableCommonBootImageImport"] is False
