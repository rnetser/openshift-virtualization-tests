import logging
import re

from ocp_resources.node import Node
from ocp_resources.resource import Resource

from utilities.constants import (
    CPU_MODEL_LABEL_PREFIX,
    EXCLUDED_CPU_MODELS,
    EXCLUDED_OLD_CPU_MODELS,
    KUBERNETES_ARCH_LABEL,
)

LOGGER = logging.getLogger(__name__)
HOST_MODEL_CPU_LABEL = f"host-model-cpu.node.{Resource.ApiGroup.KUBEVIRT_IO}"


def get_nodes_cpu_model(nodes):
    """
    Checks the cpu model labels on each nodes passed and returns a dictionary of nodes and supported nodes

    :param nodes (list) : Nodes, for which cpu model labels are to be checked

    :return: Dict of nodes and associated cpu models
    """

    nodes_cpu_model = {"common": {}, "modern": {}}
    for node in nodes:
        nodes_cpu_model["common"][node.name] = set()
        nodes_cpu_model["modern"][node.name] = set()
        for label, value in node.labels.items():
            match_object = re.match(rf"{CPU_MODEL_LABEL_PREFIX}/(.*)", label)
            if is_cpu_model_not_in_excluded_list(
                filter_list=EXCLUDED_CPU_MODELS, match=match_object, label_value=value
            ):
                nodes_cpu_model["common"][node.name].add(match_object.group(1))
            if is_cpu_model_not_in_excluded_list(
                filter_list=EXCLUDED_OLD_CPU_MODELS, match=match_object, label_value=value
            ):
                nodes_cpu_model["modern"][node.name].add(match_object.group(1))
    return nodes_cpu_model


def is_cpu_model_not_in_excluded_list(filter_list, match, label_value):
    return bool(match and label_value == "true" and not any(element in match.group(1) for element in filter_list))


def get_host_model_cpu(nodes):
    nodes_host_model_cpu = {}
    for node in nodes:
        for label, value in node.labels.items():
            match_object = re.match(rf"{HOST_MODEL_CPU_LABEL}/(.*)", label)
            if match_object and value == "true":
                nodes_host_model_cpu[node.name] = match_object.group(1)
    assert len(nodes_host_model_cpu) == len(nodes), (
        f"All nodes did not have host-model-cpu label: {nodes_host_model_cpu} "
    )
    return nodes_host_model_cpu


def find_common_cpu_model_for_live_migration(cluster_cpu, host_cpu_model):
    if cluster_cpu:
        if len(set(host_cpu_model.values())) == 1:
            LOGGER.info(f"Host model cpus for all nodes are same {host_cpu_model}. No common cpus are needed")
            return None
        else:
            LOGGER.info(f"Using cluster node cpu: {cluster_cpu}")
            return cluster_cpu
    # if we reach here, it is heterogeneous cluster, we would return None
    LOGGER.warning("This is a heterogeneous cluster with no common cluster cpu.")
    return None


def get_common_cpu_from_nodes(cluster_cpus):
    """
    Receives a set of unique common cpus between all the schedulable nodes and returns one from the set
    """
    return next(iter(cluster_cpus)) if cluster_cpus else None


def get_nodes_cpu_architecture(nodes: list[Node]) -> str:
    nodes_cpu_arch = {node.labels[KUBERNETES_ARCH_LABEL] for node in nodes}
    assert len(nodes_cpu_arch) == 1, "Mixed CPU architectures in the cluster is not supported"
    return next(iter(nodes_cpu_arch))
