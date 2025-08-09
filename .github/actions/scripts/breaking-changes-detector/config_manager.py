"""
Configuration Management Module

Handles configuration from command line arguments, environment variables,
and config files with proper validation and defaults.
"""

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import shared GitHub Actions utilities
from github_actions_utils import is_github_actions


@dataclass
class ConfigManager:
    """Configuration manager for breaking changes detector."""

    # Git configuration
    base_ref: str = "origin/main"
    head_ref: str = "HEAD"
    repository_path: str = "."

    # Analysis configuration
    ignore_unused: bool = False
    include_patterns: List[str] = field(default_factory=lambda: ["**/*.py"])
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "**/test_*.py",
        "**/tests/**/*.py",
        "**/__pycache__/**",
        "**/.*/**",
        "**/venv/**",
        "**/env/**",
        "**/.venv/**",
        "**/site-packages/**",
        "**/node_modules/**"
    ])

    # Output configuration
    json_output: Optional[str] = None
    markdown_output: Optional[str] = None
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # GitHub Actions specific
    github_token: Optional[str] = None
    fail_on_breaking: bool = True

    # Advanced configuration
    max_usage_search_files: int = 10000
    max_context_lines: int = 5
    enable_ast_analysis: bool = True
    enable_regex_analysis: bool = True

    @classmethod
    def from_args_and_env(cls, args: argparse.Namespace) -> 'ConfigManager':
        """Create configuration from command line arguments and environment variables."""

        # Start with defaults
        config = cls()

        # Override with environment variables first
        config._load_from_environment()

        # Override with command line arguments
        config._load_from_args(args)

        # Validate configuration
        config._validate()

        return config

    def _get_bool_env(self, env_var: str, default: bool) -> bool:
        """
        Parse boolean environment variable with proper handling of various true/false values.

        Args:
            env_var: Environment variable name to check
            default: Default value if environment variable is not set

        Returns:
            True if env var value is 'true', '1', 'yes', or 'on' (case insensitive)
            False for all other values, or default if env var is not set
        """
        value = os.getenv(env_var)
        if value is None:
            return default
        return value.lower() in ["true", "1", "yes", "on"]

    def _load_from_environment(self) -> None:
        """Load configuration from environment variables."""

        # Git configuration
        self.base_ref = os.getenv("BREAKING_CHANGES_BASE_REF", self.base_ref)
        self.head_ref = os.getenv("BREAKING_CHANGES_HEAD_REF", self.head_ref)
        self.repository_path = os.getenv("BREAKING_CHANGES_REPO_PATH", self.repository_path)

        # Analysis configuration
        self.ignore_unused = self._get_bool_env("BREAKING_CHANGES_IGNORE_UNUSED", self.ignore_unused)

        # Include/exclude patterns from environment
        include_env = os.getenv("BREAKING_CHANGES_INCLUDE_PATTERNS")
        if include_env:
            self.include_patterns = [p.strip() for p in include_env.split(",") if p.strip()]

        exclude_env = os.getenv("BREAKING_CHANGES_EXCLUDE_PATTERNS")
        if exclude_env:
            self.exclude_patterns = [p.strip() for p in exclude_env.split(",") if p.strip()]

        # Output configuration
        self.json_output = os.getenv("BREAKING_CHANGES_JSON_OUTPUT", self.json_output)
        self.markdown_output = os.getenv("BREAKING_CHANGES_MARKDOWN_OUTPUT", self.markdown_output)
        self.log_level = os.getenv("BREAKING_CHANGES_LOG_LEVEL", self.log_level)
        self.log_file = os.getenv("BREAKING_CHANGES_LOG_FILE", self.log_file)

        # GitHub Actions specific
        self.github_token = os.getenv("GITHUB_TOKEN", os.getenv("BREAKING_CHANGES_GITHUB_TOKEN", self.github_token))
        self.fail_on_breaking = self._get_bool_env("BREAKING_CHANGES_FAIL_ON_BREAKING", self.fail_on_breaking)

        # Advanced configuration
        max_files_env = os.getenv("BREAKING_CHANGES_MAX_SEARCH_FILES")
        if max_files_env and max_files_env.isdigit():
            self.max_usage_search_files = int(max_files_env)

        max_context_env = os.getenv("BREAKING_CHANGES_MAX_CONTEXT_LINES")
        if max_context_env and max_context_env.isdigit():
            self.max_context_lines = int(max_context_env)

        # Analysis toggles
        self.enable_ast_analysis = self._get_bool_env("BREAKING_CHANGES_ENABLE_AST", self.enable_ast_analysis)
        self.enable_regex_analysis = self._get_bool_env("BREAKING_CHANGES_ENABLE_REGEX", self.enable_regex_analysis)

    def _load_from_args(self, args: argparse.Namespace) -> None:
        """Load configuration from command line arguments."""

        # Git configuration
        if hasattr(args, 'base_ref') and args.base_ref:
            self.base_ref = args.base_ref
        if hasattr(args, 'head_ref') and args.head_ref:
            self.head_ref = args.head_ref
        if hasattr(args, 'repository_path') and args.repository_path:
            self.repository_path = args.repository_path

        # Analysis configuration
        if hasattr(args, 'ignore_unused') and args.ignore_unused is not None:
            self.ignore_unused = args.ignore_unused

        if hasattr(args, 'include_patterns') and args.include_patterns:
            self.include_patterns = args.include_patterns
        if hasattr(args, 'exclude_patterns') and args.exclude_patterns:
            self.exclude_patterns = args.exclude_patterns

        # Output configuration
        if hasattr(args, 'json_output') and args.json_output:
            self.json_output = args.json_output
        if hasattr(args, 'markdown_output') and args.markdown_output:
            self.markdown_output = args.markdown_output
        if hasattr(args, 'log_level') and args.log_level:
            self.log_level = args.log_level
        if hasattr(args, 'log_file') and args.log_file:
            self.log_file = args.log_file

        # GitHub Actions specific
        if hasattr(args, 'github_token') and args.github_token:
            self.github_token = args.github_token
        if hasattr(args, 'fail_on_breaking') and args.fail_on_breaking is not None:
            self.fail_on_breaking = args.fail_on_breaking

    def _validate(self) -> None:
        """Validate configuration values."""

        # Validate log level
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_log_levels:
            raise ValueError(f"Invalid log level: {self.log_level}. Must be one of: {valid_log_levels}")

        # Validate repository path
        repo_path = Path(self.repository_path).resolve()
        if not repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")

        # Validate numeric values
        if self.max_usage_search_files <= 0:
            raise ValueError("max_usage_search_files must be positive")

        if self.max_context_lines < 0:
            raise ValueError("max_context_lines must be non-negative")

        # Validate include patterns (at least one required)
        if not self.include_patterns:
            raise ValueError("At least one include pattern is required")

        # Validate output paths if specified
        if self.json_output:
            json_path = Path(self.json_output)
            try:
                json_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"Cannot create directory for JSON output: {e}")

        if self.markdown_output:
            md_path = Path(self.markdown_output)
            try:
                md_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"Cannot create directory for Markdown output: {e}")

        if self.log_file:
            log_path = Path(self.log_file)
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"Cannot create directory for log file: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "git": {
                "base_ref": self.base_ref,
                "head_ref": self.head_ref,
                "repository_path": self.repository_path
            },
            "analysis": {
                "ignore_unused": self.ignore_unused,
                "include_patterns": self.include_patterns,
                "exclude_patterns": self.exclude_patterns,
                "max_usage_search_files": self.max_usage_search_files,
                "max_context_lines": self.max_context_lines,
                "enable_ast_analysis": self.enable_ast_analysis,
                "enable_regex_analysis": self.enable_regex_analysis
            },
            "output": {
                "json_output": self.json_output,
                "markdown_output": self.markdown_output,
                "log_level": self.log_level,
                "log_file": self.log_file
            },
            "github_actions": {
                "github_token": "***" if self.github_token else None,
                "fail_on_breaking": self.fail_on_breaking
            }
        }

    def get_environment_template(self) -> str:
        """Get template for environment variables."""
        return """
# Breaking Changes Detector Environment Variables

# Git Configuration
BREAKING_CHANGES_BASE_REF=origin/main
BREAKING_CHANGES_HEAD_REF=HEAD
BREAKING_CHANGES_REPO_PATH=.

# Analysis Configuration
BREAKING_CHANGES_IGNORE_UNUSED=false
BREAKING_CHANGES_INCLUDE_PATTERNS="**/*.py"
BREAKING_CHANGES_EXCLUDE_PATTERNS="**/test_*.py,**/tests/**/*.py,**/__pycache__/**"

# Output Configuration
BREAKING_CHANGES_JSON_OUTPUT=
BREAKING_CHANGES_MARKDOWN_OUTPUT=
BREAKING_CHANGES_LOG_LEVEL=INFO
BREAKING_CHANGES_LOG_FILE=

# GitHub Actions
GITHUB_TOKEN=
BREAKING_CHANGES_FAIL_ON_BREAKING=true

# Advanced Configuration
BREAKING_CHANGES_MAX_SEARCH_FILES=10000
BREAKING_CHANGES_MAX_CONTEXT_LINES=5
BREAKING_CHANGES_ENABLE_AST=true
BREAKING_CHANGES_ENABLE_REGEX=true
        """.strip()

    def __str__(self) -> str:
        """String representation of configuration."""
        config_dict = self.to_dict()
        lines = []

        for section, values in config_dict.items():
            lines.append(f"[{section.upper()}]")
            for key, value in values.items():
                if isinstance(value, list):
                    value_str = ", ".join(value)
                else:
                    value_str = str(value)
                lines.append(f"  {key}: {value_str}")
            lines.append("")

        return "\n".join(lines)


