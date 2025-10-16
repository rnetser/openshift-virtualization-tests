import json
import logging
import os
from functools import lru_cache
from typing import Any

import requests

from utilities.exceptions import MissingEnvironmentVariableError

LOGGER = logging.getLogger(__name__)

# Bitwarden Secrets Manager API: https://bitwarden.com/help/secrets-manager-api/
BITWARDEN_API_BASE_URL = "https://api.bitwarden.com"


def _get_bitwarden_credentials() -> tuple[str, str]:
    """Get and validate Bitwarden credentials from environment.

    Returns:
        tuple[str, str]: (access_token, organization_id)

    Raises:
        MissingEnvironmentVariableError: If credentials not configured
    """
    access_token = os.getenv("ACCESS_TOKEN")
    organization_id = os.getenv("ORGANIZATION_ID")

    if not access_token or not organization_id:
        raise MissingEnvironmentVariableError(
            "Bitwarden client needs ORGANIZATION_ID and ACCESS_TOKEN environment variables set up"
        )

    return access_token, organization_id


def _get_bitwarden_headers() -> dict[str, str]:
    """Get headers for Bitwarden API requests with authentication.

    Returns:
        dict[str, str]: Headers dictionary with authorization and content type

    Raises:
        MissingEnvironmentVariableError: If ACCESS_TOKEN environment variable is not set
    """
    access_token, _ = _get_bitwarden_credentials()
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _make_bitwarden_request(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Make Bitwarden API request with comprehensive error handling.

    Args:
        url: Full API endpoint URL
        headers: Request headers including authentication

    Returns:
        dict[str, Any]: Parsed JSON response

    Raises:
        MissingEnvironmentVariableError: If API request fails
    """
    try:
        response = requests.get(url, headers=headers, timeout=30, verify=True)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        LOGGER.error(f"Bitwarden API request failed: {e.response.status_code}")
        raise MissingEnvironmentVariableError(
            f"Failed to access Bitwarden API (HTTP {e.response.status_code})"
        ) from None
    except requests.RequestException as e:
        LOGGER.error(f"Bitwarden API network error: {type(e).__name__}")
        raise MissingEnvironmentVariableError("Failed to connect to Bitwarden API") from None


def get_bitwarden_secrets_client() -> dict[str, str]:
    """Validates Bitwarden environment variables and returns headers for API requests.
    Maintains compatibility with original SDK-based implementation.

    This function validates that ACCESS_TOKEN and ORGANIZATION_ID environment variables are set.
    Instead of returning a client object, it returns the headers needed for API requests.

    Returns:
        dict[str, str]: Headers dictionary for Bitwarden API requests

    Raises:
        MissingEnvironmentVariableError: If ACCESS_TOKEN or ORGANIZATION_ID environment variables are not set
    """
    _get_bitwarden_credentials()
    return _get_bitwarden_headers()


@lru_cache
def get_all_cnv_tests_secrets() -> dict[str, str]:
    """Gets a list of all cnv-secrets saved in Bitwarden Secret Manager (associated with a specific organization id).
    ORGANIZATION_ID is expected to be set via environment variable.

    Returns:
        dict[str, str]: Dictionary mapping secret name to secret UUID associated with the organization

    Raises:
        MissingEnvironmentVariableError: If ORGANIZATION_ID or ACCESS_TOKEN environment variables are not set
            or if API request fails
    """
    headers = _get_bitwarden_headers()
    _, organization_id = _get_bitwarden_credentials()

    url = f"{BITWARDEN_API_BASE_URL}/organizations/{organization_id}/secrets"

    data = _make_bitwarden_request(url=url, headers=headers)
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
        ValueError: If secret is not found or contains invalid JSON
        MissingEnvironmentVariableError: If required environment variables are not set or API request fails
    """
    headers = _get_bitwarden_headers()

    # Get all secrets (cached)
    secrets = get_all_cnv_tests_secrets()

    # Use O(1) dictionary lookup instead of O(n) loop
    secret_id = secrets.get(secret_name)
    if not secret_id:
        LOGGER.info(f"Cache info stats for getting specific secret: {get_cnv_tests_secret_by_name.cache_info()}")
        raise ValueError(f"Secret '{secret_name}' not found in Bitwarden")

    url = f"{BITWARDEN_API_BASE_URL}/secrets/{secret_id}"
    secret_data = _make_bitwarden_request(url=url, headers=headers)

    secret_value = secret_data.get("value", "")

    # Add explicit JSON error handling
    try:
        secret_dict = json.loads(secret_value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in secret '{secret_name}': {e}") from e

    LOGGER.info(f"Cache info stats for getting specific secret: {get_cnv_tests_secret_by_name.cache_info()}")
    return secret_dict
