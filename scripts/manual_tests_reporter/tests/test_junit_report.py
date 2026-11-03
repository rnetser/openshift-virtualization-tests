# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.manual_tests_reporter.junit_report module.

See scripts/manual_tests_reporter/README.md for the tool this module belongs to.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

import pytest

from scripts.manual_tests_reporter.junit_report import (
    VALID_STATUSES,
    DatadogUploadError,
    ManualTestResult,
    _node_id_to_classname_and_name,
    attributes_to_tags,
    build_junit_xml,
    coerce_status,
    upload_junit_report,
    write_junit_report,
)


class TestCoerceStatus:
    def test_valid_status_returned(self) -> None:
        """Verify a valid status is returned narrowed to the Status type."""
        result = coerce_status(value="PASSED")
        assert result == "PASSED", f"Expected 'PASSED', got {result!r}"

    def test_invalid_status_raises(self) -> None:
        """Verify an unrecognized status raises ValueError."""
        with pytest.raises(expected_exception=ValueError, match="Invalid status"):
            coerce_status(value="maybe")

    def test_valid_statuses_derived_from_status_literal(self) -> None:
        """Verify VALID_STATUSES stays in sync with the Status literal (single source of truth)."""
        assert VALID_STATUSES == {"PASSED", "FAILED", "SKIPPED"}, (
            f"Expected the Status literal and VALID_STATUSES to define the same statuses, got {VALID_STATUSES!r}"
        )


class TestNodeIdToClassnameAndName:
    def test_class_method_node_id(self) -> None:
        """Verify class method node ID splits into classname and name."""
        result = _node_id_to_classname_and_name(node_id="tests/foo/test_bar.py::TestClass::test_method")
        assert result == ("tests/foo/test_bar.py::TestClass", "test_method"), (
            f"Expected ('tests/foo/test_bar.py::TestClass', 'test_method'), got {result!r}"
        )

    def test_standalone_node_id(self) -> None:
        """Verify standalone test node ID splits into file and function."""
        result = _node_id_to_classname_and_name(node_id="tests/foo/test_bar.py::test_func")
        assert result == ("tests/foo/test_bar.py", "test_func"), (
            f"Expected ('tests/foo/test_bar.py', 'test_func'), got {result!r}"
        )


class TestAttributesToTags:
    def test_attributes_to_tags(self) -> None:
        """Verify attributes convert to lowercase key:value tags."""
        result = attributes_to_tags(
            attributes=[{"key": "TEAM", "value": "NETWORK"}, {"key": "BUNDLE", "value": "v4.22.0"}]
        )
        assert result == ["team:NETWORK", "bundle:v4.22.0"], (
            f"Expected ['team:NETWORK', 'bundle:v4.22.0'], got {result!r}"
        )

    def test_attributes_to_tags_sanitizes_illegal_characters(self) -> None:
        """Verify illegal tag characters are replaced with underscores.

        Datadog tag values cannot contain spaces or quotes; the README's own
        marker example ("gating and not tier3") must survive as a valid tag.
        """
        result = attributes_to_tags(
            attributes=[
                {"key": "marker", "value": "gating and not tier3"},
                {"key": "owner", "value": "tester@redhat.com"},
                {"key": "bad key!", "value": "it's a 'value'"},
            ]
        )
        assert result == [
            "marker:gating_and_not_tier3",
            "owner:tester@redhat.com",
            "bad_key_:it_s_a__value_",
        ], f"Expected sanitized tags, got {result!r}"

    def test_property_path_matches_tags_sanitization(self) -> None:
        """Verify XML property values carry the same tag sanitization as --tags.

        datadog-ci converts <property> elements into tags on test spans, so
        a multi-word marker must reach Datadog identically through both
        paths — sanitized to underscores, not mangled or rejected.
        """
        attributes = [{"key": "marker", "value": "gating and not tier3"}]
        xml_content = build_junit_xml(
            suite_name="pytest",
            results=[ManualTestResult(test="tests/net/test_a.py::TestA::test_one", status="PASSED")],
            attributes=attributes,
        )
        tags = attributes_to_tags(attributes=attributes)
        expected_tag = tags[0].split(":", 1)[1]
        assert f'value="{expected_tag}"' in xml_content, (
            f"Expected the property value to match the sanitized tag value {expected_tag!r}, got:\n{xml_content}"
        )


