import json
import logging
import os
import time
from functools import lru_cache
from typing import Any

import requests

from utilities.exceptions import MissingEnvironmentVariableError

LOGGER = logging.getLogger(__name__)

# Cache for OAuth token to avoid repeated authentication requests
_oauth_token_cache: dict[str, Any] = {}


def _get_oauth_token() -> str:
    """Get OAuth2 access token using client credentials flow.

    Returns:
        str: Bearer access token

    Raises:
        MissingEnvironmentVariableError: If client credentials not set
        requests.HTTPError: If token request fails
    """
    client_id = os.getenv("BITWARDEN_CLIENT_ID")
    client_secret = os.getenv("BITWARDEN_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise MissingEnvironmentVariableError(
            "Bitwarden client needs BITWARDEN_CLIENT_ID and BITWARDEN_CLIENT_SECRET environment variables set up"
        )

    # Check cache for valid token
    current_time = time.time()
    if _oauth_token_cache.get("access_token") and _oauth_token_cache.get("expires_at", 0) > current_time:
        return _oauth_token_cache["access_token"]

    response = requests.post(
        url="https://identity.bitwarden.com/connect/token",
        data={
            "grant_type": "client_credentials",
            "scope": "api.organization",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
        verify=True,
    )
    response.raise_for_status()

    token_response = response.json()
    access_token = token_response["access_token"]
    expires_in = token_response.get("expires_in", 3600)

    # Cache token with absolute expiration time (subtract 100 s for a safety margin)
    _oauth_token_cache["access_token"] = access_token
    _oauth_token_cache["expires_at"] = current_time + expires_in - 100

    LOGGER.info("Successfully obtained OAuth2 access token")
    return access_token


def _make_bitwarden_request(endpoint: str) -> dict[str, Any]:
    """Make Bitwarden API request with authentication.

    Args:
        endpoint: API endpoint path (e.g., '/organizations/{id}/secrets')

    Returns:
        dict[str, Any]: Parsed JSON response

    """
    response = requests.get(
        url=f"https://api.bitwarden.com{endpoint}",
        headers={
            "Authorization": f"Bearer {_get_oauth_token()}",
            "Content-Type": "application/json",
        },
        timeout=30,
        verify=True,
    )
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
