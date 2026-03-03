import logging

import pytest

from utilities.virt import VirtualMachineForTests, fedora_vm_body, running_vm

LOGGER = logging.getLogger(__name__)


@pytest.mark.arm64
@pytest.mark.smoke
@pytest.mark.polarion("CNV-5501")
def test_container_disk_vm(
    namespace,
    unprivileged_client,
):
    LOGGER.error("this is a test message")
    name = "container-disk-vm"
    with VirtualMachineForTests(
        namespace=namespace.name,
        name=name,
        client=unprivileged_client,
        body=fedora_vm_body(name=name),
    ) as vm:
        running_vm(vm=vm)
