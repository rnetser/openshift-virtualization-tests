#!/usr/bin/env python3
"""
GitHub Actions Breaking Changes Detector - Main Entry Point

Optimized entry point for running in GitHub Actions with uv.
"""

import os
import sys
from pathlib import Path

# Add the current directory to the Python path for local imports
sys.path.insert(0, str(Path(__file__).parent))

from breaking_changes_detector import main as detector_main
from github_actions_utils import (
    is_github_actions,
    print_github_actions_summary,
    set_github_action_outputs,
    setup_github_actions_environment,
    setup_github_actions_logging,
)


def main() -> int:
    """Main entry point optimized for GitHub Actions."""

    try:
        # Setup GitHub Actions specific logging
        setup_github_actions_logging("main_breaking_changes")

        # Print environment summary in GitHub Actions
        if is_github_actions():
            print_github_actions_summary()

        # Setup GitHub Actions outputs and environment
        setup_github_actions_environment()

        print("🔍 Starting Breaking Changes Detection...")
        print(f"📂 Repository: {os.getenv('BREAKING_CHANGES_REPO_PATH', '.')}")
        print(f"🔀 Comparing: {os.getenv('BREAKING_CHANGES_BASE_REF', 'origin/main')} -> {os.getenv('BREAKING_CHANGES_HEAD_REF', 'HEAD')}")
        print()

        # Run the detector
        exit_code = detector_main()

        # Set GitHub Actions outputs
        breaking_changes_found = exit_code != 0
        set_github_action_outputs(exit_code, breaking_changes_found)

        # Print final status
        if exit_code == 0:
            print("\n✅ No breaking changes detected!")
        else:
            print(f"\n⚠️  Breaking changes detected (exit code: {exit_code})")

        return exit_code

    except KeyboardInterrupt:
        print("\n❌ Analysis interrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\n💥 Fatal error: {e}", file=sys.stderr)

        # Log full traceback in debug mode
        if os.getenv("BREAKING_CHANGES_LOG_LEVEL", "").upper() == "DEBUG":
            import traceback
            traceback.print_exc()

        return 2


if __name__ == "__main__":
    sys.exit(main())
