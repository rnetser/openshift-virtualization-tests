"""
Custom Exception Classes

Defines custom exceptions for the breaking changes detector with proper
error handling and recovery strategies.
"""

import subprocess
from typing import Any, Dict, Optional


class BreakingChangesDetectorError(Exception):
    """Base exception for all breaking changes detector errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


class GitAnalysisError(BreakingChangesDetectorError):
    """Raised when git analysis fails."""
    pass


class GitRepositoryError(GitAnalysisError):
    """Raised when there are issues with the git repository."""
    pass


class GitReferenceError(GitAnalysisError):
    """Raised when git references are invalid."""
    pass


class ASTAnalysisError(BreakingChangesDetectorError):
    """Raised when AST analysis fails."""
    pass


class SyntaxAnalysisError(ASTAnalysisError):
    """Raised when there are syntax errors in analyzed files."""
    pass


class UsageDetectionError(BreakingChangesDetectorError):
    """Raised when usage detection fails."""
    pass


class ConfigurationError(BreakingChangesDetectorError):
    """Raised when configuration is invalid."""
    pass


class ReportGenerationError(BreakingChangesDetectorError):
    """Raised when report generation fails."""
    pass


class FileAccessError(BreakingChangesDetectorError):
    """Raised when file access operations fail."""
    pass


class DependencyError(BreakingChangesDetectorError):
    """Raised when required dependencies are missing."""
    pass


def handle_git_errors(func):
    """Decorator to handle common git errors."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except subprocess.CalledProcessError as e:
            if "not a git repository" in e.stderr.lower():
                raise GitRepositoryError(
                    "Not a git repository",
                    {"path": kwargs.get('cwd', args[0] if args else 'unknown')}
                )
            elif "unknown revision" in e.stderr.lower():
                raise GitReferenceError(
                    "Invalid git reference",
                    {"stderr": e.stderr}
                )
            else:
                raise GitAnalysisError(
                    f"Git command failed: {e.stderr}",
                    {"command": e.cmd, "returncode": e.returncode}
                )
        except FileNotFoundError:
            raise DependencyError(
                "Git command not found. Please ensure git is installed.",
                {"command": "git"}
            )
    return wrapper


def handle_file_errors(func):
    """Decorator to handle common file access errors."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            raise FileAccessError(
                f"File not found: {e.filename}",
                {"filename": e.filename}
            )
        except PermissionError as e:
            raise FileAccessError(
                f"Permission denied: {e.filename}",
                {"filename": e.filename}
            )
        except IsADirectoryError as e:
            raise FileAccessError(
                f"Expected file, got directory: {e.filename}",
                {"filename": e.filename}
            )
        except OSError as e:
            raise FileAccessError(
                f"OS error accessing file: {e}",
                {"errno": e.errno}
            )
    return wrapper


def handle_ast_errors(func):
    """Decorator to handle AST parsing errors."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SyntaxError as e:
            raise SyntaxAnalysisError(
                f"Syntax error in Python file: {e.msg}",
                {
                    "filename": e.filename,
                    "lineno": e.lineno,
                    "offset": e.offset,
                    "text": e.text
                }
            )
        except ValueError as e:
            raise ASTAnalysisError(
                f"AST analysis error: {e}",
                {"original_error": str(e)}
            )
    return wrapper
