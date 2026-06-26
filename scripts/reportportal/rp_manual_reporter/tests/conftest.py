# Co-authored-by: Claude <noreply@anthropic.com>
"""Conftest for rp_manual_reporter tests.

Prevents pytest from discovering the project's top-level conftest.py
which requires an OpenShift cluster connection.
"""

import os

os.environ.setdefault("OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", "amd64")
