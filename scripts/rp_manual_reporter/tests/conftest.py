"""Conftest for rp_manual_reporter tests.

Prevents pytest from discovering the project's top-level conftest.py
which requires an OpenShift cluster connection.
"""
