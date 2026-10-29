# Co-authored-by: Claude <noreply@anthropic.com>
"""Tests for scripts.manual_tests_reporter.manual_tests_reporter module.

See scripts/manual_tests_reporter/README.md for the tool this module belongs to.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click import ClickException
from click.testing import CliRunner
from pyhelper_utils.shell import run_command

from scripts.manual_tests_reporter import manual_tests_reporter as reporter_module
from scripts.manual_tests_reporter.junit_report import DatadogUploadError, ManualTestResult
from scripts.manual_tests_reporter.manual_tests_reporter import (
    _build_run_attributes,
    _load_batch_file,
    _merge_batch_metadata,
    _save_results_for_retry,
    main,
)
from scripts.manual_tests_reporter.tests.utils import (
    MINIMAL_MANUAL_TEST_SOURCE,
    capture_uploaded_xml,
    cleanup_kept_junit_report,
    required_attr_args,
    write_manual_tests_dir,
    write_minimal_tests_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test from a temporary working directory.

    A regression in the success/cleanup path must never write
    ``manual_results_*.yaml`` into the repository checkout.
    """
    monkeypatch.chdir(path=tmp_path)


class TestBuildRunAttributes:
    def test_explicit_attrs_emit_short_keys(self) -> None:
        """Verify explicit CLI args produce short key names."""
        result = _build_run_attributes(
            team="NETWORK",
            bundle="v4.22.0",
            cnv_version="4.22",
            arch="amd64",
            ocp_version="4.22.0",
            cluster_name="bm15a",
            cluster_domain="bm15a.example.com",
            storage_class="ocs-storagecluster-ceph-rbd",
            channel="candidate",
        )
        keys = {attr["key"] for attr in result}

        assert "ARCH" in keys, "Expected: explicit CLI args produce short key names"
        assert "OCP" in keys, "Expected: explicit CLI args produce short key names"
        assert "CNV_XY_VER" in keys, "Expected: explicit CLI args produce short key names"
        assert "SC" in keys, "Expected: explicit CLI args produce short key names"
        assert "BUNDLE" in keys, "Expected: explicit CLI args produce short key names"
        assert "TEAM" in keys, "Expected: explicit CLI args produce short key names"
        assert "ARCHITECTURE" not in keys, "Expected: explicit CLI args produce short key names"
        assert "OCP_VERSION" not in keys, "Expected: explicit CLI args produce short key names"
        assert "CNV_VERSION" not in keys, "Expected: explicit CLI args produce short key names"
        assert "STORAGE_CLASS" not in keys, "Expected: explicit CLI args produce short key names"

    def test_cnv_version_derived_from_bundle(self) -> None:
        """Verify CNV_XY_VER is auto-derived from BUNDLE when not explicitly set."""
        result = _build_run_attributes(bundle="v4.22.0.rhel9-102")
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert attrs_by_key["CNV_XY_VER"] == "4.22", f"Expected '4.22', got {attrs_by_key['CNV_XY_VER']!r}"

    def test_explicit_cnv_version_wins_over_bundle_derivation(self) -> None:
        """Explicit --cnv-version is never silently discarded.

        When both --bundle and --cnv-version are provided, the explicit
        CLI value wins, consistent with every other CLI override.
        """
        result = _build_run_attributes(
            bundle="v4.22.0",
            cnv_version="4.21",
        )
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert attrs_by_key["CNV_XY_VER"] == "4.21", f"Expected '4.21', got {attrs_by_key['CNV_XY_VER']!r}"

    def test_cluster_cnv_version_kept_without_explicit_bundle(self) -> None:
        """Verify cluster-derived CNV_XY_VER is kept when bundle is not explicit."""
        result = _build_run_attributes(
            cluster_attrs=[
                {"key": "BUNDLE", "value": "v4.22.0"},
                {"key": "CNV_XY_VER", "value": "4.21"},
            ],
        )
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert attrs_by_key["CNV_XY_VER"] == "4.21", f"Expected '4.21', got {attrs_by_key['CNV_XY_VER']!r}"

    def test_cnv_version_not_derived_without_bundle(self) -> None:
        """Verify CNV_XY_VER is not set when BUNDLE is missing."""
        result = _build_run_attributes()
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert "CNV_XY_VER" not in attrs_by_key, "Expected: CNV_XY_VER is not set when BUNDLE is missing"

    def test_team_uppercased(self) -> None:
        """Verify team name is uppercased."""
        result = _build_run_attributes(team="network")
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert attrs_by_key["TEAM"] == "NETWORK", f"Expected 'NETWORK', got {attrs_by_key['TEAM']!r}"

    def test_tier_uppercased(self) -> None:
        """Verify tier label is uppercased when provided."""
        result = _build_run_attributes(tier="tier-2")
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert attrs_by_key["TIER"] == "TIER-2", f"Expected 'TIER-2', got {attrs_by_key['TIER']!r}"

    def test_manual_attribute_always_present(self) -> None:
        """Verify the MANUAL run attribute is always emitted as 'true'."""
        result = _build_run_attributes(team="NETWORK")
        attrs_by_key = {attr["key"]: attr["value"] for attr in result}
        assert attrs_by_key["MANUAL"] == "true", f"Expected 'true', got {attrs_by_key['MANUAL']!r}"

        result_without_team = _build_run_attributes()
        attrs_by_key_without_team = {attr["key"]: attr["value"] for attr in result_without_team}
        assert attrs_by_key_without_team["MANUAL"] == "true", "Expected: MANUAL attribute present even without a team"


