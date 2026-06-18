# Co-authored-by: Claude <noreply@anthropic.com>
"""Conftest for rp_coverage_gate tests.

Prevents pytest from discovering the project's top-level conftest.py
which requires an OpenShift cluster connection.
"""
