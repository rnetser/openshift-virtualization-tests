# Manual Test Reporter for ReportPortal

Push manual test results for unautomated STD (Standard Test Design) placeholder tests
to [ReportPortal](https://reportportal-cnv.apps.dno.ocp-hub.prod.psi.redhat.com).
These are tests marked with `__test__ = False` that are not yet automated.

---

## Table of Contents

- [Authentication](#authentication)
- [Launch Attributes](#launch-attributes)
- [Usage Examples](#usage-examples)
- [Interactive Mode](#interactive-mode)
- [Batch YAML Format](#batch-yaml-format)
- [Failure Recovery](#failure-recovery)
- [CLI Reference](#cli-reference)

---

## Authentication

The reporter authenticates with ReportPortal using an API token.

1. Log in to [ReportPortal](https://reportportal-cnv.apps.dno.ocp-hub.prod.psi.redhat.com).
2. Click your avatar (top-right) → **API Keys**.
3. Generate a new key or copy an existing one.
4. Export it as an environment variable:

```bash
export REPORT_PORTAL_TOKEN="your-api-key-here"
```

> **Tip:** Add the export to your shell profile (`~/.bashrc`, `~/.zshrc`) so you
> don't have to set it every session.

---

## Launch Attributes

Every ReportPortal launch is tagged with attributes that describe the environment
under test. Attributes can be auto-filled from a connected cluster, provided by the
user, or set automatically.

### Auto-filled from cluster (`--from-cluster`)

When `--from-cluster` is passed, the tool queries the connected OpenShift cluster
and populates these attributes automatically:

| Attribute        | Description                                    | Example                          |
|------------------|------------------------------------------------|----------------------------------|
| `ARCH`           | CPU architecture of the cluster nodes          | `amd64`                          |
| `OCP`            | OpenShift platform version                     | `4.22.0-ec.4`                    |
| `CNV_XY_VER`     | CNV major.minor version                        | `4.22`                           |
| `BUNDLE`         | Full CNV/HCO bundle version                    | `v4.22.0.rhel9-102`              |
| `CLUSTER_NAME`   | Cluster infrastructure name                    | `bm15a-tlv2`                     |
| `CLUSTER_DOMAIN` | Cluster base domain                            | `bm15a-tlv2.abi.cnv-qe.rhood.us`|
| `SC`             | Default storage class                          | `OCS`                            |
| `CHANNEL`        | HCO subscription channel                       | `candidate`                      |

### User-provided (required)

| Attribute | Description                          | Examples                            |
|-----------|--------------------------------------|-------------------------------------|
| `TEAM`    | QE team that owns the test results   | `NETWORK`, `STORAGE`, `VIRT`, `IUO` |

### User-provided (optional)

| Attribute | Description                          | Examples             |
|-----------|--------------------------------------|----------------------|
| `TIER`    | Test tier level                      | `TIER-2`, `TIER-3`   |

### Automatically set

| Attribute    | Description                                        |
|--------------|----------------------------------------------------|
| `MANUAL=true`| Distinguishes manual runs from automated CI runs   |

### Manual override (no cluster access)

If you don't have access to the cluster, you can pass all attributes as CLI flags:

```bash
uv run python -m scripts.rp_manual_reporter.rp_manual_reporter \
    --team VIRT \
    --bundle v4.22.0.rhel9-102 \
    --cnv-version 4.22 \
    --arch amd64 \
    --ocp-version 4.22.0-ec.4 \
    --cluster-name bm15a-tlv2 \
    --cluster-domain abi.cnv-qe.rhood.us \
    --sc OCS \
    --channel candidate \
    --tier TIER-2
```

---

## Usage Examples

### Interactive mode (with cluster)

Auto-fill environment attributes from the connected cluster and interactively
mark each STORAGE team placeholder test:

```bash
uv run python -m scripts.rp_manual_reporter.rp_manual_reporter \
    --team STORAGE --from-cluster
```

### Interactive mode (manual attributes)

Provide environment attributes manually when no cluster is connected:

```bash
uv run python -m scripts.rp_manual_reporter.rp_manual_reporter \
    --team NETWORK --bundle v4.22.0.rhel9-102 --cnv-version 4.22
```

### Batch mode (from YAML)

Submit pre-recorded results from a YAML file instead of going through
the interactive prompt:

```bash
uv run python -m scripts.rp_manual_reporter.rp_manual_reporter \
    --team NETWORK --bundle v4.22.0 --batch-file results.yaml
```

### Dry run

Preview what would be reported without pushing anything to ReportPortal:

```bash
uv run python -m scripts.rp_manual_reporter.rp_manual_reporter \
    --team STORAGE --bundle v4.22.0 --dry-run
```

---

## Interactive Mode

When no `--batch-file` is provided, the tool enters interactive mode:

1. **Test discovery** — Scans the repo for STD placeholder tests (`__test__ = False`)
   filtered to the specified `--team`.

2. **One-by-one review** — Each test is displayed with full context:
   - Module and class docstrings (STP links, preconditions)
   - Test docstring (steps, expected results)
   - Pytest markers and fixtures
   - Polarion test case ID

3. **Verdict prompt** — For each test, enter one of:

   | Key | Action                                          |
   |-----|-------------------------------------------------|
   | `p` | **Pass** — mark the test as passed              |
   | `f` | **Fail** — mark the test as failed               |
   | `s` | **Skip** — skip this test (not reported)         |
   | `n` | **Next** — move to the next test without marking |
   | `q` | **Quit** — stop and push results collected so far|

4. **Failure comment** — When you mark a test as **failed**, the tool prompts for
   an optional comment (e.g., a bug ID like `CNV-12345` or a brief description).

---

## Batch YAML Format

The batch file lists test results as a YAML document. Each entry specifies the
full pytest node ID, a status, and an optional comment:

```yaml
results:
  - test: "tests/storage/cbt/test_cbt.py::TestFullBackupRestore::test_full_backup_push_mode_restore"
    status: passed
    comment: "Verified manually on cluster xyz"
  - test: "tests/network/upgrade/test_upgrade_network.py::TestUpgradeNetwork::test_udn_vm_state"
    status: failed
    comment: "Bug CNV-12345"
```

**Fields:**

| Field     | Required | Values                      | Description                        |
|-----------|----------|-----------------------------|------------------------------------|
| `test`    | Yes      | Full pytest node ID         | Identifies the placeholder test    |
| `status`  | Yes      | `passed`, `failed`, `skipped` | Test verdict                     |
| `comment` | No       | Free text                   | Bug ID, notes, or justification    |

---

## Failure Recovery

If the push to ReportPortal fails (network error, token expiry, server outage):

1. **Auto-save** — All collected results are automatically saved to a timestamped
   file:
   ```
   manual_results_<timestamp>.yaml
   ```
   This file uses the same format as the [batch YAML](#batch-yaml-format).

2. **Retry** — Once the issue is resolved, replay the saved results:
   ```bash
   uv run python -m scripts.rp_manual_reporter.rp_manual_reporter \
       --team STORAGE --bundle v4.22.0 --batch-file manual_results_20250612_143022.yaml
   ```

No manual work is lost — you never have to re-enter verdicts.

---

## CLI Reference

| Option              | Required | Default         | Description                                          |
|---------------------|----------|-----------------|------------------------------------------------------|
| `--team`            | Yes      | —               | QE team name (`NETWORK`, `STORAGE`, `VIRT`, `IUO`)   |
| `--from-cluster`    | No       | `false`         | Auto-fill launch attributes from the connected cluster |
| `--bundle`          | No*      | —               | CNV/HCO bundle version (e.g., `v4.22.0.rhel9-102`)   |
| `--cnv-version`     | No*      | —               | CNV major.minor version (e.g., `4.22`)                |
| `--arch`            | No*      | —               | Cluster CPU architecture (e.g., `amd64`)              |
| `--ocp-version`     | No*      | —               | OpenShift version (e.g., `4.22.0-ec.4`)               |
| `--cluster-name`    | No*      | —               | Cluster infrastructure name (e.g., `bm15a-tlv2`)     |
| `--cluster-domain`  | No*      | —               | Cluster base domain (e.g., `abi.cnv-qe.rhood.us`)    |
| `--sc`              | No*      | —               | Default storage class label (e.g., `OCS`)             |
| `--channel`         | No*      | —               | HCO subscription channel (e.g., `candidate`)          |
| `--tier`            | No       | —               | Test tier level (e.g., `TIER-2`, `TIER-3`)            |
| `--batch-file`      | No       | —               | Path to YAML file with pre-recorded results           |
| `--dry-run`         | No       | `false`         | Preview results without pushing to ReportPortal       |

> **\*** These flags are required when `--from-cluster` is not used. With
> `--from-cluster`, they are auto-filled but can still be passed to override
> specific values.