class TestLoadBatchFile:
    def test_load_batch_file(self, tmp_path: Path) -> None:
        """Verify results and metadata are loaded from a batch YAML file."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=(
                "metadata:\n"
                "  team: NETWORK\n"
                "  bundle: v4.22.0\n"
                "results:\n"
                "  - test: tests/net/test_a.py::TestA::test_one\n"
                "    status: passed\n"
                "  - test: tests/net/test_a.py::TestA::test_two\n"
                "    status: failed\n"
                "    comment: boom\n"
                "    issue_type_label: Product Bug\n"
            ),
            encoding="utf-8",
        )

        results, metadata = _load_batch_file(batch_path=batch_path)

        assert len(results) == 2, f"Expected 2, got {len(results)!r}"
        assert results[0].status == "PASSED", f"Expected 'PASSED', got {results[0].status!r}"
        assert results[1].status == "FAILED", f"Expected 'FAILED', got {results[1].status!r}"
        assert results[1].issue_type_label == "Product Bug", (
            f"Expected 'Product Bug', got {results[1].issue_type_label!r}"
        )
        assert metadata["team"] == "NETWORK", f"Expected 'NETWORK', got {metadata['team']!r}"
        assert metadata["bundle"] == "v4.22.0", f"Expected 'v4.22.0', got {metadata['bundle']!r}"

    def test_load_batch_file_invalid_status(self, tmp_path: Path) -> None:
        """Verify unknown status values raise a single clean ClickException.

        The message must carry the raw value as typed and the allowed set
        exactly once — not the stacked coerce_status error text.
        """
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/net/test_a.py::TestA::test_one\n    status: maybe\n"),
            encoding="utf-8",
        )

        with pytest.raises(
            ClickException,
            match=(
                r"Invalid status 'maybe' for test 'tests/net/test_a\.py::TestA::test_one' "
                "in batch file .*; expected one of: FAILED, PASSED, SKIPPED"
            ),
        ):
            _load_batch_file(batch_path=batch_path)

    def test_load_batch_file_status_with_trailing_whitespace(self, tmp_path: Path) -> None:
        """Verify a hand-edited status with trailing whitespace is still accepted."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=('results:\n  - test: tests/net/test_a.py::TestA::test_one\n    status: "passed "\n'),
            encoding="utf-8",
        )

        results, _metadata = _load_batch_file(batch_path=batch_path)
        assert results[0].status == "PASSED", "Expected: trailing whitespace in status is tolerated"

    def test_load_batch_file_invalid_test_type(self, tmp_path: Path) -> None:
        """Verify non-string test values raise a ClickException."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: 123\n    status: passed\n"),
            encoding="utf-8",
        )

        with pytest.raises(ClickException, match="Invalid test type"):
            _load_batch_file(batch_path=batch_path)

    def test_load_batch_file_null_comment_coerced(self, tmp_path: Path) -> None:
        """Verify a YAML null comment is coerced to an empty string."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/net/test_a.py::TestA::test_one\n    status: passed\n    comment:\n"),
            encoding="utf-8",
        )

        results, _metadata = _load_batch_file(batch_path=batch_path)
        assert results[0].comment == "", "Expected: null comment loads as empty string"

    def test_load_batch_file_null_test_rejected(self, tmp_path: Path) -> None:
        """Verify a YAML null test key is rejected at load time."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test:\n    status: passed\n"),
            encoding="utf-8",
        )

        with pytest.raises(ClickException, match="missing or null 'test' key"):
            _load_batch_file(batch_path=batch_path)

    def test_load_batch_file_strips_whitespace_from_metadata_and_comment(self, tmp_path: Path) -> None:
        """Verify whitespace-padded hand-edited values are stripped on load.

        A padded ``team`` would otherwise produce a Datadog tag with
        embedded spaces (``team: NETWORK ``) — a different tag.
        """
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=(
                "metadata:\n"
                '  team: " NETWORK "\n'
                '  bundle: " v4.22.0 "\n'
                "results:\n"
                "  - test: tests/net/test_a.py::TestA::test_one\n"
                "    status: passed\n"
                '    comment: " flaky on node two "\n'
            ),
            encoding="utf-8",
        )

        results, metadata = _load_batch_file(batch_path=batch_path)

        assert metadata["team"] == "NETWORK", f"Expected 'NETWORK' with no embedded spaces, got {metadata['team']!r}"
        assert metadata["bundle"] == "v4.22.0", f"Expected 'v4.22.0', got {metadata['bundle']!r}"
        assert results[0].comment == "flaky on node two", f"Expected 'flaky on node two', got {results[0].comment!r}"

    @pytest.mark.parametrize("metadata_key", ["team", "bundle"])
    def test_load_batch_file_non_string_metadata_rejected(self, tmp_path: Path, metadata_key: str) -> None:
        """Verify non-string team/bundle metadata values are rejected, not stringified."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=(
                f"metadata:\n  {metadata_key}: [NETWORK]\n"
                "results:\n  - test: tests/net/test_a.py::TestA::test_one\n    status: passed\n"
            ),
            encoding="utf-8",
        )

        with pytest.raises(ClickException, match=f"Invalid {metadata_key} type"):
            _load_batch_file(batch_path=batch_path)


