#!/usr/bin/env python3
"""
GitHub Actions Entry Point for Breaking Changes Detector

This script serves as the main entry point when running the breaking changes
detector in GitHub Actions environments. It handles GitHub-specific
environment variables and output formatting.
"""

import os
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from breaking_changes_detector import main as detector_main
from github_actions_utils import (
    create_github_action_summary,
    set_github_action_outputs,
    setup_github_actions_environment,
    setup_github_actions_logging,
    validate_github_actions_environment,
)


def main() -> int:
    """Main GitHub Actions entry point."""
    logger = setup_github_actions_logging()

    try:
        logger.info("🚀 Starting Breaking Changes Detection for GitHub Actions")

        # Validate GitHub Actions environment
        github_env = validate_github_actions_environment()
        logger.info(f"GitHub Actions Environment: {len(github_env)} variables detected")

        # Setup GitHub Actions environment
        setup_github_actions_environment()

        base_ref = os.getenv("BREAKING_CHANGES_BASE_REF", "origin/main")
        head_ref = os.getenv("BREAKING_CHANGES_HEAD_REF", "HEAD")
        logger.info(f"Base ref: {base_ref}")
        logger.info(f"Head ref: {head_ref}")

        logger.info("📊 Running breaking changes analysis...")

        # Run the main detector
        exit_code = detector_main()

        # Determine if breaking changes were found
        breaking_changes_found = exit_code == 1

        # Set GitHub Actions outputs
        set_github_action_outputs(exit_code, breaking_changes_found)

        # Create job summary
        try:
            markdown_output = os.getenv("BREAKING_CHANGES_MARKDOWN_OUTPUT")
            create_github_action_summary(exit_code, markdown_output)
        except Exception as e:
            logger.warning(f"Could not create job summary: {e}")

        # Log final status
        if exit_code == 0:
            logger.info("✅ No breaking changes detected")
        elif exit_code == 1:
            logger.info("⚠️ Breaking changes detected - see reports for details")
        else:
            logger.error("❌ Error occurred during analysis")

        logger.info("🏁 Breaking Changes Detection completed")
        return exit_code

    except Exception as e:
        logger.error(f"❌ Fatal error in GitHub Actions entry point: {e}")

        # Set error outputs
        set_github_action_outputs(2, False)

        return 2


if __name__ == "__main__":
    sys.exit(main())
