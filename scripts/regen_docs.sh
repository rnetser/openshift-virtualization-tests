#!/usr/bin/env bash
# Regenerate the documentation site with pi-docsite and stage the output.
#
# Used by the `pi-docsite` pre-commit hook (formatter-style: the regenerated
# files are staged automatically, like ruff-format) and safe to run manually:
#
#   scripts/regen_docs.sh
#
# Output is byte-for-byte reproducible — regeneration only produces changes
# when the Markdown sources (docs/*.md, docs/nav.json) actually changed.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

uvx pi-docsite==4.10.0 \
  --docs-dir docs \
  --project-name openshift-virtualization-tests \
  --tagline "Tests for OpenShift Virtualization"

# Stage the generated site so the commit includes fresh output.
git add docs/*.html docs/index.html docs/assets docs/llms.txt docs/llms-full.txt docs/search-index.json