class TestMainDryRun:
    def test_dry_run_no_upload(self, tmp_path: Path) -> None:
        """Verify dry-run with a batch file exits without uploading."""
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=(
                "metadata:\n"
                "  team: NETWORK\n"
                "  bundle: v4.22.0\n"
                "results:\n"
                "  - test: tests/net/test_a.py::TestA::test_one\n"
                "    status: passed\n"
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli=main,
            args=[
                "--tests-dir",
                str(tests_dir),
                "--batch-file",
                str(batch_path),
                "--dry-run",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "No data was uploaded" in result.output, "Expected: dry-run with a batch file exits without uploading"
        assert "TEAM = NETWORK" in result.output, "Expected: dry-run with a batch file exits without uploading"


class TestSaveResultsForRetry:
    def test_save_load_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify a saved retry file reloads with metadata and results intact."""
        monkeypatch.chdir(path=tmp_path)
        results = [
            ManualTestResult(test="tests/net/test_a.py::TestA::test_one", status="PASSED"),
            ManualTestResult(
                test="tests/net/test_a.py::TestA::test_two",
                status="FAILED",
                comment="boom",
                issue_type_label="Product Bug",
            ),
            ManualTestResult(test="tests/net/test_a.py::TestA::test_three", status="SKIPPED"),
        ]
        attributes = [{"key": "TEAM", "value": "NETWORK"}]

        saved_path = _save_results_for_retry(
            results=results,
            team="NETWORK",
            bundle="v4.22.0",
            attributes=attributes,
        )
        assert saved_path is not None, "Expected: retry file is saved for the round trip"
        loaded_results, metadata = _load_batch_file(batch_path=saved_path)

        assert loaded_results == results, "Expected matching values"
        assert metadata["team"] == "NETWORK", f"Expected 'NETWORK', got {metadata['team']!r}"
        assert metadata["bundle"] == "v4.22.0", f"Expected 'v4.22.0', got {metadata['bundle']!r}"
        assert metadata["attributes"] == attributes, "Expected matching values"


class TestFromClusterImportGuard:
    def test_from_cluster_without_cluster_access(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify --from-cluster fails cleanly when cluster modules did not load."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/net/test_a.py::TestA::test_one\n    status: passed\n"),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            reporter_module,
            "_CLUSTER_INFO_IMPORT_ERROR",
            "Invalid kube-config file. No configuration found.",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli=main,
            args=["--batch-file", str(batch_path), "--from-cluster", "--dry-run"],
        )

        assert result.exit_code != 0, "Expected: --from-cluster fails without cluster access"
        assert "--from-cluster requires cluster access" in result.output, (
            "Expected: clean ClickException guidance when cluster modules did not load"
        )

    def test_from_cluster_with_arch_env_var_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify --from-cluster fails cleanly when the arch env var overrides detection."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/net/test_a.py::TestA::test_one\n    status: passed\n"),
            encoding="utf-8",
        )

        monkeypatch.setattr(reporter_module, "_CLUSTER_INFO_IMPORT_ERROR", None)
        monkeypatch.setenv(name="OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH", value="amd64")
        runner = CliRunner()
        result = runner.invoke(
            cli=main,
            args=["--batch-file", str(batch_path), "--from-cluster", "--dry-run"],
        )

        assert result.exit_code != 0, "Expected: --from-cluster fails with the arch env var set"
        assert "cannot be combined with OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH" in result.output, (
            "Expected: clean ClickException when the env var would override arch detection"
        )


class TestLoadBatchFileAttributes:
    def test_load_batch_file_invalid_attributes_entry(self, tmp_path: Path) -> None:
        """Verify non-dict or non-string attributes entries are rejected at load time."""
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=(
                "results:\n"
                "  - test: tests/net/test_a.py::TestA::test_one\n"
                "    status: passed\n"
                "metadata:\n"
                "  attributes:\n"
                "    - 1\n"
            ),
            encoding="utf-8",
        )
        with pytest.raises(ClickException, match="Invalid attributes entry"):
            _load_batch_file(batch_path=batch_path)


class TestMergeBatchMetadata:
    def test_cli_values_not_overridden_by_batch_metadata(self) -> None:
        """Verify CLI-provided team/bundle/cluster attrs win over batch metadata."""
        cluster_attrs = [{"key": "CLUSTER_NAME", "value": "bm15a"}]
        team, bundle, merged_attrs = _merge_batch_metadata(
            batch_metadata={
                "team": "STORAGE",
                "bundle": "v4.21.0",
                "attributes": [{"key": "TEAM", "value": "STORAGE"}],
            },
            team="NETWORK",
            bundle="v4.22.0",
            cluster_attrs=cluster_attrs,
        )

        assert team == "NETWORK", f"Expected 'NETWORK', got {team!r}"
        assert bundle == "v4.22.0", f"Expected 'v4.22.0', got {bundle!r}"
        assert merged_attrs == cluster_attrs, f"Expected {cluster_attrs!r}, got {merged_attrs!r}"

    def test_batch_metadata_fills_missing_cli_values(self) -> None:
        """Verify batch metadata fills team/bundle when the CLI provided none."""
        team, bundle, merged_attrs = _merge_batch_metadata(
            batch_metadata={"team": "NETWORK", "bundle": "v4.22.0"},
            team=None,
            bundle=None,
            cluster_attrs=None,
        )

        assert team == "NETWORK", f"Expected 'NETWORK', got {team!r}"
        assert bundle == "v4.22.0", f"Expected 'v4.22.0', got {bundle!r}"
        assert merged_attrs is None, f"Expected None, got {merged_attrs!r}"

    def test_restored_attributes_prevent_bundle_override(self) -> None:
        """Verify a restored retry file's saved CNV version is not re-derived from its bundle."""
        saved_attrs = [
            {"key": "BUNDLE", "value": "v4.22.0"},
            {"key": "CNV_XY_VER", "value": "4.21"},
        ]

        _team, bundle, restored_attrs = _merge_batch_metadata(
            batch_metadata={"bundle": "v4.22.0", "attributes": saved_attrs},
            team=None,
            bundle=None,
            cluster_attrs=None,
        )

        assert bundle is None, (
            "Expected: metadata bundle is not promoted when saved attributes were restored, "
            "so the saved CNV_XY_VER is not re-derived"
        )
        assert restored_attrs == saved_attrs, f"Expected {saved_attrs!r}, got {restored_attrs!r}"

    def test_restored_attributes_missing_bundle_filled_from_metadata(self) -> None:
        """Verify a restored attributes list without BUNDLE gets it filled from batch metadata."""
        saved_attrs = [{"key": "TEAM", "value": "NETWORK"}]

        _team, bundle, restored_attrs = _merge_batch_metadata(
            batch_metadata={"bundle": "v4.22.0", "attributes": saved_attrs},
            team=None,
            bundle=None,
            cluster_attrs=None,
        )

        assert bundle is None, "Expected: bundle stays unset (no explicit override)"
        assert restored_attrs is not None, "Expected: restored attributes list"
        assert {"key": "BUNDLE", "value": "v4.22.0"} in restored_attrs, (
            "Expected: missing BUNDLE filled from batch metadata so upload validation passes"
        )

    def test_saved_attributes_restored_only_without_cluster_attrs(self) -> None:
        """Verify saved attributes are restored only when no cluster attrs were resolved."""
        saved_attrs = [{"key": "TEAM", "value": "NETWORK"}]

        _team, _bundle, restored_attrs = _merge_batch_metadata(
            batch_metadata={"attributes": saved_attrs},
            team=None,
            bundle=None,
            cluster_attrs=None,
        )
        assert restored_attrs == saved_attrs, f"Expected {saved_attrs!r}, got {restored_attrs!r}"

        cluster_attrs = [{"key": "CLUSTER_NAME", "value": "bm15a"}]
        _team, _bundle, kept_attrs = _merge_batch_metadata(
            batch_metadata={"attributes": saved_attrs},
            team=None,
            bundle=None,
            cluster_attrs=cluster_attrs,
        )
        assert kept_attrs == cluster_attrs, f"Expected {cluster_attrs!r}, got {kept_attrs!r}"


class TestBatchUnmatchedWarning:
    def test_batch_unmatched_node_id_warns(self, tmp_path: Path) -> None:
        """Verify batch entries matching no collected test produce a stderr warning."""
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/net/test_typo.py::TestA::test_one\n    status: passed\n"),
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli=main,
            args=["--tests-dir", str(tests_dir), "--batch-file", str(batch_path), "--dry-run"],
        )
        assert result.exit_code == 0, "Expected: unmatched node_id still uploads (warning only)"
        assert "match no collected manual test" in result.stderr, (
            "Expected: stderr warning for batch entries matching no collected test"
        )


class TestInvalidMarkerExpression:
    def test_invalid_marker_expression_with_no_manual_tests(self, tmp_path: Path) -> None:
        """Verify an invalid -m expression fails even when no manual tests are collected."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_automated.py").write_text(
            data=("import pytest\n\n\nclass TestAutomated:\n    def test_one(self):\n        assert True\n"),
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            cli=main,
            args=["--tests-dir", str(tests_dir), "-m", "smoke and (", "--dry-run"],
        )

        assert result.exit_code != 0, "Expected: invalid -m expression fails even with zero manual tests"
        assert "Invalid marker expression" in result.output, (
            "Expected: invalid-expression error instead of a silent empty selection"
        )


class TestUploadPreflight:
    def test_missing_api_key_fails_before_prompting(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify a missing API key fails before the tester enters any verdicts."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.delenv(name="DATADOG_API_KEY", raising=False)
        monkeypatch.delenv(name="DD_API_KEY", raising=False)
        with patch(
            target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
            return_value="/usr/bin/datadog-ci",
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\n",
            )

        assert result.exit_code != 0, "Expected: missing API key fails the run"
        assert "DATADOG_API_KEY" in result.output, "Expected: clear API key error message"
        assert "Result (p=pass" not in result.output, "Expected: failure happens before the verdict prompt"

    def test_missing_datadog_ci_binary_fails_before_prompting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a missing datadog-ci binary fails before the verdict loop."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with patch(
            target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
            return_value=None,
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\n",
            )

        assert result.exit_code != 0, "Expected: missing datadog-ci binary fails the run"
        assert "datadog-ci not found" in result.output, "Expected: clear datadog-ci install guidance"

    def test_missing_required_attributes_fails_without_dry_run(self, tmp_path: Path) -> None:
        """Verify a non-dry-run missing a required attribute fails before prompting."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        all_args = required_attr_args(tests_dir=tests_dir)
        bundle_flag_index = all_args.index("--bundle")
        # Split on a plain index variable: ruff format writes complex slice
        # bounds with a space before ':' (E203), flake8 rejects it.
        after_bundle_index = bundle_flag_index + 2
        incomplete_args = all_args[:bundle_flag_index] + all_args[after_bundle_index:]

        result = CliRunner().invoke(
            cli=main,
            args=incomplete_args,
        )

        assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code!r}"
        assert "Missing required run attributes" in result.output, "Expected: error listing the missing attributes"
        assert "BUNDLE" in result.output, "Expected: error names the missing BUNDLE attribute"
        assert "Result (p=pass" not in result.output, "Expected: failure happens before the verdict prompt"


