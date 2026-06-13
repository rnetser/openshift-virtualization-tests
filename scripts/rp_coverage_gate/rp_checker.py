# Co-authored-by: Claude <noreply@anthropic.com>
"""ReportPortal results checker.

Queries ReportPortal for test execution results across launches
matching a bundle prefix and builds a result map.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from scripts.rp_utils.rp_client import RPClient

LOGGER = logging.getLogger(__name__)


@dataclass
class ItemResult:
    """Execution result for a single test item from ReportPortal.

    Attributes:
        name: Dotted RP test name.
        status: Last status (PASSED, FAILED, SKIPPED).
        last_executed: ISO timestamp of last execution.
        bundle: Bundle version from the launch attributes.
        launch_name: Name of the launch.
        source: "manual" if MANUAL=true in launch, else "automated".
        defect_type: Classified defect type for failed/skipped items.
        defect_comment: Defect comment from RP issue field.
    """

    name: str
    status: str
    last_executed: str
    bundle: str
    launch_name: str
    source: str = "automated"
    defect_type: str | None = None
    defect_comment: str | None = None


_DEFECT_TYPE_PREFIXES: dict[str, str] = {
    "pb": "Product Bug",
    "ab": "Automation Bug",
    "si": "System Issue",
    "ti": "To Investigate",
    "nd": "No Defect",
}


def _classify_defect(issue_type: str) -> str:
    """Classify a ReportPortal issue type locator into a human-readable label.

    Matches by prefix since custom defect types may have different numeric
    suffixes (e.g., ``pb001``, ``pb_custom_123``).

    Args:
        issue_type: RP issue type locator (e.g., ``pb001``, ``ab002``).

    Returns:
        Human-readable defect classification.
    """
    if issue_type == "NOT_ISSUE":
        return "Not Issue"

    lower_type = issue_type.lower()
    for prefix, label in _DEFECT_TYPE_PREFIXES.items():
        if lower_type.startswith(prefix):
            return label

    return "Unknown"


def _extract_attribute(attributes: list[dict[str, Any]], key: str) -> str | None:
    """Extract a specific attribute value from a list of RP attribute dicts.

    Args:
        attributes: List of attribute dicts with 'key' and 'value' fields.
        key: Attribute key to search for (case-sensitive).

    Returns:
        The attribute value if found, None otherwise.
    """
    for attr in attributes:
        if attr.get("key") == key:
            return attr.get("value")
    return None


def check_coverage(rp_client: RPClient, bundle_prefix: str) -> dict[str, ItemResult]:
    """Query ReportPortal for test results matching the bundle prefix.

    Iterates all launches with matching BUNDLE attribute, fetches their
    test items, and builds a result map. When a test appears in multiple
    launches, the most recent result wins.

    Args:
        rp_client: Authenticated RPClient instance.
        bundle_prefix: Bundle version prefix to match.

    Returns:
        Dict mapping RP test name to its most recent ItemResult.
    """
    launches = rp_client.get_launches(bundle_prefix=bundle_prefix)
    launches.sort(key=lambda launch: launch.get("startTime", 0))

    result_map: dict[str, ItemResult] = {}

    for launch in launches:
        launch_attributes = launch.get("attributes", [])
        bundle_value = _extract_attribute(attributes=launch_attributes, key="BUNDLE") or ""
        manual_value = _extract_attribute(attributes=launch_attributes, key="MANUAL")
        source = "manual" if manual_value and manual_value.lower() == "true" else "automated"
        launch_name = launch.get("name", "")

        items = rp_client.get_test_items(launch_id=launch["id"])

        for item in items:
            item_name = item.get("name", "")
            item_status = item.get("status", "")
            item_end_time = item.get("endTime", "")
            item.get("attributes", [])

            issue = item.get("issue")
            defect_type = None
            defect_comment = None
            if issue:
                raw_issue_type = issue.get("issueType", "")
                defect_type = _classify_defect(issue_type=raw_issue_type)
                defect_comment = issue.get("comment")

            result_map[item_name] = ItemResult(
                name=item_name,
                status=item_status,
                last_executed=str(item_end_time),
                bundle=bundle_value,
                launch_name=launch_name,
                source=source,
                defect_type=defect_type,
                defect_comment=defect_comment,
            )

    LOGGER.info(f"Found results for {len(result_map)} unique tests across {len(launches)} launches")
    return result_map
