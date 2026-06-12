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
        polarion_id: Polarion test case ID if present.
        source: "manual" if MANUAL=true in launch, else "automated".
    """

    name: str
    status: str
    last_executed: str
    bundle: str
    launch_name: str
    polarion_id: str | None = None
    source: str = "automated"


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
            item_attributes = item.get("attributes", [])

            polarion_id = _extract_attribute(attributes=item_attributes, key="polarion-testcase-id")

            result_map[item_name] = ItemResult(
                name=item_name,
                status=item_status,
                last_executed=str(item_end_time),
                bundle=bundle_value,
                launch_name=launch_name,
                polarion_id=polarion_id,
                source=source,
            )

    LOGGER.info(f"Found results for {len(result_map)} unique tests across {len(launches)} launches")
    return result_map
