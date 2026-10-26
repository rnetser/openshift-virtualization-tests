"""Conftest for manual_tests_reporter tests."""

import os
from collections.abc import Generator

import pytest

from scripts.manual_tests_reporter.tests.arch_env_bootstrap import ORIGINAL_ARCH


@pytest.fixture(autouse=True, scope="session")
def restored_arch_env() -> Generator[None]:
    """Original architecture env var, restored after the test session."""
    yield
    if ORIGINAL_ARCH is None:
        os.environ.pop("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", None)
    else:
        os.environ["OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"] = ORIGINAL_ARCH
