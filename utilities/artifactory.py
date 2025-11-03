import logging
import os
import ssl

import requests
from ocp_resources.config_map import ConfigMap
from ocp_resources.secret import Secret
from pytest_testconfig import config as py_config
from timeout_sampler import TimeoutExpiredError, TimeoutSampler

from utilities.constants import TIMEOUT_1MIN, TIMEOUT_5SEC
from utilities.infra import base64_encode_str

LOGGER = logging.getLogger(__name__)

ARTIFACTORY_SECRET_NAME = "cnv-tests-artifactory-secret"
BASE_ARTIFACTORY_LOCATION = "artifactory/cnv-qe-server-local"


def get_test_artifact_server_url(schema="https"):
    """
    Verify https server server connectivity (regardless of schema).
    Return the requested "registry" or "https" server url.

    Args:
        schema (str): registry or https.

    Returns:
        str: Server URL.

    Raises:
        URLError: If server is not accessible.
    """
    artifactory_connection_url = py_config["servers"]["https_server"]
    LOGGER.info(f"Testing connectivity to {artifactory_connection_url} {schema.upper()} server")
    sample = None
    try:
        for sample in TimeoutSampler(
            wait_timeout=TIMEOUT_1MIN,
            sleep=TIMEOUT_5SEC,
            func=lambda: requests.get(artifactory_connection_url, headers=get_artifactory_header(), verify=False),
        ):
            if sample.status_code == requests.codes.ok:
                return py_config["servers"][f"{schema}_server"]
    except TimeoutExpiredError:
        LOGGER.error(
            f"Unable to connect to test image server: {artifactory_connection_url} "
            f"{schema.upper()}, with error code: {sample.status_code}, error: {sample.text}"
        )
        raise


def get_http_image_url(image_directory, image_name):
    return f"{get_test_artifact_server_url()}{image_directory}/{image_name}"


def get_artifactory_header():
    return {"Authorization": f"Bearer {os.environ['ARTIFACTORY_TOKEN']}"}


def get_artifactory_secret(
    namespace,
):
    artifactory_secret = Secret(
        name=ARTIFACTORY_SECRET_NAME,
        namespace=namespace,
        accesskeyid=base64_encode_str(os.environ["ARTIFACTORY_USER"]),
        secretkey=base64_encode_str(os.environ["ARTIFACTORY_TOKEN"]),
    )
    if not artifactory_secret.exists:
        artifactory_secret.deploy()
    return artifactory_secret


def get_artifactory_config_map(
    namespace,
):
    artifactory_cm = ConfigMap(
        name="artifactory-configmap",
        namespace=namespace,
        data={"tlsregistry.crt": ssl.get_server_certificate(addr=(py_config["server_url"], 443))},
    )
    if not artifactory_cm.exists:
        artifactory_cm.deploy()
    return artifactory_cm


def cleanup_artifactory_secret_and_config_map(artifactory_secret=None, artifactory_config_map=None):
    if artifactory_secret:
        artifactory_secret.clean_up()
    if artifactory_config_map:
        artifactory_config_map.clean_up()
