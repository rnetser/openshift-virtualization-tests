# Co-authored-by: Claude <noreply@anthropic.com>
"""Conftest for polarion_sync tests.

This file prevents pytest from discovering the project's top-level
conftest.py which requires an OpenShift cluster connection.
"""
