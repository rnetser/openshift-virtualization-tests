"""
Bitwarden utilities for accessing secrets via bws CLI.

Assisted-by: Claude cli
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from typing import TYPE_CHECKING

from pyhelper_utils.shell import run_command

if TYPE_CHECKING:
    from _pytest.main import Session

LOGGER = logging.getLogger(__name__)

BWS_ACCESS_TOKEN_ENV_VAR = "BWS_ACCESS_TOKEN"


def _run_bws_command(args: list[str]) -> str:
    """Run bws CLI command and return output.

    Args:
        args: Command arguments to pass to bws.

    Returns:
        Command stdout.

    Raises:
        ValueError: If BWS_ACCESS_TOKEN environment variable is not set.
        RuntimeError: If bws command fails.
    """
    access_token = os.environ.get(BWS_ACCESS_TOKEN_ENV_VAR)
    if not access_token:
        raise ValueError(f"{BWS_ACCESS_TOKEN_ENV_VAR} environment variable is not set")

    cmd = ["bws", *args, "--access-token", access_token]
    result = run_command(command=cmd, check=True)
    return result.out


@cache
def get_all_cnv_tests_secrets() -> dict[str, str]:
    """Get all CNV tests secrets from Bitwarden.

    Returns:
        Dictionary mapping secret names to their values.
    """
    try:
        output = _run_bws_command(args=["secret", "list"])
        secrets = json.loads(output)
        return {secret["key"]: secret["value"] for secret in secrets}
    except Exception as exc:
        LOGGER.error(f"Failed to get secrets from Bitwarden: {exc}")
        raise


def get_cnv_tests_secret_by_name(name: str, session: Session | None = None) -> dict[str, str]:
    """Get a specific secret from Bitwarden by name.

    Args:
        name: Name of the secret to retrieve.
        session: Optional pytest session for checking --disabled-bitwarden flag.

    Returns:
        Dictionary with the secret value.

    Raises:
        ValueError: If the secret is not found.
    """
    if session and session.config.getoption("--disabled-bitwarden", default=False):
        return {}

    secrets = get_all_cnv_tests_secrets()
    if name not in secrets:
        raise ValueError(f"Secret '{name}' not found in Bitwarden")

    return json.loads(secrets[name])
