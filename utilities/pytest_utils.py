import getpass
import importlib
import logging
import os
import re
import shutil
import socket
import sys
from typing import Any

from ocp_resources.config_map import ConfigMap
from ocp_resources.namespace import Namespace
from ocp_resources.resource import ResourceEditor
from ocp_resources.template import Template
from pytest_testconfig import config as py_config

from utilities.bitwarden import get_cnv_tests_secret_by_name
from utilities.constants import (
    CNV_TEST_RUN_IN_PROGRESS,
    CNV_TEST_RUN_IN_PROGRESS_NS,
    CNV_TESTS_CONTAINER,
    DV_SIZE_STR,
    FLAVOR_STR,
    IMAGE_NAME_STR,
    IMAGE_PATH_STR,
    LATEST_RELEASE_STR,
    OS_STR,
    OS_VERSION_STR,
    POD_SECURITY_NAMESPACE_LABELS,
    TEMPLATE_LABELS_STR,
    TIMEOUT_2MIN,
    WIN_2K22,
    WIN_2K25,
    WIN_10,
    WIN_11,
    WORKLOAD_STR,
    Images,
)
from utilities.exceptions import MissingEnvironmentVariableError
from utilities.infra import exit_pytest_execution

LOGGER = logging.getLogger(__name__)


def get_base_matrix_name(matrix_name):
    match = re.match(r".*?(.*?_matrix)_(?:.*_matrix)+", matrix_name)
    if match:
        return match.group(1)

    return matrix_name


def get_matrix_params(pytest_config, matrix_name):
    """
    Customize matrix based on existing matrix
    Name should be <base_matrix><_extra_matrix>_<scope>
    base_matrix should exist in py_config.
    _extra_matrix should be a function in utilities.pytest_matrix_utils

    Args:
       pytest_config (_pytest.config.Config): pytest config
       matrix_name (str): matrix name

    Example:
       storage_class_matrix_snapshot_matrix__class__

       storage_class_matrix is in py_config
       snapshot_matrix is a function in utilities.pytest_matrix_utils
       all function in utilities.pytest_matrix_utils accept only matrix args.

    Returns:
         list: list of matrix params
    """
    missing_matrix_error = f"{matrix_name} is missing in config file"
    base_matrix_name = get_base_matrix_name(matrix_name=matrix_name)

    _matrix_params = py_config.get(matrix_name)
    # If matrix is not in py_config, check if it is a function in utilities.pytest_matrix_utils
    if not _matrix_params:
        _matrix_func_name = matrix_name.split(base_matrix_name)[-1].replace("_", "", 1)
        _base_matrix_params = py_config.get(base_matrix_name)
        if not _base_matrix_params:
            raise ValueError(missing_matrix_error)

        # When running --collect-only or --setup-plan we cannot execute functions from pytest_matrix_utils
        if skip_if_pytest_flags_exists(pytest_config=pytest_config):
            _matrix_params = _base_matrix_params

        else:
            module_name = "utilities.pytest_matrix_utils"
            if module_name not in sys.modules:
                sys.modules[module_name] = importlib.import_module(name=module_name)

            pytest_matrix_utils = sys.modules[module_name]
            matrix_func = getattr(pytest_matrix_utils, _matrix_func_name)
            return matrix_func(matrix=_base_matrix_params)

    if not _matrix_params:
        raise ValueError(missing_matrix_error)

    return _matrix_params if isinstance(_matrix_params, list) else [_matrix_params]


