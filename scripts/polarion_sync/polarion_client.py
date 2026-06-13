# Co-authored-by: Claude <noreply@anthropic.com>
"""Create Polarion test cases for unlinked tests.

Uses ``pylero`` (the same library already used by ``python-utility-scripts``)
to create test work-items in the CNV Polarion project.

Credentials are read from the standard pylero config file
(``~/.pylero``) which Jenkins already provisions.
"""

from __future__ import annotations

import logging
import os
import ssl
from dataclasses import dataclass

from scripts.polarion_sync.jira_linker import resolve_requirement
from scripts.polarion_sync.scanner import UnlinkedTest

LOGGER = logging.getLogger(__name__)

_ssl_configured = False


def _configure_ssl() -> None:
    """Disable SSL verification for Polarion if POLARION_DISABLE_SSL_VERIFY is set."""
    global _ssl_configured
    if _ssl_configured:
        return
    _ssl_configured = True
    if os.environ.get("POLARION_DISABLE_SSL_VERIFY"):
        # Mypy complains about ssl internal type signatures; use vars() to bypass
        vars(ssl)["_create_default_https_context"] = ssl._create_unverified_context
        LOGGER.warning("SSL verification disabled via POLARION_DISABLE_SSL_VERIFY — affects all HTTPS in this process")


# Cache for sibling requirement lookups
_sibling_requirement_cache: dict[str, str | None] = {}


def clear_sibling_cache() -> None:
    """Clear the sibling requirement cache. Used by tests to ensure isolation."""
    _sibling_requirement_cache.clear()


@dataclass
class PolarionResult:
    """Mapping of a test to its newly-created Polarion work-item ID."""

    test: UnlinkedTest
    polarion_id: str
    requirement_linked: bool = False


def _resolve_sibling_requirement(sibling_ids: list[str], project_id: str) -> str | None:
    """Look up the requirement linked to an existing sibling test case in Polarion.

    Queries Polarion for each sibling's linked work items and returns the first
    requirement found via a ``verifies`` link.

    Args:
        sibling_ids: Polarion work-item IDs of existing tests in the same file.
        project_id: Polarion project ID.

    Returns:
        Polarion requirement work item ID, or None if none found.
    """
    from pylero.work_item import TestCase as PyleroTestCase  # noqa: PLC0415

    for sibling_id in sibling_ids:
        if sibling_id in _sibling_requirement_cache:
            cached = _sibling_requirement_cache[sibling_id]
            if cached:
                LOGGER.info(f"  Sibling {sibling_id} → requirement {cached} (cached)")
                return cached
            continue

        try:
            sibling_tc = PyleroTestCase(project_id=project_id, work_item_id=sibling_id)
            if sibling_tc.linked_work_items:
                for link in sibling_tc.linked_work_items:
                    if link.role == "verifies":
                        requirement_id = link.work_item_id
                        _sibling_requirement_cache[sibling_id] = requirement_id
                        LOGGER.info(f"  Sibling {sibling_id} → requirement {requirement_id}")
                        return requirement_id
        except Exception as exc:
            LOGGER.warning(f"  Could not fetch sibling test case {sibling_id} from Polarion: {exc}")

        _sibling_requirement_cache[sibling_id] = None

    return None


def _humanize_test_name(test_name: str) -> str:
    """Turn ``test_vm_starts_with_bridge`` into ``VM starts with bridge``."""
    return test_name.removeprefix("test_").replace("_", " ").capitalize()


def _build_description(test: UnlinkedTest) -> str:
    """Build a Polarion description from the test docstring and parametrize info."""
    parts: list[str] = []
    if test.docstring:
        parts.append(f"<pre>{test.docstring}</pre>")
    else:
        parts.append(f"Auto-generated from {test.node_id}")
    if test.parametrize_info:
        parts.append("<br/><b>Parameters:</b><ul>")
        for info in test.parametrize_info:
            parts.append(f"<li>{info}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def create_test_cases(
    tests: list[UnlinkedTest],
    project_id: str = "CNV",
    dry_run: bool = False,
) -> list[PolarionResult]:
    """Create a Polarion ``TestCase`` for each test and return the IDs.

    Args:
        tests: tests that need Polarion IDs.
        project_id: Polarion project identifier.
        dry_run: when True, log what *would* be created without touching Polarion.

    Returns:
        List of ``PolarionResult`` with the assigned IDs.
    """
    _configure_ssl()
    if not tests:
        LOGGER.info("No tests to create in Polarion")
        return []

    results: list[PolarionResult] = []

    if dry_run:
        for idx, test in enumerate(tests, start=1):
            fake_id = f"{project_id}-DRY{idx:05d}"
            automation_status = "notautomated" if test.is_std_only else "automated"
            LOGGER.info(f"[dry-run] Would create: {test.node_id} → {fake_id} ({automation_status})")
            for jira_key in test.jira_ids:
                LOGGER.info(f"[dry-run] Would resolve {jira_key} to Polarion requirement")
            results.append(PolarionResult(test=test, polarion_id=fake_id, requirement_linked=False))
        return results

    from pylero.work_item import TestCase  # noqa: PLC0415

    for test in tests:
        title = _humanize_test_name(test_name=test.test_name)
        description = _build_description(test=test)
        automation_status = "notautomated" if test.is_std_only else "automated"

        LOGGER.info(f"Creating Polarion test case: {title} ({test.node_id}) [{automation_status}]")
        try:
            test_case = TestCase.create(
                project_id=project_id,
                title=title,
                description=description,
                caseautomation=automation_status,
                caselevel="component",
                caseimportance="medium",
                automation_id=test.node_id,
            )
        except Exception as exc:
            LOGGER.error(f"  Failed to create test case for {test.node_id}: {exc}")
            continue
        polarion_id = test_case.work_item_id
        LOGGER.info(f"  Created: {polarion_id}")
        result = PolarionResult(test=test, polarion_id=polarion_id)
        results.append(result)

        for jira_key in test.jira_ids:
            requirement_id = resolve_requirement(jira_key=jira_key, project_id=project_id)
            if requirement_id:
                try:
                    test_case.add_linked_item(linked_id=requirement_id, role="verifies")
                except Exception as exc:
                    LOGGER.warning(f"  Failed to link {polarion_id} → {requirement_id}: {exc}")
                    break
                LOGGER.info(f"  Linked {polarion_id} → verifies {requirement_id} (via {jira_key})")
                result.requirement_linked = True
                break

        if not result.requirement_linked and test.sibling_polarion_ids:
            requirement_id = _resolve_sibling_requirement(
                sibling_ids=test.sibling_polarion_ids,
                project_id=project_id,
            )
            if requirement_id:
                try:
                    test_case.add_linked_item(linked_id=requirement_id, role="verifies")
                except Exception as exc:
                    LOGGER.warning(f"  Failed to link {polarion_id} → {requirement_id} (sibling): {exc}")
                    continue
                LOGGER.info(f"  Linked {polarion_id} → verifies {requirement_id} (via sibling fallback)")
                result.requirement_linked = True

    # All-or-nothing: if any test case failed to create, abort.
    # NOTE: Already-created Polarion work items become orphans on abort.
    # These are harmless (unlinked test cases) and can be cleaned up
    # manually or by a periodic maintenance job.
    if len(results) < len(tests):
        failed_count = len(tests) - len(results)
        LOGGER.error(f"{failed_count} test case(s) failed to create in Polarion — aborting (all-or-nothing)")
        return []

    return results
