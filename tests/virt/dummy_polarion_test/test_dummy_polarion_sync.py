"""Dummy tests for verifying Polarion sync pipeline.

STP: https://redhat.atlassian.net/browse/CNV-61530

This file exists solely to test the polarion_sync scanner/injector.
Delete after testing.
"""

import pytest


@pytest.mark.polarion("CNV-11111")
def test_already_linked():
    """This test already has a Polarion marker — scanner should skip it."""
    assert True


class TestDummyVmOperations:
    """Dummy VM operations for polarion sync testing.

    STP: https://redhat.atlassian.net/browse/CNV-61530
    """

    def test_vm_start(self):
        """Test that a VM can be started.

        Preconditions:
            - A running VM
        Steps:
            - Start the VM
        Expected:
            - VM starts successfully
        """
        assert True

    def test_vm_stop(self):
        """Test that a VM can be stopped.

        Preconditions:
            - A running VM
        Steps:
            - Stop the VM
        Expected:
            - VM stops successfully
        """
        assert True


def test_standalone_function():
    """Test a standalone function without a class.

    Jira: https://redhat.atlassian.net/browse/CNV-87822
    """
    assert True
