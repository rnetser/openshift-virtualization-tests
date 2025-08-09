"""
Git Analysis Module

Handles git diff analysis to identify changed files and their modifications.
"""

import fnmatch
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from config_manager import ConfigManager
from git_utils import GitCommandRunner


@dataclass
class GitDiffInfo:
    """Information about a file change from git diff."""
    file_path: str
    change_type: str  # A=added, M=modified, D=deleted, R=renamed
    old_path: Optional[str] = None  # For renamed files
    additions: int = 0
    deletions: int = 0


@dataclass
class FileChange:
    """Detailed information about changes in a specific file."""
    file_path: str
    old_content: str
    new_content: str
    diff_hunks: List[Dict[str, any]]


class GitAnalyzer:
    """Analyzes git repository changes to identify modified Python files."""

    def __init__(self, config: ConfigManager, logger: logging.Logger):
        """Initialize git analyzer."""
        self.config = config
        self.logger = logger
        self.repo_path = Path(config.repository_path).resolve()
        self.git_runner = GitCommandRunner(self.repo_path, logger)

    def get_changed_files(self) -> List[str]:
        """Get list of changed Python files between base and head refs."""
        try:
            all_changed_files = self.git_runner.get_diff_files(
                self.config.base_ref,
                self.config.head_ref,
                "AMR"  # Added, Modified, Renamed
            )

            changed_files = []
            for file_path in all_changed_files:
                if self._is_python_file(file_path) and self._should_include_file(file_path):
                    changed_files.append(file_path)
                    self.logger.debug(f"Included changed file: {file_path}")
                else:
                    self.logger.debug(f"Excluded changed file: {file_path}")

            self.logger.info(f"Found {len(changed_files)} changed Python files")
            return changed_files

        except Exception as e:
            if "unknown revision" in str(e).lower():
                self.logger.error(f"Unknown git revision: {self.config.base_ref} or {self.config.head_ref}")
                raise ValueError(f"Invalid git references: {self.config.base_ref}..{self.config.head_ref}")
            raise

    def get_file_diff_info(self, file_path: str) -> GitDiffInfo:
        """Get detailed diff information for a specific file."""
        try:
            # Get file status from diff
            self.git_runner.get_diff_files(
                self.config.base_ref,
                self.config.head_ref
            )

            # Find the specific file and its status
            status = "M"  # Default to modified
            old_path = None

            # Get diff stats
            additions, deletions = self.git_runner.get_diff_stats(
                file_path,
                self.config.base_ref,
                self.config.head_ref
            )

            return GitDiffInfo(
                file_path=file_path,
                change_type=status,
                old_path=old_path,
                additions=additions,
                deletions=deletions
            )

        except Exception as e:
            self.logger.error(f"Failed to get diff info for {file_path}: {e}")
            raise

    def get_file_content(self, file_path: str, ref: str) -> str:
        """Get file content at a specific git reference."""
        try:
            return self.git_runner.get_file_content(file_path, ref)
        except Exception as e:
            self.logger.error(f"Failed to get content for {file_path} at {ref}: {e}")
            raise

    def get_file_changes(self, file_path: str) -> FileChange:
        """Get detailed changes for a file including old and new content."""
        try:
            # Get old and new content
            old_content = self.get_file_content(file_path, self.config.base_ref)
            new_content = self.get_file_content(file_path, self.config.head_ref)

            # Get diff hunks
            diff_hunks = self._parse_diff_hunks(file_path)

            return FileChange(
                file_path=file_path,
                old_content=old_content,
                new_content=new_content,
                diff_hunks=diff_hunks
            )

        except Exception as e:
            self.logger.error(f"Failed to get changes for {file_path}: {e}")
            raise

    def _parse_diff_hunks(self, file_path: str) -> List[Dict[str, any]]:
        """Parse diff hunks to extract detailed change information."""
        try:
            diff_content = self.git_runner.get_diff_content(
                file_path,
                self.config.base_ref,
                self.config.head_ref,
                context_lines=3
            )

            hunks = []
            current_hunk = None

            for line in diff_content.split('\n'):
                # Parse hunk header
                if line.startswith('@@'):
                    if current_hunk:
                        hunks.append(current_hunk)

                    # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
                    hunk_match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                    if hunk_match:
                        old_start = int(hunk_match.group(1))
                        old_count = int(hunk_match.group(2) or 1)
                        new_start = int(hunk_match.group(3))
                        new_count = int(hunk_match.group(4) or 1)

                        current_hunk = {
                            'old_start': old_start,
                            'old_count': old_count,
                            'new_start': new_start,
                            'new_count': new_count,
                            'lines': []
                        }

                # Add line to current hunk
                elif current_hunk is not None:
                    if line.startswith('+'):
                        current_hunk['lines'].append({
                            'type': 'addition',
                            'content': line[1:],
                            'line_number': None  # Will be calculated
                        })
                    elif line.startswith('-'):
                        current_hunk['lines'].append({
                            'type': 'deletion',
                            'content': line[1:],
                            'line_number': None  # Will be calculated
                        })
                    elif line.startswith(' '):
                        current_hunk['lines'].append({
                            'type': 'context',
                            'content': line[1:],
                            'line_number': None  # Will be calculated
                        })

            # Add the last hunk
            if current_hunk:
                hunks.append(current_hunk)

            return hunks

        except Exception as e:
            self.logger.warning(f"Failed to parse diff hunks for {file_path}: {e}")
            return []

    def _is_python_file(self, file_path: str) -> bool:
        """Check if a file is a Python file."""
        path = Path(file_path)
        return path.suffix in ['.py', '.pyi']

    def _should_include_file(self, file_path: str) -> bool:
        """Check if a file should be included based on include/exclude patterns."""
        # Check exclude patterns first
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return False

        # Check include patterns
        for pattern in self.config.include_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return True

        return False

    def get_repository_info(self) -> Dict[str, str]:
        """Get basic repository information."""
        try:
            current_branch = self.git_runner.get_current_branch()
            remote_url = self.git_runner.get_remote_url() or "unknown"
            base_commit = self.git_runner.get_commit_hash(self.config.base_ref)
            head_commit = self.git_runner.get_commit_hash(self.config.head_ref)

            return {
                'current_branch': current_branch,
                'remote_url': remote_url,
                'base_ref': self.config.base_ref,
                'head_ref': self.config.head_ref,
                'base_commit': base_commit,
                'head_commit': head_commit,
                'repository_path': str(self.repo_path)
            }

        except Exception as e:
            self.logger.warning(f"Failed to get repository info: {e}")
            return {
                'repository_path': str(self.repo_path),
                'base_ref': self.config.base_ref,
                'head_ref': self.config.head_ref
            }

    def validate_references(self) -> bool:
        """Validate that the git references exist."""
        try:
            base_valid = self.git_runner.validate_reference(self.config.base_ref)
            head_valid = self.git_runner.validate_reference(self.config.head_ref)
            return base_valid and head_valid
        except Exception as e:
            self.logger.error(f"Invalid git references: {e}")
            return False