def config_default_storage_class(session):
    # Default storage class selection order:
    # 1. --default-storage-class from command line
    # 2. --storage-class-matrix:
    #     * if default sc from global_config storage_class_matrix appears in the commandline, use this sc
    #     * if default sc from global_config storage_class_matrix does not appear in the commandline, use the first
    #       sc in --storage-class-matrix options
    # 3. global_config default_storage_class
    global_config_default_sc = py_config["default_storage_class"]
    cmd_default_storage_class = session.config.getoption(name="default_storage_class")
    cmdline_storage_class_matrix = session.config.getoption(name="storage_class_matrix")
    updated_default_sc = None
    if cmd_default_storage_class:
        updated_default_sc = cmd_default_storage_class
    elif cmdline_storage_class_matrix:
        cmdline_storage_class_matrix = cmdline_storage_class_matrix.split(",")
        updated_default_sc = (
            global_config_default_sc
            if global_config_default_sc in cmdline_storage_class_matrix
            else cmdline_storage_class_matrix[0]
        )

    # Update only if the requested default sc is not the same as set in global_config
    if updated_default_sc and updated_default_sc != global_config_default_sc:
        py_config["default_storage_class"] = updated_default_sc
        default_storage_class_configuration = [
            sc_dict
            for sc in py_config["storage_class_matrix"]
            for sc_name, sc_dict in sc.items()
            if sc_name == updated_default_sc
        ][0]

        py_config["default_volume_mode"] = default_storage_class_configuration["volume_mode"]
        py_config["default_access_mode"] = default_storage_class_configuration["access_mode"]


