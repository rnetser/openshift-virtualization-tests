#!/usr/bin/env python3
"""
GitHub Actions Breaking Changes Detector

A comprehensive tool for detecting potential breaking changes in Python codebases
through git diffs and AST analysis.
"""

import argparse
import logging
import sys
from typing import Dict, List

from ast_analyzer import ASTAnalyzer
from breaking_changes_types import AnalysisResult, BreakingChange, UsageLocation
from config_manager import ConfigManager

# Import modules
from git_analyzer import GitAnalyzer
from report_generator import ReportGenerator
from usage_detector import UsageDetector


class BreakingChangesDetector:
    """Main class for detecting breaking changes."""

    def __init__(self, config: ConfigManager):
        """Initialize the detector with configuration."""
        self.config = config
        self.logger = self._setup_logging()

        # Initialize analyzers
        self.git_analyzer = GitAnalyzer(config, self.logger)
        self.ast_analyzer = ASTAnalyzer(config, self.logger)
        self.usage_detector = UsageDetector(config, self.logger)
        self.report_generator = ReportGenerator(config, self.logger)

    def _setup_logging(self) -> logging.Logger:
        """Set up logging configuration."""
        logger = logging.getLogger(__name__)

        # Clear any existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Set log level
        log_level = getattr(logging, self.config.log_level.upper())
        logger.setLevel(log_level)

        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler if specified
        if self.config.log_file:
            file_handler = logging.FileHandler(self.config.log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger

    def analyze(self) -> AnalysisResult:
        """Perform complete breaking changes analysis."""
        try:
            self.logger.info("Starting breaking changes analysis")

            # Step 1: Get changed files from git
            self.logger.info("Analyzing git changes...")
            changed_files = self.git_analyzer.get_changed_files()

            if not changed_files:
                self.logger.info("No Python files changed, no analysis needed")
                return AnalysisResult(
                    breaking_changes=[],
                    usage_locations={},
                    total_files_analyzed=0,
                    total_changes_detected=0,
                    exit_code=0
                )

            self.logger.info(f"Found {len(changed_files)} changed Python files")

            # Step 2: Analyze AST changes for each file
            self.logger.info("Analyzing AST changes...")
            all_breaking_changes = []

            for file_path in changed_files:
                try:
                    changes = self.ast_analyzer.analyze_file_changes(file_path)
                    all_breaking_changes.extend(changes)
                except Exception as e:
                    self.logger.error(f"Error analyzing {file_path}: {e}")
                    continue

            self.logger.info(f"Detected {len(all_breaking_changes)} potential breaking changes")

            # Step 3: Find usage patterns for changed elements
            self.logger.info("Detecting usage patterns...")
            usage_locations = {}

            for change in all_breaking_changes:
                try:
                    locations = self.usage_detector.find_usage_locations(
                        change.element_name,
                        change.file_path
                    )
                    if locations:
                        key = f"{change.file_path}:{change.element_name}"
                        usage_locations[key] = locations
                except Exception as e:
                    self.logger.error(f"Error detecting usage for {change.element_name}: {e}")
                    continue

            # Step 4: Determine exit code
            exit_code = self._determine_exit_code(all_breaking_changes, usage_locations)

            result = AnalysisResult(
                breaking_changes=all_breaking_changes,
                usage_locations=usage_locations,
                total_files_analyzed=len(changed_files),
                total_changes_detected=len(all_breaking_changes),
                exit_code=exit_code
            )

            self.logger.info("Analysis completed successfully")
            return result

        except Exception as e:
            self.logger.error(f"Critical error during analysis: {e}")
            return AnalysisResult(
                breaking_changes=[],
                usage_locations={},
                total_files_analyzed=0,
                total_changes_detected=0,
                exit_code=2  # Critical error
            )

    def _determine_exit_code(self, changes: List[BreakingChange],
                           usage_locations: Dict[str, List[UsageLocation]]) -> int:
        """Determine appropriate exit code based on findings."""
        if not changes:
            return 0  # No breaking changes

        # Check if any breaking changes have actual usage
        has_used_breaking_changes = any(
            f"{change.file_path}:{change.element_name}" in usage_locations
            for change in changes
        )

        if has_used_breaking_changes:
            # Check severity
            critical_changes = [c for c in changes if c.severity == "critical"]
            high_changes = [c for c in changes if c.severity == "high"]

            if critical_changes:
                return 1  # Critical breaking changes found
            elif high_changes:
                return 1  # High severity breaking changes found
            else:
                return 1 if not self.config.ignore_unused else 0

        # Breaking changes found but no usage detected
        return 1 if not self.config.ignore_unused else 0

    def generate_reports(self, result: AnalysisResult) -> None:
        """Generate all requested report formats."""
        try:
            self.logger.info("Generating reports...")

            # Console report (always generated)
            self.report_generator.generate_console_report(result)

            # JSON report
            if self.config.json_output:
                self.report_generator.generate_json_report(result, self.config.json_output)

            # Markdown report
            if self.config.markdown_output:
                self.report_generator.generate_markdown_report(result, self.config.markdown_output)

            self.logger.info("Reports generated successfully")

        except Exception as e:
            self.logger.error(f"Error generating reports: {e}")


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        description="Detect breaking changes in Python code for GitHub Actions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python breaking_changes_detector.py

  # Specify git range
  python breaking_changes_detector.py --base-ref origin/main --head-ref HEAD

  # Generate reports
  python breaking_changes_detector.py --json-output changes.json --markdown-output report.md

  # Configure via environment variables
  export BREAKING_CHANGES_BASE_REF=origin/main
  export BREAKING_CHANGES_LOG_LEVEL=DEBUG
  python breaking_changes_detector.py
        """
    )

    # Git configuration
    git_group = parser.add_argument_group('Git Configuration')
    git_group.add_argument(
        '--base-ref',
        default='origin/main',
        help='Base git reference for comparison (default: origin/main)'
    )
    git_group.add_argument(
        '--head-ref',
        default='HEAD',
        help='Head git reference for comparison (default: HEAD)'
    )
    git_group.add_argument(
        '--repository-path',
        default='.',
        help='Path to git repository (default: current directory)'
    )

    # Analysis configuration
    analysis_group = parser.add_argument_group('Analysis Configuration')
    analysis_group.add_argument(
        '--ignore-unused',
        action='store_true',
        help='Ignore breaking changes that have no detected usage'
    )
    analysis_group.add_argument(
        '--include-patterns',
        nargs='*',
        default=['**/*.py'],
        help='File patterns to include in analysis (default: **/*.py)'
    )
    analysis_group.add_argument(
        '--exclude-patterns',
        nargs='*',
        default=['**/test_*.py', '**/tests/**/*.py', '**/__pycache__/**'],
        help='File patterns to exclude from analysis'
    )

    # Output configuration
    output_group = parser.add_argument_group('Output Configuration')
    output_group.add_argument(
        '--json-output',
        help='Path to JSON output file'
    )
    output_group.add_argument(
        '--markdown-output',
        help='Path to Markdown output file'
    )
    output_group.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Logging level (default: INFO)'
    )
    output_group.add_argument(
        '--log-file',
        help='Path to log file (default: console only)'
    )

    # GitHub Actions specific
    actions_group = parser.add_argument_group('GitHub Actions')
    actions_group.add_argument(
        '--github-token',
        help='GitHub token for API access (can also use GITHUB_TOKEN env var)'
    )
    actions_group.add_argument(
        '--fail-on-breaking',
        action='store_true',
        default=True,
        help='Fail (exit 1) when breaking changes are detected (default: True)'
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_argument_parser()
    args = parser.parse_args()

    try:
        # Initialize configuration
        config = ConfigManager.from_args_and_env(args)

        # Create detector
        detector = BreakingChangesDetector(config)

        # Run analysis
        result = detector.analyze()

        # Generate reports
        detector.generate_reports(result)

        # Return appropriate exit code
        return result.exit_code if config.fail_on_breaking else 0

    except KeyboardInterrupt:
        print("\nAnalysis interrupted by user", file=sys.stderr)
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 2  # General error


if __name__ == "__main__":
    sys.exit(main())
