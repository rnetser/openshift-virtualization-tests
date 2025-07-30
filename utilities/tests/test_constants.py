"""Unit tests for constants module"""

import sys
from pathlib import Path

import pytest

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import constants


class TestConstants:
    """Test cases for constants module"""

    def test_architecture_constants(self):
        """Test architecture-related constants"""
        assert constants.AMD_64 == "amd64"
        assert constants.ARM_64 == "arm64"
        assert constants.S390X == "s390x"
        assert constants.X86_64 == "x86_64"
        assert constants.KUBERNETES_ARCH_LABEL == "kubernetes.io/arch"

    def test_timeout_constants(self):
        """Test timeout-related constants"""
        assert constants.TIMEOUT_1MIN == 60
        assert constants.TIMEOUT_2MIN == 120
        assert constants.TIMEOUT_3MIN == 180
        assert constants.TIMEOUT_5MIN == 300
        assert constants.TIMEOUT_10MIN == 600
        assert constants.TIMEOUT_15MIN == 900
        assert constants.TIMEOUT_20MIN == 1200
        assert constants.TIMEOUT_30MIN == 1800
        assert constants.TIMEOUT_1HOUR == 3600
        assert constants.TIMEOUT_2HOUR == 7200

    def test_tcp_timeout_constants(self):
        """Test TCP timeout constants"""
        assert constants.TCP_TIMEOUT_30SEC == 30

    def test_memory_constants(self):
        """Test memory-related constants"""
        assert constants.ONE_GI_MEMORY == "1Gi"
        assert constants.TWO_GI_MEMORY == "2Gi"
        assert constants.FOUR_GI_MEMORY == "4Gi"

    def test_cpu_constants(self):
        """Test CPU-related constants"""
        assert constants.EIGHT_CPU_SOCKETS == 8

    def test_state_constants(self):
        """Test state-related constants"""
        assert constants.PENDING_STATE == "pending"
        assert constants.FIRING_STATE == "firing"

    def test_cnv_operator_constants(self):
        """Test CNV operator constants"""
        assert constants.OPENSHIFT_CNV_NAMESPACE == "openshift-cnv"
        assert constants.SSP_KUBEVIRT_HYPERCONVERGED == "ssp-kubevirt-hyperconverged"
        assert constants.ENABLE_COMMON_BOOT_IMAGE_IMPORT == "enableCommonBootImageImport"

    def test_storage_classes(self):
        """Test storage class constants"""
        assert hasattr(constants, "StorageClasses")
        # Check that StorageClasses has expected attributes
        storage_classes = constants.StorageClasses
        assert hasattr(storage_classes, "NFS")
        assert hasattr(storage_classes, "DEFAULT_SC")

    def test_operator_health_impact_values(self):
        """Test operator health impact values"""
        assert hasattr(constants, "OPERATOR_HEALTH_IMPACT_VALUES")
        assert isinstance(constants.OPERATOR_HEALTH_IMPACT_VALUES, dict)
        # Should have standard health impact keys
        expected_keys = ["none", "warning", "critical"]
        for key in expected_keys:
            assert key in constants.OPERATOR_HEALTH_IMPACT_VALUES

    def test_images_class_exists(self):
        """Test that Images class exists"""
        assert hasattr(constants, "Images")
        # The Images class should have various image constants
        images = constants.Images
        # Check for some expected attributes
        assert hasattr(images, "__class__")

    def test_data_import_cron_prefix(self):
        """Test data import cron prefix constant"""
        assert hasattr(constants, "DATA_IMPORT_CRON_PREFIX")
        assert isinstance(constants.DATA_IMPORT_CRON_PREFIX, str)

    def test_os_prefix_mapping(self):
        """Test OS prefix mapping exists"""
        assert hasattr(constants, "OS_PREFIX_MAPPING")
        assert isinstance(constants.OS_PREFIX_MAPPING, dict)

    def test_windows_os_disk_image(self):
        """Test Windows OS disk image constant"""
        assert hasattr(constants, "WINDOWS_OS_DISK_IMAGE")
        assert isinstance(constants.WINDOWS_OS_DISK_IMAGE, str)

    def test_workload_constants(self):
        """Test workload-related constants"""
        assert hasattr(constants, "WORKLOAD")
        assert hasattr(constants, "FLAVOR")

    def test_network_constants(self):
        """Test network-related constants"""
        # Check for network binding constants if they exist
        if hasattr(constants, "MULTUS"):
            assert isinstance(constants.MULTUS, str)
        if hasattr(constants, "MASQUERADE"):
            assert isinstance(constants.MASQUERADE, str) 