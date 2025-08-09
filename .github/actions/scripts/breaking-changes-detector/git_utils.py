"""
Git Utilities Module

Centralized git command execution with proper error handling and logging.
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


class GitCommandRunner:
    """Centralized git command runner with error handling and logging."""

    def __init__(self, repo_path: Path, logger: logging.Logger):
        """
        Initialize git command runner.

        Args:
            repo_path: Path to the git repository
            logger: Logger instance for command output and errors

        Raises:
            ValueError: If the path is not a valid git repository
        """
        self.repo_path = repo_path
        self.logger = logger

        if not self._is_git_repository():
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def _is_git_repository(self) -> bool:
        """Check if the given path is a git repository."""
        try:
            self.run_command(['rev-parse', '--git-dir'])
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _validate_git_reference(self, ref: str) -> None:
        """
        Validate git reference to prevent command injection.

        Args:
            ref: Git reference to validate

        Raises:
            ValueError: If the reference contains invalid characters
        """
        if not ref:
            raise ValueError("Git reference cannot be empty")

        # Check for dangerous characters that could be used for command injection
        dangerous_chars = [';', '&', '|', '>', '<', '`', '$', '(', ')', '{', '}']
        if any(char in ref for char in dangerous_chars):
            raise ValueError(f"Git reference contains invalid characters: {ref}")

        # Check for common injection patterns
        injection_patterns = [
            r'\$\(',  # Command substitution $(...)
            r'`',     # Backticks for command substitution
            r'&&',    # Command chaining
            r'\|\|',  # Command chaining
            r';\s*',  # Command separation
        ]

        for pattern in injection_patterns:
            if re.search(pattern, ref):
                raise ValueError(f"Git reference contains potentially unsafe pattern: {ref}")

        # Allow only alphanumeric, hyphens, underscores, slashes, dots, and @ symbols
        if not re.match(r'^[a-zA-Z0-9._/@-]+$', ref):
            raise ValueError(f"Git reference contains invalid characters: {ref}")

    def run_command(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """
        Run a git command and return the result.

        Args:
            cmd: Git command arguments (without 'git' prefix)
            **kwargs: Additional arguments passed to subprocess.run

        Returns:
            CompletedProcess with stdout/stderr captured as text

        Raises:
            subprocess.CalledProcessError: If git command fails
            RuntimeError: If git is not installed or not found
        """
        full_cmd = ['git'] + cmd
        self.logger.debug(f"Running git command: {' '.join(full_cmd)}")

        try:
            result = subprocess.run(
                full_cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
                **kwargs
            )
            return result
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Git command failed: {' '.join(full_cmd)}")
            self.logger.error(f"Error output: {e.stderr}")
            raise
        except FileNotFoundError:
            raise RuntimeError("Git command not found. Please ensure git is installed.")

    def get_diff_files(self, base_ref: str, head_ref: str, diff_filter: str = "AMR") -> List[str]:
        """Get list of changed files between two refs."""
        self._validate_git_reference(base_ref)
        self._validate_git_reference(head_ref)

        result = self.run_command([
            'diff',
            '--name-status',
            f'--diff-filter={diff_filter}',
            base_ref,
            head_ref
        ])

        files = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                continue

            status = parts[0]
            file_path = parts[1]

            # Handle renamed files
            if status.startswith('R') and len(parts) >= 3:
                file_path = parts[2]  # New name for renamed files

            files.append(file_path)

        return files

    def get_file_content(self, file_path: str, ref: str) -> str:
        """Get file content at a specific git reference."""
        self._validate_git_reference(ref)

        try:
            result = self.run_command(['show', f'{ref}:{file_path}'])
            return result.stdout
        except subprocess.CalledProcessError as e:
            if "does not exist" in e.stderr or "exists on disk, but not in" in e.stderr:
                return ""
            raise

    def get_diff_stats(self, file_path: str, base_ref: str, head_ref: str) -> Tuple[int, int]:
        """Get diff statistics for a file (additions, deletions)."""
        self._validate_git_reference(base_ref)
        self._validate_git_reference(head_ref)

        try:
            result = self.run_command([
                'diff',
                '--numstat',
                base_ref,
                head_ref,
                '--',
                file_path
            ])

            if not result.stdout.strip():
                return 0, 0

            stats_line = result.stdout.strip().split('\n')[0]
            stats_parts = stats_line.split('\t')

            if len(stats_parts) >= 2 and stats_parts[0] != '-' and stats_parts[1] != '-':
                return int(stats_parts[0]), int(stats_parts[1])

            return 0, 0
        except subprocess.CalledProcessError:
            return 0, 0

    def get_diff_content(self, file_path: str, base_ref: str, head_ref: str, context_lines: int = 3) -> str:
        """Get diff content for a file."""
        self._validate_git_reference(base_ref)
        self._validate_git_reference(head_ref)

        result = self.run_command([
            'diff',
            f'-U{context_lines}',
            base_ref,
            head_ref,
            '--',
            file_path
        ])
        return result.stdout

    def validate_reference(self, ref: str) -> bool:
        """Validate that a git reference exists."""
        try:
            self._validate_git_reference(ref)
            self.run_command(['rev-parse', '--verify', ref])
            return True
        except (subprocess.CalledProcessError, ValueError):
            return False

    def get_commit_hash(self, ref: str) -> str:
        """Get the commit hash for a reference."""
        self._validate_git_reference(ref)
        result = self.run_command(['rev-parse', ref])
        return result.stdout.strip()

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = self.run_command(['branch', '--show-current'])
        return result.stdout.strip()

    def get_remote_url(self, remote: str = 'origin') -> Optional[str]:
        """Get remote URL, returns None if not found."""
        try:
            result = self.run_command(['remote', 'get-url', remote])
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