class TestBuildJunitXml:
    def test_pass_fail_skip_structure(self) -> None:
        """Verify XML structure for passed, failed, and skipped results."""
        results = [
            ManualTestResult(test="tests/net/test_a.py::TestA::test_pass", status="PASSED"),
            ManualTestResult(
                test="tests/net/test_a.py::TestA::test_fail",
                status="FAILED",
                comment="boom",
                issue_type_label="Product Bug",
            ),
            ManualTestResult(test="tests/net/test_a.py::TestA::test_skip", status="SKIPPED"),
        ]
        xml_content = build_junit_xml(
            results=results,
            suite_name="Manual - NETWORK",
            attributes=[{"key": "TEAM", "value": "NETWORK"}],
        )
        root = fromstring(text=xml_content)
        suite = root.find("testsuite")
        assert suite is not None, "Expected: XML structure for passed, failed, and skipped results"
        assert suite.get("name") == "Manual - NETWORK", f"Expected 'Manual - NETWORK', got {suite.get('name')!r}"
        assert suite.get("tests") == "3", f"Expected '3', got {suite.get('tests')!r}"
        assert suite.get("failures") == "1", f"Expected '1', got {suite.get('failures')!r}"
        assert suite.get("skipped") == "1", f"Expected '1', got {suite.get('skipped')!r}"

        testcases = suite.findall("testcase")
        assert len(testcases) == 3, f"Expected 3, got {len(testcases)!r}"

        passed, failed, skipped = testcases
        assert passed.get("name") == "test_pass", f"Expected 'test_pass', got {passed.get('name')!r}"
        assert passed.find("failure") is None, "Expected: XML structure for passed, failed, and skipped results"

        failure = failed.find("failure")
        assert failure is not None, "Expected: XML structure for passed, failed, and skipped results"
        assert failure.get("type") == "Product Bug", f"Expected 'Product Bug', got {failure.get('type')!r}"
        assert failure.get("message") == "boom", f"Expected 'boom', got {failure.get('message')!r}"

        assert skipped.find("skipped") is not None, "Expected: XML structure for passed, failed, and skipped results"

    def test_properties_included(self) -> None:
        """Verify run attributes and Polarion ID become testcase properties."""
        results = [ManualTestResult(test="tests/net/test_a.py::TestA::test_one", status="PASSED")]
        xml_content = build_junit_xml(
            results=results,
            suite_name="Manual - NETWORK",
            attributes=[{"key": "TEAM", "value": "NETWORK"}],
            polarion_lookup={"tests/net/test_a.py::TestA::test_one": "MOCK-1234"},
        )
        root = fromstring(text=xml_content)
        suite = root.find("testsuite")
        assert suite is not None, "Expected: run attributes and Polarion ID become testcase properties"
        testcase = suite.find("testcase")
        assert testcase is not None, "Expected: run attributes and Polarion ID become testcase properties"
        properties = testcase.find("properties")
        assert properties is not None, "Expected: run attributes and Polarion ID become testcase properties"
        props = {prop.get("name"): prop.get("value") for prop in properties.findall("property")}
        assert props["team"] == "NETWORK", f"Expected 'NETWORK', got {props['team']!r}"
        assert props["dd_tags[polarion-testcase-id]"] == "MOCK-1234", (
            f"Expected 'MOCK-1234', got {props['dd_tags[polarion-testcase-id]']!r}"
        )

    def test_classname_split(self) -> None:
        """Verify classname and name are split from the node ID."""
        results = [ManualTestResult(test="tests/net/test_a.py::TestA::test_one", status="PASSED")]
        xml_content = build_junit_xml(results=results, suite_name="s", attributes=[])
        root = fromstring(text=xml_content)
        suite = root.find("testsuite")
        assert suite is not None, "Expected: classname and name are split from the node ID"
        testcase = suite.find("testcase")
        assert testcase is not None, "Expected: classname and name are split from the node ID"
        assert testcase.get("classname") == "tests/net/test_a.py::TestA", (
            f"Expected 'tests/net/test_a.py::TestA', got {testcase.get('classname')!r}"
        )
        assert testcase.get("name") == "test_one", f"Expected 'test_one', got {testcase.get('name')!r}"


