from ocp_utilities.exceptions import NodeNotReadyError, NodeUnschedulableError
from ocp_utilities.infra import assert_nodes_in_healthy_condition, assert_nodes_schedulable
from pytest_testconfig import config as py_config
from timeout_sampler import TimeoutExpiredError

from utilities.constants import IMAGE_CRON_STR, KUBELET_READY_CONDITION
from utilities.exceptions import ClusterSanityError, StorageSanityError
from utilities.hco import wait_for_hco_conditions
from utilities.infra import LOGGER, wait_for_pods_running
from utilities.pytest_utils import exit_pytest_execution


def storage_sanity_check(cluster_storage_classes_names):
    config_sc = list([[*csc][0] for csc in py_config["storage_class_matrix"]])
    exists_sc = [scn for scn in config_sc if scn in cluster_storage_classes_names]
    if sorted(config_sc) != sorted(exists_sc):
        LOGGER.error(f"Expected {config_sc}, On cluster {exists_sc}")
        return False
    return True


def cluster_sanity(
    request,
    admin_client,
    cluster_storage_classes_names,
    nodes,
    hco_namespace,
    hco_status_conditions,
    expected_hco_status,
    junitxml_property=None,
):
    if "cluster_health_check" in request.config.getoption("-m"):
        LOGGER.warning("Skipping cluster sanity test, got -m cluster_health_check")
        return

    skip_cluster_sanity_check = "--cluster-sanity-skip-check"
    skip_storage_classes_check = "--cluster-sanity-skip-storage-check"
    skip_nodes_check = "--cluster-sanity-skip-nodes-check"
    exceptions_filename = "cluster_sanity_failure.txt"
    try:
        if request.session.config.getoption(skip_cluster_sanity_check):
            LOGGER.warning(f"Skipping cluster sanity check, got {skip_cluster_sanity_check}")
            return
        LOGGER.info(
            f"Running cluster sanity. (To skip cluster sanity check pass {skip_cluster_sanity_check} to pytest)"
        )
        # Check storage class only if --cluster-sanity-skip-storage-check not passed to pytest.
        if request.session.config.getoption(skip_storage_classes_check):
            LOGGER.warning(f"Skipping storage classes check, got {skip_storage_classes_check}")
        else:
            LOGGER.info(
                f"Check storage classes sanity. (To skip storage class sanity check pass {skip_storage_classes_check} "
                f"to pytest)"
            )
            if not storage_sanity_check(cluster_storage_classes_names=cluster_storage_classes_names):
                raise StorageSanityError(
                    err_str=f"Cluster is missing storage class.\n"
                    f"either run with '--storage-class-matrix' or with '{skip_storage_classes_check}'"
                )

        # Check nodes only if --cluster-sanity-skip-nodes-check not passed to pytest.
        if request.session.config.getoption(skip_nodes_check):
            LOGGER.warning(f"Skipping nodes check, got {skip_nodes_check}")

        else:
            # validate that all the nodes are ready and schedulable and CNV pods are running
            LOGGER.info(f"Check nodes sanity. (To skip nodes sanity check pass {skip_nodes_check} to pytest)")
            assert_nodes_in_healthy_condition(nodes=nodes, healthy_node_condition_type=KUBELET_READY_CONDITION)
            assert_nodes_schedulable(nodes=nodes)

            try:
                wait_for_pods_running(
                    admin_client=admin_client,
                    namespace=hco_namespace,
                    filter_pods_by_name=IMAGE_CRON_STR,
                )
            except TimeoutExpiredError as timeout_error:
                LOGGER.error(timeout_error)
                raise ClusterSanityError(
                    err_str=f"Timed out waiting for all pods in namespace {hco_namespace.name} to get to running state."
                )
        # Wait for hco to be healthy
        wait_for_hco_conditions(
            admin_client=admin_client,
            hco_namespace=hco_namespace,
        )
    except (ClusterSanityError, NodeUnschedulableError, NodeNotReadyError, StorageSanityError) as ex:
        exit_pytest_execution(
            filename=exceptions_filename,
            message=str(ex),
            junitxml_property=junitxml_property,
        )