class TestDryRunReadinessWarning:
    def test_dry_run_warns_about_missing_required_attributes(self, tmp_path: Path) -> None:
        """Verify dry-run predicts upload failure when attributes are missing."""
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_manual_minimal.py::test_minimal\n    status: passed\n"),
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            cli=main,
            args=["--tests-dir", str(tests_dir), "--batch-file", str(batch_path), "--dry-run"],
        )

        assert result.exit_code == 0, "Expected: dry-run never fails on missing attributes"
        assert "upload would fail — missing:" in result.stderr, "Expected: warning listing missing attributes"
        assert "No data was uploaded" in result.output, "Expected: dry-run still exits without uploading"


class TestInteractiveFlow:
    def test_interactive_verdicts_and_upload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify interactive pass/fail verdicts upload and leave no XML in the working directory."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=2)
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report") as mock_upload,
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\nf\n1\nboom\n",
            )

        assert result.exit_code == 0, result.output
        assert "Uploaded 2 results" in result.output, "Expected: success message after interactive run"
        assert mock_upload.call_count == 1, "Expected: exactly one upload attempt"
        uploaded_tags = mock_upload.call_args.kwargs["tags"]
        assert "manual:true" in uploaded_tags, f"Expected manual:true tag, got {uploaded_tags!r}"
        assert "team:NETWORK" in uploaded_tags, f"Expected team:NETWORK tag, got {uploaded_tags!r}"
        assert not list(tmp_path.glob("*.xml")), "Expected: no JUnit XML left in the working directory"
        assert not list(tmp_path.glob("manual_results_*.yaml")), "Expected: no retry file on success"

    def test_interactive_skip_verdict_in_summary_and_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a skip verdict reaches both the summary and the JUnit report."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        uploaded_xml: list[str] = []
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report",
                side_effect=capture_uploaded_xml(uploaded_xml=uploaded_xml),
            ),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="s\n",
            )

        assert result.exit_code == 0, result.output
        assert "Skipped: 1" in result.output, "Expected: skip verdict counted in the summary"
        assert uploaded_xml, "Expected: one uploaded report"
        assert "<skipped" in uploaded_xml[0], "Expected: skipped verdict serialized as a <skipped> element"

    def test_interactive_invalid_choice_then_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify an invalid verdict choice is rejected and re-prompted."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report"),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="x\np\n",
            )

        assert result.exit_code == 0, result.output
        assert "Invalid choice" in result.output, "Expected: invalid verdict choice is rejected"

    def test_interactive_invalid_defect_choice_then_valid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify an invalid defect-type choice is rejected and re-prompted."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report"),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="f\n9\n2\nboom\n",
            )

        assert result.exit_code == 0, result.output
        assert "Invalid choice '9'" in result.output, "Expected: invalid defect-type choice is rejected"

    def test_interactive_quit_saves_partial_results_without_upload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify quitting saves partial results for retry and uploads nothing."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=2)
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report") as mock_upload,
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\nq\n",
            )

        assert result.exit_code == 0, result.output
        assert "nothing was uploaded" in result.output, "Expected: clear no-upload message on quit"
        assert not mock_upload.called, "Expected: no upload attempt after quitting"
        retry_files = list(tmp_path.glob("manual_results_*.yaml"))
        assert len(retry_files) == 1, f"Expected one retry file, got {retry_files!r}"
        loaded_results, metadata = _load_batch_file(batch_path=retry_files[0])
        assert len(loaded_results) == 1, f"Expected 1 partial result, got {len(loaded_results)!r}"
        assert loaded_results[0].status == "PASSED", "Expected: partial result keeps its verdict"
        assert metadata["team"] == "NETWORK", f"Expected 'NETWORK', got {metadata['team']!r}"

    def test_interactive_eof_saves_partial_results_without_upload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify EOF (Ctrl-D) during the session saves partial results for retry."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=2)
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report") as mock_upload,
        ):
            # First test gets a verdict; the second prompt hits EOF (Ctrl-D).
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\n",
            )

        assert result.exit_code == 0, result.output
        assert "Session interrupted — partial results saved to" in result.output, (
            "Expected: interrupted-session message with the retry path"
        )
        assert "nothing was uploaded" in result.output, "Expected: clear no-upload message on interrupt"
        assert not mock_upload.called, "Expected: no upload attempt after an interrupted session"
        retry_files = list(tmp_path.glob("manual_results_*.yaml"))
        assert len(retry_files) == 1, f"Expected one retry file, got {retry_files!r}"
        loaded_results, _metadata = _load_batch_file(batch_path=retry_files[0])
        assert len(loaded_results) == 1, f"Expected 1 partial result, got {len(loaded_results)!r}"
        assert loaded_results[0].status == "PASSED", "Expected: verdict collected before EOF is kept"

    def test_interactive_eof_at_first_prompt_reports_interrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify an interrupt at the very first prompt is reported as an interrupt."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report") as mock_upload,
        ):
            # EOF (Ctrl-D) at the very first prompt: no verdict collected yet.
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="",
            )

        assert result.exit_code == 0, result.output
        assert "Session interrupted before any verdict" in result.output, (
            "Expected: interrupt at the first prompt is reported as an interrupt"
        )
        assert "No results to upload." not in result.output, "Expected: no plain empty-run message on interrupt"
        assert not mock_upload.called, "Expected: no upload attempt after an interrupted session"

    def test_interactive_quit_teamless_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify a team-less quit round-trips without fabricating a TEAM:ALL attribute."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=2)
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report"),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir, team=None),
                input="p\nq\n",
            )

        assert result.exit_code == 0, result.output
        retry_files = list(tmp_path.glob("manual_results_*.yaml"))
        assert len(retry_files) == 1, f"Expected one retry file, got {retry_files!r}"
        loaded_results, metadata = _load_batch_file(batch_path=retry_files[0])
        assert len(loaded_results) == 1, f"Expected 1 partial result, got {len(loaded_results)!r}"
        assert "team" not in metadata, "Expected: team-less session saves team as null, not 'ALL'"

        # Retry the saved file: no TEAM attribute may be fabricated from 'ALL'.
        retry_result = CliRunner().invoke(
            cli=main,
            args=[
                *required_attr_args(tests_dir=tests_dir, team=None),
                "--batch-file",
                str(retry_files[0]),
                "--dry-run",
            ],
        )
        assert retry_result.exit_code == 0, retry_result.output
        assert "TEAM = " not in retry_result.output, "Expected: retry of a team-less run stays team-less"

    def test_interactive_quit_save_failure_still_exits_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a failing retry save on the quit path exits 0 with a clear message."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=2)
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report"),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.yaml.dump",
                side_effect=OSError("disk full"),
            ),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\nq\n",
            )

        assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code!r}"
        assert "Failed to save partial results" in result.output, (
            "Expected: quit-path save failure is reported without failing the run"
        )
        assert not list(tmp_path.glob("manual_results_*.yaml")), "Expected: no retry file when the save fails"

    def test_successful_upload_cleanup_failure_warns_but_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a cleanup failure after a successful upload warns without failing the run."""
        tests_dir = write_manual_tests_dir(tmp_path=tmp_path, test_count=1)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report") as mock_upload,
            patch(target="pathlib.Path.unlink", side_effect=OSError("unlink boom")),
            patch.object(target=reporter_module.LOGGER, attribute="warning") as mock_warning,
        ):
            result = CliRunner().invoke(
                cli=main,
                args=required_attr_args(tests_dir=tests_dir),
                input="p\n",
            )

        assert result.exit_code == 0, f"Expected exit code 0, got {result.exit_code!r}"
        assert "Uploaded 1 results" in result.output, "Expected: upload success is still reported"
        assert mock_warning.called, "Expected: cleanup failure is logged as a warning"
        warning_messages = [call.args[0] for call in mock_warning.call_args_list]
        assert any("Failed to clean up temporary report directory" in message for message in warning_messages), (
            f"Expected a cleanup warning, got {warning_messages!r}"
        )
        # The unlink patch keeps the temp report behind on purpose; remove it
        # so repeated runs do not accumulate /tmp/manual_tests_reporter_* entries.
        kept_xml_path = mock_upload.call_args.kwargs["xml_path"]
        assert kept_xml_path.exists(), f"Expected the kept JUnit report at {kept_xml_path}"
        shutil.rmtree(kept_xml_path.parent)


class TestMalformedKubeconfig:
    def test_batch_dry_run_with_malformed_kubeconfig(self, tmp_path: Path) -> None:
        """Verify a malformed-YAML kubeconfig does not crash import-time flows.

        The import guard must catch the unwrapped YAMLError raised by the
        kubernetes config loader, not only ConfigException.
        """
        kubeconfig_path = tmp_path / "kubeconfig"
        kubeconfig_path.write_text(data="key: [unclosed", encoding="utf-8")
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_manual_minimal.py::test_minimal\n    status: passed\n"),
            encoding="utf-8",
        )
        # Strip the arch env var (set by the test bootstrap) so the child
        # process actually reads the malformed kubeconfig instead of
        # short-circuiting architecture resolution on the env var.
        child_env = {
            key: value for key, value in os.environ.items() if key != "OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH"
        }
        child_env["KUBECONFIG"] = str(kubeconfig_path)
        base_command = [
            sys.executable,
            "-m",
            "scripts.manual_tests_reporter.manual_tests_reporter",
            "--tests-dir",
            str(tests_dir),
            "--batch-file",
            str(batch_path),
        ]
        result, _, err = run_command(
            command=[*base_command, "--dry-run"],
            env=child_env,
            cwd=REPO_ROOT,
            verify_stderr=False,
            check=False,
        )
        assert result, f"Expected: dry-run succeeds with a malformed kubeconfig; stderr: {err}"
        assert "Traceback" not in err, "Expected: YAMLError caught by the import guard, no raw traceback"

        # Prove the guard fired (rather than the import succeeding):
        # --from-cluster must fail with the cluster-access guidance.
        run_failed, _, fail_err = run_command(
            command=[*base_command, "--from-cluster", "--dry-run"],
            env=child_env,
            cwd=REPO_ROOT,
            verify_stderr=False,
            check=False,
        )
        assert not run_failed, "Expected: --from-cluster fails when the import guard fired"
        assert "--from-cluster requires cluster access" in fail_err, (
            "Expected: guidance message proving the guard caught the import failure"
        )


class TestUploadFailure:
    def test_upload_failure_saves_retry_and_keeps_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify an upload failure saves a retry file and keeps the JUnit report."""
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_manual_minimal.py::test_minimal\n    status: passed\n"),
            encoding="utf-8",
        )
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report",
                side_effect=DatadogUploadError("upload boom"),
            ),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=[
                    *required_attr_args(tests_dir=tests_dir),
                    "--batch-file",
                    str(batch_path),
                ],
            )

        assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code!r}"
        assert "upload boom" in result.output, "Expected: original upload error is reported"
        assert "JUnit report kept at" in result.output, "Expected: JUnit report kept message on upload failure"
        cleanup_kept_junit_report(result_output=result.output)
        retry_files = list(tmp_path.glob("manual_results_*.yaml"))
        assert len(retry_files) == 1, f"Expected one retry file, got {retry_files!r}"

    def test_upload_failure_retry_save_error_does_not_mask_original(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify a failing retry save does not mask the original upload error."""
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_manual_minimal.py::test_minimal\n    status: passed\n"),
            encoding="utf-8",
        )
        monkeypatch.chdir(path=tmp_path)
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report",
                side_effect=DatadogUploadError("upload boom"),
            ),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.yaml.dump",
                side_effect=OSError("disk full"),
            ),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=[
                    *required_attr_args(tests_dir=tests_dir),
                    "--batch-file",
                    str(batch_path),
                ],
            )

        assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code!r}"
        assert "upload boom" in result.output, "Expected: original upload error is still reported"
        assert "Failed to save results for retry" in result.output, (
            "Expected: retry-save failure is reported without masking the original error"
        )
        assert not list(tmp_path.glob("manual_results_*.yaml")), "Expected: no retry file when the save fails"
        cleanup_kept_junit_report(result_output=result.output)

    def test_keyboard_interrupt_during_upload_saves_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify Ctrl-C during report build/upload saves a retry file without a traceback.

        [NEGATIVE] An interrupt after the verdicts but outside the interactive
        loop must route into the retry-save path, not propagate as a raw
        KeyboardInterrupt traceback with the verdicts lost.
        """
        tests_dir = write_minimal_tests_dir(tmp_path=tmp_path)
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_manual_minimal.py::test_minimal\n    status: passed\n"),
            encoding="utf-8",
        )
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report",
                side_effect=KeyboardInterrupt,
            ),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=[
                    *required_attr_args(tests_dir=tests_dir),
                    "--batch-file",
                    str(batch_path),
                ],
            )

        assert result.exit_code == 1, f"Expected exit code 1, got {result.exit_code!r}"
        assert "Session interrupted during upload — partial results saved to" in result.output, (
            "Expected: interrupt during upload saves partial results with a clean message"
        )
        assert "Traceback" not in result.output, "Expected: no raw traceback on interrupt during upload"
        retry_files = list(tmp_path.glob("manual_results_*.yaml"))
        assert len(retry_files) == 1, f"Expected one retry file, got {retry_files!r}"
        loaded_results, _metadata = _load_batch_file(batch_path=retry_files[0])
        assert loaded_results[0].status == "PASSED", "Expected: verdict collected before the interrupt is kept"
        cleanup_kept_junit_report(result_output=result.output)


