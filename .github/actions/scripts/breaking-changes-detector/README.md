# Breaking Changes Detector

A GitHub Actions utility script for detecting breaking changes in Python codebases.

## Overview

This tool analyzes Python code changes using AST (Abstract Syntax Tree) analysis to detect potential breaking changes and their impact across your codebase. It's designed to run in GitHub Actions workflows to prevent breaking changes from being merged.

## Features

- **AST-based Analysis**: Deep code structure analysis for accurate detection
- **Usage Pattern Detection**: Finds where changed elements are actually used
- **Multiple Output Formats**: Console, JSON, and Markdown reports
- **GitHub Actions Integration**: Native support for GitHub workflow environments
- **Configurable**: Extensive configuration via environment variables and arguments
- **UV Package Management**: Modern Python packaging with uv

## Detected Breaking Changes

The tool can detect the following types of breaking changes:

- Function signature changes (parameters added/removed/renamed)
- Method signature changes
- Class/function/method removal
- Import path changes
- Type annotation changes
- Return type modifications
- Parameter type changes

## Usage

### In GitHub Actions Workflow

```yaml
name: Breaking Changes Check
on: [pull_request]

jobs:
  check-breaking-changes:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Need full history for comparison
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install uv
        uses: astral-sh/setup-uv@v2
      
      - name: Run Breaking Changes Detector
        run: |
          cd .github/actions/scripts/breaking-changes-detector
          uv run python action_entrypoint.py
        env:
          BREAKING_CHANGES_BASE_REF: ${{ github.event.pull_request.base.sha }}
          BREAKING_CHANGES_HEAD_REF: ${{ github.event.pull_request.head.sha }}
```

### Local Usage

```bash
# Navigate to the script directory
cd .github/actions/scripts/breaking-changes-detector

# Install dependencies with uv
uv sync

# Run analysis
uv run python breaking_changes_detector.py --base-ref origin/main --head-ref HEAD
```

### Environment Variables

```bash
export BREAKING_CHANGES_BASE_REF=origin/main
export BREAKING_CHANGES_HEAD_REF=HEAD
export BREAKING_CHANGES_LOG_LEVEL=INFO
export BREAKING_CHANGES_FAIL_ON_BREAKING=true
uv run python breaking_changes_detector.py
```

## Configuration

### Action Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `base-ref` | Base git reference for comparison | No | `origin/main` |
| `head-ref` | Head git reference for comparison | No | `HEAD` |
| `ignore-unused` | Ignore breaking changes with no detected usage | No | `false` |
| `include-patterns` | File patterns to include (comma-separated) | No | `**/*.py` |
| `exclude-patterns` | File patterns to exclude (comma-separated) | No | `**/test_*.py,**/tests/**/*.py` |
| `json-output` | Path to JSON output file | No | `breaking-changes.json` |
| `markdown-output` | Path to Markdown output file | No | `breaking-changes.md` |
| `log-level` | Logging level | No | `INFO` |
| `fail-on-breaking` | Fail when breaking changes are detected | No | `true` |

### Action Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | Exit code (0=no issues, 1=breaking changes, 2=error) |
| `reports-generated` | Whether reports were generated successfully |
| `json-report` | Path to generated JSON report |
| `markdown-report` | Path to generated Markdown report |

### Environment Variables

All configuration can be set via environment variables with the `BREAKING_CHANGES_` prefix:

- `BREAKING_CHANGES_BASE_REF`
- `BREAKING_CHANGES_HEAD_REF`
- `BREAKING_CHANGES_IGNORE_UNUSED`
- `BREAKING_CHANGES_INCLUDE_PATTERNS`
- `BREAKING_CHANGES_EXCLUDE_PATTERNS`
- `BREAKING_CHANGES_JSON_OUTPUT`
- `BREAKING_CHANGES_MARKDOWN_OUTPUT`
- `BREAKING_CHANGES_LOG_LEVEL`
- `BREAKING_CHANGES_FAIL_ON_BREAKING`

## Exit Codes

- `0`: No breaking changes detected
- `1`: Breaking changes detected
- `2`: Critical error occurred
- `130`: Process interrupted by user

## Output Formats

### Console Output
Provides a summary with colored output showing detected breaking changes grouped by severity.

### JSON Output
Structured data suitable for programmatic consumption:

```json
{
  "summary": {
    "total_files_analyzed": 5,
    "total_changes_detected": 2,
    "exit_code": 1
  },
  "breaking_changes": [
    {
      "change_type": "function_signature",
      "file_path": "src/module.py",
      "line_number": 10,
      "element_name": "my_function",
      "old_signature": "def my_function(a, b)",
      "new_signature": "def my_function(a, b, c)",
      "description": "Function signature changed: added parameter 'c'",
      "severity": "high"
    }
  ]
}
```

### Markdown Output
Human-readable report suitable for PR comments or documentation.

## Architecture

The tool consists of several modular components:

- **GitAnalyzer**: Handles git operations and file change detection
- **ASTAnalyzer**: Performs AST analysis to detect structural changes
- **UsageDetector**: Searches for usage patterns of changed elements
- **ReportGenerator**: Generates reports in multiple formats
- **ConfigManager**: Handles configuration from multiple sources

## Requirements

- Python 3.7+
- Git repository
- No external dependencies (uses Python standard library only)

## Error Handling

The tool includes comprehensive error handling:

- Git repository validation
- Python syntax error handling
- Graceful degradation for unparseable files
- Detailed logging and error reporting

## Contributing

This tool is part of the CNV project. For contributions:

1. Follow the existing code style
2. Add tests for new functionality
3. Update documentation as needed
4. Ensure all modules use only standard library dependencies

## License

This project follows the same license as the parent CNV project.