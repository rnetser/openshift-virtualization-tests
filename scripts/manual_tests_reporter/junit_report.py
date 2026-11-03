# Co-authored-by: Claude <noreply@anthropic.com>
"""JUnit XML report builder and Datadog uploader for manual test results.

Builds a JUnit XML report from collected manual test verdicts and
uploads it to Datadog Test Visibility via ``datadog-ci junit upload``,
so manual runs appear in Test Optimization alongside CI runs.

Note: durations are not tracked for manual verdicts, so every suite and
testcase intentionally reports ``time="0"``.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast, get_args
from xml.etree import ElementTree

from pyhelper_utils.shell import run_command
from simple_logger.logger import get_logger

LOGGER = get_logger(name=__name__)

# Characters illegal in XML 1.0 (control chars other than tab/newline/CR)
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Datadog tag keys/values allow alphanumerics and _ . : / @ + -; anything
# else (spaces, quotes, backslashes...) makes datadog-ci reject or mangle
# the tag. The Jenkins upload pipeline sanitizes its tag values the same
# way (replacing illegal characters with underscores).
_ILLEGAL_TAG_CHARS = re.compile(r"[^A-Za-z0-9_.:/@+\-]")

# Verdict status type for a manual test result — single source of truth
Status = Literal["PASSED", "FAILED", "SKIPPED"]

# Valid verdict statuses for a manual test result, derived from Status
VALID_STATUSES = frozenset(get_args(Status))


class DatadogUploadError(Exception):
    """Raised when the ``datadog-ci junit upload`` command fails."""


@dataclass
class ManualTestResult:
    """Verdict for a single manual test.

    Attributes:
        test: Pytest-style node ID of the test.
        status: Verdict — ``PASSED``, ``FAILED`` or ``SKIPPED``.
        comment: Optional tester comment.
        issue_type_label: Defect classification label for failures.
    """

    test: str
    status: Status
    comment: str = ""
    issue_type_label: str | None = None


def coerce_status(value: str) -> Status:
    """Narrow a status string to the ``Status`` literal type.

    Args:
        value: Status string, e.g. ``"PASSED"``.

    Returns:
        The value narrowed to ``Status``.

    Raises:
        ValueError: If the value is not one of ``VALID_STATUSES``.
    """
    if value not in VALID_STATUSES:
        raise ValueError(f"Invalid status {value!r}. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
    return cast(Status, value)


def _sanitize_xml_text(text: str) -> str:
    """Remove characters that are illegal in XML 1.0.

    Args:
        text: User-supplied text destined for an XML attribute or body.

    Returns:
        The text with illegal control characters removed.
    """
    return _ILLEGAL_XML_CHARS.sub(repl="", string=text)


def _sanitize_tag_text(text: str) -> str:
    """Sanitize a value destined for a Datadog tag or a tag-shaped property.

    Both upload channels emit the same Datadog-legal text: the ``--tags``
    flags (``attributes_to_tags``) and the per-testcase ``<property>``
    elements, which mirror the run's tag values (Datadog only ingests
    ``dd_tags[...]``-named properties as tags; plain-named ones still ship
    in the XML, so they are kept consistent with the tag channel). XML-
    illegal control characters are removed first, then characters Datadog
    forbids in tags become ``_``.

    Args:
        text: User-supplied property name or value.

    Returns:
        The sanitized, tag-legal text.
    """
    return _ILLEGAL_TAG_CHARS.sub(repl="_", string=_ILLEGAL_XML_CHARS.sub(repl="", string=text))


def _node_id_to_classname_and_name(node_id: str) -> tuple[str, str]:
    """Split a pytest node ID into JUnit classname and name.

    Args:
        node_id: Pytest-style node ID, e.g.
            ``tests/foo/test_bar.py::TestClass::test_method``.

    Returns:
        A tuple of (classname, name), e.g.
        ``("tests/foo/test_bar.py::TestClass", "test_method")``.
        For standalone tests the classname is the file path.
    """
    classname, separator, name = node_id.rpartition("::")
    if not separator:
        return node_id, node_id
    return classname, name


def attributes_to_tags(attributes: list[dict[str, str]]) -> list[str]:
    """Convert run attributes to Datadog tag strings.

    Keys are lowercased; keys and values run through the same sanitization
    pipeline as the XML property path (``_sanitize_tag_text``) so both
    channels emit identical, Datadog-legal tag values.

    Args:
        attributes: List of ``{"key": ..., "value": ...}`` run attributes.

    Returns:
        List of ``key:value`` tag strings with sanitized keys and values.
    """
    return [
        f"{_sanitize_tag_text(text=attr['key'].lower())}:{_sanitize_tag_text(text=attr['value'])}"
        for attr in attributes
    ]


def build_junit_xml(
    results: list[ManualTestResult],
    suite_name: str,
    attributes: list[dict[str, str]],
    polarion_lookup: dict[str, str] | None = None,
    description: str = "",
) -> str:
    """Build a JUnit XML report from manual test results.

    Args:
        results: List of test verdicts.
        suite_name: Name for the testsuite element.
        attributes: Run attributes emitted as testcase properties.
        polarion_lookup: Optional node_id → Polarion ID mapping; matching
            tests get a ``polarion-testcase-id`` property.
        description: Suite-level description.

    Returns:
        The JUnit XML document as a string.
    """
    polarion_lookup = polarion_lookup or {}
    passed_count = sum(1 for result in results if result.status == "PASSED")
    failed_count = sum(1 for result in results if result.status == "FAILED")
    skipped_count = sum(1 for result in results if result.status == "SKIPPED")

    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(
        root,
        "testsuite",
        attrib={
            "name": _sanitize_xml_text(text=suite_name),
            "tests": str(len(results)),
            "failures": str(failed_count),
            "errors": "0",
            "skipped": str(skipped_count),
            "time": "0",
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
    )
    if description:
        suite.set("description", _sanitize_xml_text(text=description))

    for result in results:
        classname, name = _node_id_to_classname_and_name(node_id=result.test)
        testcase = ElementTree.SubElement(
            suite,
            "testcase",
            attrib={
                "classname": _sanitize_xml_text(text=classname),
                "name": _sanitize_xml_text(text=name),
                "time": "0",
            },
        )

        properties = ElementTree.SubElement(testcase, "properties")
        for attr in attributes:
            ElementTree.SubElement(
                properties,
                "property",
                attrib={
                    "name": _sanitize_tag_text(text=attr["key"].lower()),
                    "value": _sanitize_tag_text(text=attr["value"]),
                },
            )
        polarion_id = polarion_lookup.get(result.test)
        if polarion_id:
            ElementTree.SubElement(
                properties,
                "property",
                # Datadog only ingests <property> names of the form dd_tags[key];
                # any other name is dropped during ingestion.
                attrib={"name": "dd_tags[polarion-testcase-id]", "value": _sanitize_xml_text(text=polarion_id)},
            )

        if result.status == "FAILED":
            defect_label = result.issue_type_label or "Unclassified"
            failure = ElementTree.SubElement(
                testcase,
                "failure",
                attrib={
                    "type": _sanitize_xml_text(text=defect_label),
                    "message": _sanitize_xml_text(text=result.comment),
                },
            )
            failure.text = _sanitize_xml_text(text=f"{defect_label}: {result.comment}")
        elif result.status == "SKIPPED":
            ElementTree.SubElement(
                testcase,
                "skipped",
                attrib={"message": _sanitize_xml_text(text=result.comment)},
            )

    LOGGER.info(
        f"Built JUnit report '{suite_name}': {passed_count} passed, {failed_count} failed, {skipped_count} skipped"
    )
    ElementTree.indent(tree=root, space="  ")
    return ElementTree.tostring(element=root, encoding="unicode")


def write_junit_report(xml_path: Path, xml_content: str) -> None:
    """Write a JUnit XML document to disk.

    Args:
        xml_path: Destination file path.
        xml_content: JUnit XML document string.
    """
    xml_path.write_text(data=xml_content, encoding="utf-8")
    LOGGER.info(f"Wrote JUnit report to {xml_path}")


def upload_junit_report(
    xml_path: Path,
    service: str,
    tags: list[str],
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> None:
    """Upload a JUnit XML report to Datadog Test Visibility.

    Runs ``datadog-ci junit upload`` which requires the
    ``DATADOG_API_KEY`` (or ``DD_API_KEY``) environment variable to be
    set; ``DATADOG_SITE`` (or ``DD_SITE``) selects a non-US site.

    Args:
        xml_path: Path to the JUnit XML report file (absolute — the child
            process may run from a different working directory).
        service: Datadog service name for the uploaded results.
        tags: Run-level tags as ``key:value`` strings.
        env: Extra environment variables for the datadog-ci child process
            (e.g. ``DD_ENV`` and the ``DD_GIT_*`` git-metadata vars);
            merged over the current environment.
        cwd: Working directory for the child process. Pass the scanned
            tests directory so datadog-ci's own git detection resolves the
            same checkout the explicit ``DD_GIT_*`` vars describe — instead
            of attaching an unrelated repository's git facets when the
            tests directory is not a git checkout.

    Raises:
        DatadogUploadError: If the upload command fails.
    """
    command = ["datadog-ci", "junit", "upload", "--service", service]
    # datadog-ci parses --tags as an array flag: one flag per tag. A single
    # comma-joined value would be uploaded as one mangled tag.
    for tag in tags:
        command.extend(["--tags", tag])
    command.append(str(xml_path))

    child_env = {**os.environ, **(env or {})}

    LOGGER.info(f"Uploading {xml_path} to Datadog (service: {service})")
    try:
        # 300s: large reports on a slow link can take minutes; datadog-ci has
        # no built-in timeout, so without one a hung upload blocks forever.
        success, stdout, stderr = run_command(
            command=command,
            check=False,
            verify_stderr=False,
            capture_output=True,
            timeout=300,
            env=child_env,
            cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # OSError covers a missing datadog-ci binary (FileNotFoundError) and
        # other spawn failures; SubprocessError covers subprocess-level errors.
        raise DatadogUploadError(f"Failed to run datadog-ci: {exc}") from exc
    if not success:
        raise DatadogUploadError(
            f"datadog-ci junit upload failed:\n{stdout}\n{stderr}\n"
            f"Verify DATADOG_API_KEY is set and '{xml_path}' is a valid JUnit XML file."
        )
    LOGGER.info(f"Uploaded {xml_path} to Datadog Test Visibility (service: {service})")
