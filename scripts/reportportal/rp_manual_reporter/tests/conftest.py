"""Conftest for rp_manual_reporter tests."""

import os
from collections.abc import Generator

import pytest

# Set early (module-level) so the env var is available during collection,
# before session-scoped fixtures run.
os.environ.setdefault("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", "amd64")


@pytest.fixture(autouse=True, scope="session")
def _mock_cluster_architecture() -> Generator[None]:
    """Set architecture env var to avoid cluster connection in tests."""
    old_value = os.environ.get("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH")
    os.environ["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = "amd64"
    yield
    if old_value is None:
        os.environ.pop("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", None)
    else:
        os.environ["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = old_value