class TestWriteJunitReport:
    def test_write_junit_report(self, tmp_path: Path) -> None:
        """Verify XML content is written to disk."""
        xml_path = tmp_path / "report.xml"
        write_junit_report(xml_path=xml_path, xml_content="<testsuites/>")
        assert xml_path.read_text(encoding="utf-8") == "<testsuites/>", (
            f"Expected '<testsuites/>', got {xml_path.read_text(encoding='utf-8')!r}"
        )


class TestUploadJunitReport:
    def test_upload_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify successful upload runs datadog-ci with service, tags, env, and a timeout.

        The explicit env (DD_ENV, DD_GIT_*) must win over ambient variables —
        a tester with DD_ENV=staging exported still uploads as production.
        """
        xml_path = tmp_path / "report.xml"
        xml_path.write_text(data="<testsuites/>", encoding="utf-8")
        monkeypatch.setenv(name="DD_ENV", value="staging")
        with patch(
            target="scripts.manual_tests_reporter.junit_report.run_command",
            return_value=(True, "uploaded", ""),
        ) as mock_run:
            upload_junit_report(
                xml_path=xml_path,
                service="svc",
                tags=["team:NETWORK"],
                env={"DD_ENV": "production", "DD_GIT_BRANCH": "main"},
                cwd=tmp_path,
            )
        assert mock_run.call_count == 1, "Expected exactly one datadog-ci invocation"
        passed_env = mock_run.call_args.kwargs["env"]
        assert passed_env["DD_ENV"] == "production", "Expected: explicit env wins over the ambient DD_ENV"
        assert passed_env["DD_GIT_BRANCH"] == "main", "Expected: git metadata env vars reach datadog-ci"
        assert passed_env.get("DD_SITE") == os.environ.get("DD_SITE"), "Expected: ambient vars pass through"
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["command"] == [
            "datadog-ci",
            "junit",
            "upload",
            "--service",
            "svc",
            "--tags",
            "team:NETWORK",
            str(xml_path),
        ], f"Expected the datadog-ci command, got {call_kwargs['command']!r}"
        assert call_kwargs["check"] is False, "Expected: datadog-ci failures surface via return code handling"
        assert call_kwargs["verify_stderr"] is False, "Expected: datadog-ci stderr is not treated as failure"
        assert call_kwargs["capture_output"] is True, "Expected: upload output captured for the error report"
        assert call_kwargs["timeout"] == 300, "Expected: the 300s hang guard on the upload"
        assert call_kwargs["cwd"] == tmp_path, f"Expected cwd forwarded, got {call_kwargs['cwd']!r}"

    def test_upload_multiple_tags_one_flag_each(self, tmp_path: Path) -> None:
        """Verify each tag gets its own --tags flag (datadog-ci array option)."""
        xml_path = tmp_path / "report.xml"
        xml_path.write_text(data="<testsuites/>", encoding="utf-8")
        with patch(
            target="scripts.manual_tests_reporter.junit_report.run_command",
            return_value=(True, "uploaded", ""),
        ) as mock_run:
            upload_junit_report(xml_path=xml_path, service="svc", tags=["team:NETWORK", "bundle:v4.22.0"])
        command = mock_run.call_args.kwargs["command"]
        assert command == [
            "datadog-ci",
            "junit",
            "upload",
            "--service",
            "svc",
            "--tags",
            "team:NETWORK",
            "--tags",
            "bundle:v4.22.0",
            str(xml_path),
        ], f"Expected one --tags flag per tag, got {command!r}"

    def test_upload_missing_binary_raises(self, tmp_path: Path) -> None:
        """Verify a missing datadog-ci binary raises DatadogUploadError, not FileNotFoundError."""
        xml_path = tmp_path / "report.xml"
        xml_path.write_text(data="<testsuites/>", encoding="utf-8")
        with patch(
            target="scripts.manual_tests_reporter.junit_report.run_command",
            side_effect=FileNotFoundError("datadog-ci"),
        ):
            with pytest.raises(expected_exception=DatadogUploadError, match="Failed to run datadog-ci"):
                upload_junit_report(xml_path=xml_path, service="svc", tags=[])

    def test_upload_failure_raises(self, tmp_path: Path) -> None:
        """Verify failed upload raises DatadogUploadError."""
        xml_path = tmp_path / "report.xml"
        xml_path.write_text(data="<testsuites/>", encoding="utf-8")
        with patch(
            target="scripts.manual_tests_reporter.junit_report.run_command",
            return_value=(False, "", "api key invalid"),
        ):
            with pytest.raises(expected_exception=DatadogUploadError, match="api key invalid"):
                upload_junit_report(xml_path=xml_path, service="svc", tags=[])

    def test_upload_without_tags_omits_flag(self, tmp_path: Path) -> None:
        """Verify empty tag list omits the --tags flag."""
        xml_path = tmp_path / "report.xml"
        xml_path.write_text(data="<testsuites/>", encoding="utf-8")
        with patch(
            target="scripts.manual_tests_reporter.junit_report.run_command",
            return_value=(True, "uploaded", ""),
        ) as mock_run:
            upload_junit_report(xml_path=xml_path, service="svc", tags=[])
        assert "--tags" not in mock_run.call_args.kwargs["command"], "Expected: empty tag list omits the --tags flag"


class TestSanitizeXmlText:
    def test_control_characters_removed(self) -> None:
        """Verify illegal XML control characters are stripped from comments."""
        results = [
            ManualTestResult(test="tests/net/test_a.py::TestA::test_fail", status="FAILED", comment="boom\x01\x02"),
        ]
        xml_content = build_junit_xml(results=results, suite_name="s", attributes=[])
        root = fromstring(text=xml_content)
        suite = root.find("testsuite")
        assert suite is not None, "Expected: illegal XML control characters are stripped from comments"
        testcase = suite.find("testcase")
        assert testcase is not None, "Expected: illegal XML control characters are stripped from comments"
        failure = testcase.find("failure")
        assert failure is not None, "Expected: illegal XML control characters are stripped from comments"
        assert failure.get("message") == "boom", f"Expected 'boom', got {failure.get('message')!r}"


class TestSuiteNameSanitized:
    def test_suite_name_control_chars_removed(self) -> None:
        """Verify control characters in suite_name are stripped."""
        results = [ManualTestResult(test="tests/net/test_a.py::TestA::test_one", status="PASSED")]
        xml_content = build_junit_xml(
            results=results,
            suite_name="Manual - NET\x01WORK",
            attributes=[{"key": "TE\x02AM", "value": "NETWORK"}],
        )
        root = fromstring(text=xml_content)
        suite = root.find("testsuite")
        assert suite is not None, "Expected: suite name sanitized"
        assert suite.get("name") == "Manual - NETWORK", "Expected: suite name sanitized"
        testcase = suite.find("testcase")
        assert testcase is not None, "Expected: property key sanitized"
        properties = testcase.find("properties")
        assert properties is not None, "Expected: property key sanitized"
        prop = properties.find("property")
        assert prop is not None, "Expected: property key sanitized"
        assert prop.get("name") == "team", "Expected: property key sanitized"
