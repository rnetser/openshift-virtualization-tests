"""Conftest for rp_utils tests."""

import os
from collections.abc import Generator

import pytest

# Snapshot original state before mutation
_ORIGINAL_ARCH = os.environ.get("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH")

# Set early (module-level) so the env var is available during collection,
# before session-scoped fixtures run.
os.environ.setdefault("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", "amd64")


@pytest.fixture(autouse=True, scope="session")
def _mock_cluster_architecture() -> Generator[None]:
    """Restore original architecture env var after tests complete."""
    yield
    if _ORIGINAL_ARCH is None:
        os.environ.pop("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", None)
    else:
        os.environ["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = _ORIGINAL_ARCH
