"""
GitHub Actions Utilities

Shared utilities for GitHub Actions integration to eliminate code duplication
between different entry points.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


def setup_github_actions_logging(logger_name: str = "github_actions_breaking_changes") -> logging.Logger:
    """Set up logging optimized for GitHub Actions."""
    logger = logging.getLogger(logger_name)

    # Clear any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    logger.setLevel(logging.INFO)

    # GitHub Actions format
    formatter = logging.Formatter('%(message)s')
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Disable third-party noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    return logger


def get_github_env_vars() -> Dict[str, Optional[str]]:
    """Get GitHub Actions environment variables."""
    github_env_vars = [
        "GITHUB_WORKSPACE",
        "GITHUB_REPOSITORY",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_EVENT_NAME",
        "GITHUB_ACTOR",
        "GITHUB_TOKEN",
        "GITHUB_BASE_REF",
        "GITHUB_HEAD_REF",
        "GITHUB_ACTIONS"
    ]

    return {var: os.getenv(var) for var in github_env_vars}


def validate_github_actions_environment() -> Dict[str, str]:
    """Validate and return GitHub Actions environment variables."""
    github_env = get_github_env_vars()
    return {k: v for k, v in github_env.items() if v is not None}


def setup_github_actions_environment() -> None:
    """Setup GitHub Actions specific environment variables."""
    workspace = os.getenv("GITHUB_WORKSPACE", ".")

    # Set GitHub Actions specific defaults
    if os.getenv("GITHUB_ACTIONS") == "true":
        # Use GitHub workspace as repository path
        if os.getenv("GITHUB_WORKSPACE"):
            os.environ.setdefault("BREAKING_CHANGES_REPO_PATH", os.getenv("GITHUB_WORKSPACE"))

        # Set git references for PR context
        if os.getenv("GITHUB_BASE_REF"):
            os.environ.setdefault("BREAKING_CHANGES_BASE_REF", f"origin/{os.getenv('GITHUB_BASE_REF')}")

        if os.getenv("GITHUB_SHA"):
            os.environ.setdefault("BREAKING_CHANGES_HEAD_REF", os.getenv("GITHUB_SHA"))

    # Set default output paths
    if not os.getenv("BREAKING_CHANGES_JSON_OUTPUT"):
        os.environ["BREAKING_CHANGES_JSON_OUTPUT"] = os.path.join(workspace, "breaking-changes.json")

    if not os.getenv("BREAKING_CHANGES_MARKDOWN_OUTPUT"):
        os.environ["BREAKING_CHANGES_MARKDOWN_OUTPUT"] = os.path.join(workspace, "breaking-changes.md")


def set_github_action_outputs(exit_code: int, breaking_changes_found: bool) -> None:
    """Set GitHub Actions outputs."""
    github_output = os.getenv('GITHUB_OUTPUT')
    if not github_output:
        return

    try:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"breaking-changes-detected={str(breaking_changes_found).lower()}\n")
            f.write(f"exit-code={exit_code}\n")

            # Output file paths if they exist
            json_output = os.getenv("BREAKING_CHANGES_JSON_OUTPUT")
            if json_output and os.path.exists(json_output):
                f.write(f"json-report={json_output}\n")

            markdown_output = os.getenv("BREAKING_CHANGES_MARKDOWN_OUTPUT")
            if markdown_output and os.path.exists(markdown_output):
                f.write(f"markdown-report={markdown_output}\n")
    except Exception as e:
        print(f"Warning: Could not set GitHub Actions outputs: {e}", file=sys.stderr)

    # Also set as environment variables for step outputs (legacy support)
    print(f"::set-output name=breaking-changes-detected::{str(breaking_changes_found).lower()}")
    print(f"::set-output name=exit-code::{exit_code}")


def create_github_action_summary(exit_code: int, markdown_output_path: Optional[str] = None) -> None:
    """Create GitHub Actions job summary."""
    github_step_summary = os.getenv('GITHUB_STEP_SUMMARY')
    if not github_step_summary:
        return

    # Build summary content
    summary_content = "# Breaking Changes Detection Report\n\n"

    if exit_code == 0:
        summary_content += "✅ **No breaking changes detected**\n\n"
    elif exit_code == 1:
        summary_content += "⚠️ **Breaking changes detected**\n\n"

        # Include markdown report if available
        if markdown_output_path and Path(markdown_output_path).exists():
            try:
                with open(markdown_output_path, encoding='utf-8') as f:
                    summary_content += f.read()
            except Exception as e:
                summary_content += f"❌ Could not read report: {e}\n"
    else:
        summary_content += "❌ **Error occurred during analysis**\n\n"

    # Write to GitHub step summary
    try:
        with open(github_step_summary, 'w', encoding='utf-8') as f:
            f.write(summary_content)
    except Exception as e:
        print(f"Warning: Could not create job summary: {e}", file=sys.stderr)


def print_github_actions_summary() -> None:
    """Print GitHub Actions environment summary."""
    github_env = validate_github_actions_environment()

    if github_env:
        print("🔧 GitHub Actions Environment Detected:")
        for key, value in github_env.items():
            if key == "GITHUB_TOKEN":
                value = "***" if value else "not set"
            print(f"   {key}: {value}")
        print()


def is_github_actions() -> bool:
    """Check if running in GitHub Actions environment."""
    return os.getenv("GITHUB_ACTIONS") == "true"


def get_workspace_path() -> str:
    """Get the GitHub Actions workspace path or current directory."""
    return os.getenv("GITHUB_WORKSPACE", ".")


def get_git_refs() -> Tuple[str, str]:
    """Get base and head git references for GitHub Actions."""
    base_ref = os.getenv("BREAKING_CHANGES_BASE_REF") or os.getenv("GITHUB_BASE_REF", "origin/main")
    head_ref = os.getenv("BREAKING_CHANGES_HEAD_REF") or os.getenv("GITHUB_SHA", "HEAD")

    # Ensure base_ref has origin prefix for PR context
    if os.getenv("GITHUB_BASE_REF") and not base_ref.startswith("origin/"):
        base_ref = f"origin/{base_ref}"

    return base_ref, head_ref
