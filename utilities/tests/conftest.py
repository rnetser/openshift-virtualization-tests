"""Pytest configuration for utilities tests - independent of main project"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Set architecture environment variable to prevent K8s API calls
os.environ["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = "x86_64"

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock get_client to prevent K8s API calls
from ocp_resources import resource
resource.get_client = lambda: MagicMock()

# Create mock modules to break circular imports
sys.modules['utilities.data_collector'] = MagicMock()
sys.modules['utilities.data_collector'].get_data_collector_base_directory = lambda: "/tmp/data"
sys.modules['utilities.data_collector'].collect_alerts_data = MagicMock()

import pytest


# Mock fixtures for common dependencies
@pytest.fixture
def mock_k8s_client():
    """Mock Kubernetes dynamic client"""
    client = MagicMock()
    client.resources.get.return_value = MagicMock()
    return client


@pytest.fixture
def mock_ocp_resource():
    """Mock base OCP resource"""
    resource = MagicMock()
    resource.exists = True
    resource.instance = MagicMock()
    resource.name = "test-resource"
    resource.namespace = "test-namespace"
    return resource


@pytest.fixture(autouse=True)
def mock_get_client(monkeypatch):
    """Auto-mock get_client for all tests"""
    mock_client = MagicMock()
    monkeypatch.setattr("ocp_resources.resource.get_client", lambda: mock_client)
    return mock_client


@pytest.fixture
def mock_node():
    """Mock Node resource"""
    node = MagicMock()
    node.name = "test-node"
    node.labels = {"kubernetes.io/arch": "x86_64"}
    node.status = {"conditions": []}
    return node


@pytest.fixture
def mock_vm():
    """Mock VirtualMachine resource"""
    vm = MagicMock()
    vm.name = "test-vm"
    vm.namespace = "test-namespace"
    vm.status = "Running"
    vm.instance = MagicMock()
    return vm


@pytest.fixture
def mock_pod():
    """Mock Pod resource"""
    pod = MagicMock()
    pod.name = "test-pod"
    pod.namespace = "test-namespace"
    pod.status = {"phase": "Running"}
    return pod


@pytest.fixture
def mock_hco():
    """Mock HyperConverged resource"""
    hco = MagicMock()
    hco.name = "kubevirt-hyperconverged"
    hco.namespace = "openshift-cnv"
    hco.instance = MagicMock()
    hco.instance.spec = {"certConfig": {}, "infra": {}}
    return hco


@pytest.fixture
def mock_csv():
    """Mock ClusterServiceVersion resource"""
    csv = MagicMock()
    csv.name = "kubevirt-hyperconverged-operator.v4.14.0"
    csv.namespace = "openshift-cnv"
    csv.instance = MagicMock()
    return csv


@pytest.fixture
def temp_file(tmp_path):
    """Create a temporary file for testing"""
    file_path = tmp_path / "test_file.txt"
    file_path.write_text("test content")
    return file_path


@pytest.fixture
def mock_logger(monkeypatch):
    """Mock logger to avoid actual logging during tests"""
    mock_log = MagicMock()
    monkeypatch.setattr("logging.getLogger", lambda name: mock_log)
    return mock_log