class TestTeamInference:
    def test_team_inferred_from_tests_dir(self, tmp_path: Path) -> None:
        """Verify the team is inferred from the directory under tests/."""
        tests_dir = tmp_path / "x" / "tests" / "storage"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_storage_manual.py").write_text(
            data=MINIMAL_MANUAL_TEST_SOURCE,
            encoding="utf-8",
        )
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_storage_manual.py::test_minimal\n    status: passed\n"),
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            cli=main,
            args=["--tests-dir", str(tests_dir), "--batch-file", str(batch_path), "--dry-run"],
        )

        assert result.exit_code == 0, result.output
        assert "Inferred team: STORAGE" in result.output, "Expected: team inferred from the tests directory"
        assert "TEAM = STORAGE" in result.output, "Expected: inferred team reaches the run attributes"


class TestBatchUpload:
    def test_batch_upload_keeps_polarion_linkage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify a batch upload writes the collected Polarion ID into the JUnit XML."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_polarion_manual.py").write_text(
            data=(
                "import pytest\n\n\n"
                "@pytest.mark.manual\n"
                '@pytest.mark.polarion("MOCK-4321")\n'
                "def test_polarion_linked():\n    pass\n"
            ),
            encoding="utf-8",
        )
        batch_path = tmp_path / "batch.yaml"
        batch_path.write_text(
            data=("results:\n  - test: tests/test_polarion_manual.py::test_polarion_linked\n    status: passed\n"),
            encoding="utf-8",
        )
        monkeypatch.setenv(name="DATADOG_API_KEY", value="test-key")
        uploaded_xml: list[str] = []
        with (
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.shutil.which",
                return_value="/usr/bin/datadog-ci",
            ),
            patch(
                target="scripts.manual_tests_reporter.manual_tests_reporter.upload_junit_report",
                side_effect=capture_uploaded_xml(uploaded_xml=uploaded_xml),
            ),
        ):
            result = CliRunner().invoke(
                cli=main,
                args=[*required_attr_args(tests_dir=tests_dir), "--batch-file", str(batch_path)],
            )

        assert result.exit_code == 0, result.output
        assert uploaded_xml, "Expected: one uploaded report"
        assert "dd_tags[polarion-testcase-id]" in uploaded_xml[0], "Expected: Polarion property in the uploaded XML"
        assert "MOCK-4321" in uploaded_xml[0], "Expected: collected Polarion ID in the uploaded XML"
