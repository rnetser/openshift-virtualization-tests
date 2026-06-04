"""Inject Polarion IDs as pytest markers on test functions.

Adds a ``@pytest.mark.polarion("CNV-XXXXX")`` decorator before each
test function's ``def`` line.  Uses line-number targeting and processes
insertions bottom-up to avoid offset shifts.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from scripts.polarion_sync.polarion_client import PolarionResult

LOGGER = logging.getLogger(__name__)


def inject_polarion_ids(results: list[PolarionResult]) -> dict[Path, str]:
    """Inject Polarion IDs as ``@pytest.mark.polarion()`` decorators.

    Args:
        results: list of ``PolarionResult`` mapping tests to Polarion IDs.

    Returns:
        Dict mapping modified file paths to their new content.
    """
    # Group results by file — process each file once
    by_file: dict[Path, list[PolarionResult]] = {}
    for result in results:
        by_file.setdefault(result.test.file, []).append(result)

    modified_files: dict[Path, str] = {}

    for file, file_results in by_file.items():
        source = file.read_text()
        source_lines = source.splitlines(keepends=True)

        # Ensure pytest is imported
        if "import pytest" not in source:
            # Find insertion point: after last import, or after module docstring if no imports
            last_import_idx = 0
            for idx, line in enumerate(source_lines):
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    last_import_idx = idx + 1
            if last_import_idx == 0:
                # No imports found — insert after module docstring
                tree = ast.parse(source)
                module_docstring = ast.get_docstring(tree)
                if module_docstring and tree.body:
                    first_node = tree.body[0]
                    if isinstance(first_node, ast.Expr) and isinstance(first_node.value, ast.Constant):
                        if first_node.end_lineno is not None:
                            last_import_idx = first_node.end_lineno
            source_lines.insert(last_import_idx, "import pytest\n")
            # Adjust linenos for results targeting lines after the insertion
            for result in file_results:
                if result.test.lineno > last_import_idx:
                    result.test.lineno += 1

        # Sort by line number descending so insertions don't shift later offsets
        file_results.sort(key=lambda result: result.test.lineno, reverse=True)

        for result in file_results:
            def_line_index = result.test.lineno - 1
            # Skip if polarion marker already exists above this def
            # Scan upward through decorators to check for existing polarion marker
            has_existing_polarion = False
            for scan_idx in range(def_line_index - 1, -1, -1):
                scan_line = source_lines[scan_idx].strip()
                if scan_line.startswith("@"):
                    if "@pytest.mark.polarion(" in scan_line:
                        has_existing_polarion = True
                        break
                elif scan_line == "":
                    continue  # Skip blank lines between decorators
                else:
                    break  # Hit non-decorator, non-blank line — stop scanning
            if has_existing_polarion:
                LOGGER.info(f"  Skipping {file.name}:{result.test.test_name} — @pytest.mark.polarion already present")
                continue
            def_line = source_lines[def_line_index]
            indent = " " * (len(def_line) - len(def_line.lstrip()))
            decorator_line = f'{indent}@pytest.mark.polarion("{result.polarion_id}")\n'
            source_lines.insert(def_line_index, decorator_line)
            LOGGER.info(
                f'  Injected @pytest.mark.polarion("{result.polarion_id}") into '
                f"{file.name}:{result.test.test_name} at line {result.test.lineno}"
            )

        new_content = "".join(source_lines)
        file.write_text(data=new_content)
        modified_files[file] = new_content

    return modified_files