def load_config_from_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from a YAML or JSON file (if needed in future)."""
    # This is a placeholder for future file-based configuration support
    # For now, we use environment variables and command line arguments
    config_file = Path(config_path)

    if not config_file.exists():
        return {}

    # Future implementation could support YAML/JSON config files
    # import yaml
    # with open(config_file, 'r') as f:
    #     return yaml.safe_load(f)

    return {}


def create_default_config_file(output_path: str) -> None:
    """Create a default configuration file."""
    config = ConfigManager()

    config_content = f"""# Breaking Changes Detector Configuration
# This file contains default configuration values
# Environment variables and command line arguments will override these values

# Git Configuration
base_ref: {config.base_ref}
head_ref: {config.head_ref}
repository_path: {config.repository_path}

# Analysis Configuration
ignore_unused: {config.ignore_unused}
include_patterns:
{chr(10).join(f"  - {pattern}" for pattern in config.include_patterns)}
exclude_patterns:
{chr(10).join(f"  - {pattern}" for pattern in config.exclude_patterns)}

# Output Configuration
json_output: {config.json_output or "null"}
markdown_output: {config.markdown_output or "null"}
log_level: {config.log_level}
log_file: {config.log_file or "null"}

# GitHub Actions
fail_on_breaking: {config.fail_on_breaking}

