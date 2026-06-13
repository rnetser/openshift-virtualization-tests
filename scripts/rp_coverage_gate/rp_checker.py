# Co-authored-by: Claude <noreply@anthropic.com>
"""ReportPortal results checker.

Queries ReportPortal for test execution results across launches
matching a bundle prefix and builds a result map.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _process_launch_items(launch: dict[str, Any], items: list[dict[str, Any]]) -> list[ItemResult]:
    """Process items from a single launch into ItemResult objects.

    Args:
        launch: Launch dict with attributes, name, etc.
        items: List of test item dicts from RP API.

    Returns:
        List of ItemResult objects for this launch.
    """
    launch_attributes = launch.get("attributes", [])
    bundle_value = _extract_attribute(attributes=launch_attributes, key="BUNDLE") or ""
    manual_value = _extract_attribute(attributes=launch_attributes, key="MANUAL")
    source = "manual" if manual_value and manual_value.lower() == "true" else "automated"
    launch_name = launch.get("name", "")

    results: list[ItemResult] = []
    for item in items:
        item_name = item.get("name", "")
        item_status = item.get("status", "")
        item_end_time = item.get("endTime", "")

        issue = item.get("issue")
        defect_type = None
        defect_comment = None
        if issue:
            raw_issue_type = issue.get("issueType", "")
            defect_type = _classify_defect(issue_type=raw_issue_type)
            defect_comment = issue.get("comment")

        results.append(
            ItemResult(
                name=item_name,
                status=item_status,
                last_executed=str(item_end_time),
                bundle=bundle_value,
                launch_name=launch_name,
                source=source,
                defect_type=defect_type,
                defect_comment=defect_comment,
            )
        )
    return results


def check_coverage(
    rp_client: RPClient,
    bundle_prefix: str,
    max_launches: int = 50,
    max_workers: int = 10,
    progress_callback: Any | None = None,
) -> dict[str, ItemResult]:
    """Query ReportPortal for test results matching the bundle prefix.

    Fetches launches matching the bundle, keeps the most recent
    ``max_launches`` to avoid redundant work, then fetches test items
    in parallel using a thread pool.

    When a test appears in multiple launches, the most recent result
    wins (launches are processed in chronological order).

    Args:
        rp_client: Authenticated RPClient instance.
        bundle_prefix: Bundle version prefix to match.
        max_launches: Maximum number of recent launches to process.
        max_workers: Thread pool size for parallel item fetching.
        progress_callback: Optional callable(current, total) for progress.

    Returns:
        Dict mapping RP test name to its most recent ItemResult.
    """
    launches = rp_client.get_launches(bundle_prefix=bundle_prefix)
    launches.sort(key=lambda launch: launch.get("startTime", 0))

    total_launches = len(launches)
    if total_launches > max_launches:
        LOGGER.info(f"Using {max_launches} most recent launches out of {total_launches}")
        launches = launches[-max_launches:]

    result_map: dict[str, ItemResult] = {}

    def _fetch_launch_items(launch: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        items = rp_client.get_test_items(launch_id=launch["id"])
        return launch, items

    completed = 0
    launch_count = len(launches)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_launch_items, launch): launch for launch in launches}
        for future in as_completed(futures):
            launch, items = future.result()
            for item_result in _process_launch_items(launch=launch, items=items):
                result_map[item_result.name] = item_result
            completed += 1
            if progress_callback:
                progress_callback(current=completed, total=launch_count)

    LOGGER.info(f"Found results for {len(result_map)} unique tests across {launch_count} launches")
    return result_map
