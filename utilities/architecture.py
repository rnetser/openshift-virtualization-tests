import os
from typing import Any

from ocp_resources.node import Node
from ocp_resources.resource import Resource, get_client

import utilities.constants as constants


def get_nodes_cpu_architecture(nodes: list[Node]) -> str:
    nodes_cpu_arch = {node.labels[f"{Resource.ApiGroup.KUBERNETES_IO}/arch"] for node in nodes}
    assert len(nodes_cpu_arch) == 1, "Mixed CPU architectures in the cluster is not supported"
    return next(iter(nodes_cpu_arch))


def get_test_images_arch_class() -> Any:
    # Needed for CI
    arch = os.environ.get("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH")

    if not arch:
        nodes: list[Node] = list(Node.get(dyn_client=get_client()))
        arch = get_nodes_cpu_architecture(nodes=nodes)

    arch = constants.X86_64 if arch == constants.AMD_64 else arch

    if arch not in (constants.X86_64, constants.ARM_64, constants.S390X):
        raise ValueError(f"{arch} architecture in not supported")

    return getattr(constants.ArchImages, arch.upper())