def separator(symbol_, val=None):
    terminal_width = shutil.get_terminal_size(fallback=(120, 40))[0]
    if not val:
        return f"{symbol_ * terminal_width}"

    sepa = int((terminal_width - len(val) - 2) // 2)
    return f"{symbol_ * sepa} {val} {symbol_ * sepa}"


def reorder_early_fixtures(metafunc):
    """
    Put fixtures with `pytest.mark.early` first during execution

    This allows patch of configurations before the application is initialized

    Due to the way pytest collects fixtures, marks must be placed below
    @pytest.fixture — which is to say, they must be applied BEFORE @pytest.fixture.
    """
    for fixturedef in metafunc._arg2fixturedefs.values():
        fixturedef = fixturedef[0]
        for mark in getattr(fixturedef.func, "pytestmark", []):
            if mark.name == "early":
                mark_order = mark.kwargs.get("order", 0)
                order = metafunc.fixturenames
                order.insert(mark_order, order.pop(order.index(fixturedef.argname)))
                break


def stop_if_run_in_progress():
    run_in_progress = run_in_progress_config_map()
    if run_in_progress.exists:
        exit_pytest_execution(
            message=f"openshift-virtualization-tests run already in progress: \n{run_in_progress.instance.data}"
            f"\nAfter verifying no one else is performing tests against the cluster, run:"
            f"\n'oc delete configmap -n {run_in_progress.namespace} {run_in_progress.name}'",
            return_code=100,
        )


def deploy_run_in_progress_namespace():
    run_in_progress_namespace = Namespace(name=CNV_TEST_RUN_IN_PROGRESS_NS)
    if not run_in_progress_namespace.exists:
        run_in_progress_namespace.deploy(wait=True)
        run_in_progress_namespace.wait_for_status(status=Namespace.Status.ACTIVE, timeout=TIMEOUT_2MIN)
        ResourceEditor({run_in_progress_namespace: {"metadata": {"labels": POD_SECURITY_NAMESPACE_LABELS}}}).update()
    return run_in_progress_namespace


def deploy_run_in_progress_config_map(session):
    run_in_progress_config_map(session=session).deploy()


def run_in_progress_config_map(session=None):
    return ConfigMap(
        name=CNV_TEST_RUN_IN_PROGRESS,
        namespace=CNV_TEST_RUN_IN_PROGRESS_NS,
        data=get_current_running_data(session=session) if session else None,
    )


def get_current_running_data(session):
    return {
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "running_from_dir": os.getcwd(),
        "pytest_cmd": ", ".join(session.config.invocation_params.args),
        "session-id": session.config.option.session_id,
        "run-in-container": os.environ.get(CNV_TESTS_CONTAINER, "No"),
    }


def skip_if_pytest_flags_exists(pytest_config):
    """
    In some cases we want to skip some operation when pytest got executed with some flags
    Used in dynamic fixtures and in check if run already in progress.

    Args:
        pytest_config (_pytest.config.Config): Pytest config object

    Returns:
        bool: True if skip is needed, otherwise False
    """
    return pytest_config.getoption("--collect-only") or pytest_config.getoption("--setup-plan")


def get_artifactory_server_url(cluster_host_url):
    LOGGER.info(f"Getting artifactory server information using cluster host url: {cluster_host_url}")
    artifactory_server = os.environ.get("ARTIFACTORY_SERVER")
    if artifactory_server:
        LOGGER.warning(f"Using user requested ARTIFACTORY_SERVER environment variable: {artifactory_server}")
        return artifactory_server
    else:
        servers = get_cnv_tests_secret_by_name(secret_name="artifactory_servers")
        matching_server = [servers[domain_key] for domain_key in servers if domain_key in cluster_host_url]
        if matching_server:
            artifactory_server = matching_server[0]
        else:
            artifactory_server = get_cnv_tests_secret_by_name(secret_name="default_artifactory_server")["server"]
    LOGGER.info(f"Using artifactory server: {artifactory_server}")
    return artifactory_server


def get_cnv_version_explorer_url(pytest_config):
    if pytest_config.getoption("install") or pytest_config.getoption("upgrade") == "eus":
        LOGGER.info("Checking for cnv version explorer url:")
        version_explorer_url = os.environ.get("CNV_VERSION_EXPLORER_URL")
        if not version_explorer_url:
            raise MissingEnvironmentVariableError("Please set CNV_VERSION_EXPLORER_URL environment variable")
        return version_explorer_url


def generate_os_matrix_dict(os_name: str, supported_operating_systems: list[str]) -> list[dict[str, Any]]:
    """
    Generate a dictionary of OS matrix for the given OS name and supported operating systems.

    Args:
        os_name (str): The name of the OS.
        supported_operating_systems (list[str]): A list of supported operating systems.

    Returns:
        list[dict[str, Any]]: A list of dictionaries representing the OS matrix.

            Example:
                [
                    {
                    "rhel-7-8": {
                        OS_VERSION_STR: "7.8",
                        IMAGE_NAME_STR: "rhel-78.qcow2",
                        IMAGE_PATH_STR: "cnv-tests/rhel-images/rhel-78.qcow2",
                        DV_SIZE_STR:  "20Gi",
                        TEMPLATE_LABELS_STR: {
                            OS_STR: "rhel7.8",
                            WORKLOAD_STR: "server",
                            FLAVOR_STR: "tiny",
                            },
                        }
                    }
                ]

    Raises:
        ValueError: If the OS name is not supported or if the supported operating systems list is empty.
    """
    rhel_os_mapping = {
        WORKLOAD_STR: Template.Workload.SERVER,
        FLAVOR_STR: Template.Flavor.TINY,
        "rhel-7-8": {
            IMAGE_NAME_STR: "RHEL7_8_IMG",
            OS_VERSION_STR: "7.8",
            OS_STR: "rhel7.8",
        },
        "rhel-7-9": {
            IMAGE_NAME_STR: "RHEL7_9_IMG",
            OS_VERSION_STR: "7.9",
            OS_STR: "rhel7.9",
        },
        "rhel-8-8": {
            IMAGE_NAME_STR: "RHEL8_8_IMG",
            OS_VERSION_STR: "8.8",
            OS_STR: "rhel8.8",
        },
        "rhel-8-10": {
            IMAGE_NAME_STR: "RHEL8_10_IMG",
            OS_VERSION_STR: "8.10",
            OS_STR: "rhel8.10",
        },
        "rhel-9-4": {
            IMAGE_NAME_STR: "RHEL9_4_IMG",
            OS_VERSION_STR: "9.4",
            OS_STR: "rhel9.4",
        },
        "rhel-9-6": {
            IMAGE_NAME_STR: "RHEL9_6_IMG",
            OS_VERSION_STR: "9.6",
            LATEST_RELEASE_STR: True,
            OS_STR: "rhel9.6",
        },
    }

    windows_os_mapping = {
        WORKLOAD_STR: Template.Workload.SERVER,
        FLAVOR_STR: Template.Flavor.MEDIUM,
        "win-10": {
            IMAGE_NAME_STR: "WIN10_IMG",
            OS_VERSION_STR: "10",
            OS_STR: WIN_10,
            WORKLOAD_STR: Template.Workload.DESKTOP,
            FLAVOR_STR: Template.Flavor.MEDIUM,
        },
        "win-2016": {
            IMAGE_NAME_STR: "WIN2k16_IMG",
            OS_VERSION_STR: "2016",
            OS_STR: "win2k16",
        },
        "win-2019": {
            IMAGE_NAME_STR: "WIN2k19_IMG",
            OS_VERSION_STR: "2019",
            LATEST_RELEASE_STR: True,
            OS_STR: "win2k19",
        },
        "win-11": {
            IMAGE_NAME_STR: "WIN11_IMG",
            OS_VERSION_STR: "11",
            OS_STR: WIN_11,
            WORKLOAD_STR: Template.Workload.DESKTOP,
            FLAVOR_STR: Template.Flavor.MEDIUM,
        },
        "win-2022": {
            IMAGE_NAME_STR: "WIN2022_IMG",
            OS_VERSION_STR: "2022",
            OS_STR: WIN_2K22,
        },
        "win-2025": {
            IMAGE_NAME_STR: "WIN2k25_IMG",
            OS_VERSION_STR: "2025",
            OS_STR: WIN_2K25,
        },
    }

    fedora_os_mapping = {
        WORKLOAD_STR: Template.Workload.SERVER,
        FLAVOR_STR: Template.Flavor.SMALL,
        "fedora-41": {
            IMAGE_NAME_STR: "FEDORA41_IMG",
            LATEST_RELEASE_STR: True,
            OS_STR: "fedora41",
        },
    }

    centos_os_mapping = {
        WORKLOAD_STR: Template.Workload.SERVER,
        FLAVOR_STR: Template.Flavor.TINY,
        "centos-stream-9": {
            IMAGE_NAME_STR: "CENTOS_STREAM_9_IMG",
            LATEST_RELEASE_STR: True,
            OS_STR: "centos-stream9",
        },
    }

    os_formatted_list = []
    unsupported_versions = []

    if os_name == "rhel":
        base_dict = rhel_os_mapping
    elif os_name == "windows":
        base_dict = windows_os_mapping
    elif os_name == "fedora":
        base_dict = fedora_os_mapping
    elif os_name == "centos":
        base_dict = centos_os_mapping
    else:
        raise ValueError(f"Unsupported OS: {os_name}. Supported: rhel, win, fedora")

    os_base_class = getattr(Images, os_name.title())

    for version in supported_operating_systems:
        if base_version_dict := base_dict.get(version):
            image_name = getattr(os_base_class, base_dict[version][IMAGE_NAME_STR])

            os_formatted_list.append({
                version: {
                    OS_VERSION_STR: base_version_dict.get(OS_VERSION_STR),
                    IMAGE_NAME_STR: image_name,
                    IMAGE_PATH_STR: os.path.join(getattr(os_base_class, "DIR"), image_name),
                    DV_SIZE_STR: getattr(os_base_class, "DEFAULT_DV_SIZE"),
                    TEMPLATE_LABELS_STR: {
                        OS_STR: base_version_dict[OS_STR],
                        WORKLOAD_STR: base_version_dict.get(WORKLOAD_STR, base_dict[WORKLOAD_STR]),
                        FLAVOR_STR: base_version_dict.get(FLAVOR_STR, base_dict[FLAVOR_STR]),
                    },
                    LATEST_RELEASE_STR: base_version_dict.get(LATEST_RELEASE_STR, False),
                }
            })

        else:
            unsupported_versions.append(version)

    if unsupported_versions:
        raise ValueError(f"Unsupported OS versions: {unsupported_versions} for {os_name}")

    return os_formatted_list