# Advanced Configuration
max_usage_search_files: {config.max_usage_search_files}
max_context_lines: {config.max_context_lines}
enable_ast_analysis: {config.enable_ast_analysis}
enable_regex_analysis: {config.enable_regex_analysis}
"""

    with open(output_path, 'w') as f:
        f.write(config_content)


def setup_github_actions_defaults(config: ConfigManager) -> ConfigManager:
    """Setup defaults specifically for GitHub Actions environment."""

    # Check if we're running in GitHub Actions
    if is_github_actions():

        # Use GitHub workspace as repository path if available
        workspace = os.getenv("GITHUB_WORKSPACE")
        if workspace:
            config.repository_path = workspace

        # Set default base ref to the target branch in PR
        github_base_ref = os.getenv("GITHUB_BASE_REF")
        if github_base_ref:
            config.base_ref = f"origin/{github_base_ref}"

        # Set head ref to the current SHA
        github_sha = os.getenv("GITHUB_SHA")
        if github_sha:
            config.head_ref = github_sha

        # Enable GitHub-specific output formats
        if not config.json_output:
            config.json_output = os.path.join(os.getenv("GITHUB_WORKSPACE", "."), "breaking-changes.json")

        if not config.markdown_output:
            config.markdown_output = os.path.join(os.getenv("GITHUB_WORKSPACE", "."), "breaking-changes.md")

    return config
