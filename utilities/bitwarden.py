import json
import logging
import os
from functools import lru_cache
from typing import Any

import requests

from utilities.exceptions import MissingEnvironmentVariableError

LOGGER = logging.getLogger(__name__)


def _make_bitwarden_request(endpoint: str) -> dict[str, Any]:
    """Make Bitwarden API request with authentication.

    Args:
        endpoint: API endpoint path (e.g., '/organizations/{id}/secrets')

    Returns:
        dict[str, Any]: Parsed JSON response

    Raises:
        MissingEnvironmentVariableError: If ACCESS_TOKEN not set
    """
    access_token = os.getenv("ACCESS_TOKEN")

    if not access_token:
        raise MissingEnvironmentVariableError("Bitwarden client needs ACCESS_TOKEN environment variables set up")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    response = requests.get(url=f"https://api.bitwarden.com{endpoint}", headers=headers, timeout=30, verify=True)
    response.raise_for_status()
    return response.json()


@lru_cache
def get_all_cnv_tests_secrets() -> dict[str, str]:
    """Gets a list of all cnv-secrets saved in Bitwarden Secret Manager (associated with a specific organization id).

    ORGANIZATION_ID is expected to be set via environment variable.

    Returns:
        dict[str, str]: Dictionary mapping secret name to secret UUID associated with the organization

    Raises:
        MissingEnvironmentVariableError: If ORGANIZATION_ID or ACCESS_TOKEN environment variables are not set
    """
    organization_id = os.getenv("ORGANIZATION_ID")

    if not organization_id:
        raise MissingEnvironmentVariableError("Bitwarden client needs ORGANIZATION_ID environment variables set up")

    data = _make_bitwarden_request(endpoint=f"/organizations/{organization_id}/secrets")
    secrets_list = data.get("data", [])

    LOGGER.info(f"Cache info stats for pulling secrets: {get_all_cnv_tests_secrets.cache_info()}")

    return {secret["key"]: secret["id"] for secret in secrets_list}


@lru_cache
def get_cnv_tests_secret_by_name(secret_name: str) -> dict[str, Any]:
    """Pull a specific secret from Bitwarden Secret Manager by name.

    Args:
        secret_name: Bitwarden Secret Manager secret name

    Returns:
        dict[str, Any]: Value of the saved secret (parsed from JSON)

    Raises:
        ValueError: If a secret is not found or contains invalid JSON
    """
    secrets = get_all_cnv_tests_secrets()

    secret_id = secrets.get(secret_name)
    if not secret_id:
        LOGGER.info(f"Cache info stats for getting specific secret: {get_cnv_tests_secret_by_name.cache_info()}")
        raise ValueError(f"Secret '{secret_name}' not found in Bitwarden")

    secret_data = _make_bitwarden_request(endpoint=f"/secrets/{secret_id}")
    secret_value = secret_data.get("value", "")

    try:
        secret_dict = json.loads(secret_value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in secret '{secret_name}': {e}") from e

    LOGGER.info(f"Cache info stats for getting specific secret: {get_cnv_tests_secret_by_name.cache_info()}")
    return secret_dict
