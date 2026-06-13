# Co-authored-by: Claude <noreply@anthropic.com>
"""Resolve Jira references to Polarion requirement IDs.

Walks the Jira hierarchy from a ticket to its Epic, then searches
Polarion for a requirement whose ``jiraurl`` matches that Epic.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jira import JIRA

LOGGER = logging.getLogger(__name__)

JIRA_BROWSE_URL = "https://redhat.atlassian.net/browse"

# Cache to avoid repeated API calls for the same Jira ID
_epic_cache: dict[str, str | None] = {}
_requirement_cache: dict[str, str | None] = {}
_jira_client_cache: dict[str, JIRA] = {}


def clear_caches() -> None:
    """Clear all module-level caches. Used by tests to ensure isolation."""
    _epic_cache.clear()
    _requirement_cache.clear()
    _jira_client_cache.clear()


def _get_jira_client() -> JIRA:
    """Return a cached authenticated Jira client.

    Returns:
        An authenticated JIRA instance (created once, reused).

    Raises:
        RuntimeError: when required environment variables are missing.
    """
    if "client" not in _jira_client_cache:
        from jira import JIRA  # noqa: PLC0415 — pylero/jira crash on import without ~/.pylero config

        required_vars = ("PYTEST_JIRA_URL", "PYTEST_JIRA_USERNAME", "PYTEST_JIRA_TOKEN")
        missing = [var for var in required_vars if var not in os.environ]
        if missing:
            raise RuntimeError(f"Missing required Jira environment variables: {', '.join(missing)}")

        _jira_client_cache["client"] = JIRA(
            server=os.environ["PYTEST_JIRA_URL"],
            basic_auth=(os.environ["PYTEST_JIRA_USERNAME"], os.environ["PYTEST_JIRA_TOKEN"]),
        )
    return _jira_client_cache["client"]


def _find_epic_key(jira_client: JIRA, jira_key: str) -> str | None:
    """Walk the Jira hierarchy to find the Epic for a given ticket.

    Checks: parent chain (up to 3 levels), then issuelinks for Epic type.

    Args:
        jira_client: authenticated JIRA instance.
        jira_key: Jira issue key (e.g. "CNV-87822").

    Returns:
        The Epic's key, or None if no Epic is found.
    """
    if jira_key in _epic_cache:
        return _epic_cache[jira_key]

    try:
        issue = jira_client.issue(id=jira_key)
    except Exception as exc:
        LOGGER.warning(f"Could not fetch Jira issue {jira_key}: {exc}")
        _epic_cache[jira_key] = None
        return None

    # If it's already an Epic, return it
    if issue.fields.issuetype.name == "Epic":
        _epic_cache[jira_key] = jira_key
        return jira_key

    # Walk parent chain (up to 3 levels)
    current = issue
    for _level in range(3):
        parent = getattr(current.fields, "parent", None)
        if parent is None:
            break
        parent_issue = jira_client.issue(id=parent.key)
        if parent_issue.fields.issuetype.name == "Epic":
            _epic_cache[jira_key] = parent.key
            LOGGER.info(f"  {jira_key} → Epic {parent.key} (via parent chain)")
            return parent.key
        current = parent_issue

    # Check issuelinks for Epic references
    for link in issue.fields.issuelinks:
        for direction in ("outwardIssue", "inwardIssue"):
            target = getattr(link, direction, None)
            if target and target.fields.issuetype.name == "Epic":
                _epic_cache[jira_key] = target.key
                LOGGER.info(f"  {jira_key} → Epic {target.key} (via issuelink)")
                return target.key

    LOGGER.warning(f"  No Epic found for {jira_key}")
    _epic_cache[jira_key] = None
    return None


def _find_polarion_requirement(epic_key: str, project_id: str) -> str | None:
    """Search Polarion for a requirement linked to a Jira Epic.

    Args:
        epic_key: Jira Epic key (e.g. "CNV-61530").
        project_id: Polarion project ID.

    Returns:
        Polarion requirement work item ID, or None if not found.
    """
    if epic_key in _requirement_cache:
        return _requirement_cache[epic_key]

    from pylero.work_item import Requirement  # noqa: PLC0415

    jira_url = f"{JIRA_BROWSE_URL}/{epic_key}"
    try:
        results = Requirement.query(
            query=f'jiraurl:"{jira_url}"',
            project_id=project_id,
            fields=["work_item_id"],
        )
    except Exception as exc:
        LOGGER.warning(f"  Polarion query failed for {epic_key}: {exc}")
        _requirement_cache[epic_key] = None
        return None

    if not results:
        LOGGER.warning(f"  No Polarion requirement found for Epic {epic_key}")
        _requirement_cache[epic_key] = None
        return None

    requirement_id = results[0].work_item_id
    LOGGER.info(f"  Epic {epic_key} → Polarion requirement {requirement_id}")
    _requirement_cache[epic_key] = requirement_id
    return requirement_id


def resolve_requirement(jira_key: str, project_id: str = "CNV") -> str | None:
    """Resolve a Jira ticket to a Polarion requirement ID.

    Walks the Jira hierarchy to find the Epic, then searches Polarion
    for a requirement whose ``jiraurl`` matches.

    Args:
        jira_key: Jira issue key (e.g. "CNV-87822").
        project_id: Polarion project ID.

    Returns:
        Polarion requirement work item ID, or None if not found.
    """
    jira_client = _get_jira_client()
    epic_key = _find_epic_key(jira_client=jira_client, jira_key=jira_key)
    if not epic_key:
        return None
    return _find_polarion_requirement(epic_key=epic_key, project_id=project_id)


def extract_jira_ids(docstring: str) -> list[str]:
    """Extract Jira issue keys from Jira URLs in a docstring.

    Only matches keys inside ``redhat.atlassian.net/browse/`` URLs to avoid
    confusing Polarion work-item IDs (which share the ``CNV-`` prefix) with
    Jira tickets.

    Args:
        docstring: the test or class docstring.

    Returns:
        List of unique Jira keys found.
    """
    matches = re.findall(r"redhat\.atlassian\.net/browse/([A-Z]+-\d+)", docstring)
    seen: set[str] = set()
    result: list[str] = []
    for key in matches:
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result
