"""
Error Handling Module

Provides comprehensive error handling, logging, and recovery strategies
for the breaking changes detector.
"""

import logging
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

from exceptions import (
    ASTAnalysisError,
    BreakingChangesDetectorError,
    ConfigurationError,
    DependencyError,
    FileAccessError,
    GitAnalysisError,
    GitReferenceError,
    GitRepositoryError,
    ReportGenerationError,
    SyntaxAnalysisError,
    UsageDetectionError,
)

T = TypeVar('T')


class ErrorHandler:
    """Centralized error handling and logging."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.error_counts = {}
        self.recovery_strategies = {
            GitRepositoryError: self._handle_git_repository_error,
            GitReferenceError: self._handle_git_reference_error,
            SyntaxAnalysisError: self._handle_syntax_error,
            FileAccessError: self._handle_file_access_error,
            DependencyError: self._handle_dependency_error
        }

    def handle_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        Handle an error with appropriate logging and recovery.

        Returns:
            True if error was handled and execution can continue
            False if error is fatal and execution should stop
        """
        error_type = type(error).__name__
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

        # Log the error with context
        self._log_error(error, context)

        # Try recovery strategy if available
        if isinstance(error, tuple(self.recovery_strategies.keys())):
            for error_class, strategy in self.recovery_strategies.items():
                if isinstance(error, error_class):
                    try:
                        return strategy(error, context)
                    except Exception as recovery_error:
                        self.logger.error(f"Recovery strategy failed: {recovery_error}")
                        return False

        # Check if this is a known recoverable error
        if isinstance(error, (SyntaxAnalysisError, FileAccessError)):
            return True  # Can continue with other files

        # Fatal errors
        if isinstance(error, (GitRepositoryError, ConfigurationError, DependencyError)):
            return False

        # Unknown errors - log and continue
        return True

    def _log_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> None:
        """Log an error with appropriate level and context."""

        # Determine log level based on error type
        if isinstance(error, (GitRepositoryError, ConfigurationError, DependencyError)):
            log_level = logging.CRITICAL
        elif isinstance(error, (GitReferenceError, ASTAnalysisError, ReportGenerationError)):
            log_level = logging.ERROR
        elif isinstance(error, (SyntaxAnalysisError, FileAccessError, UsageDetectionError)):
            log_level = logging.WARNING
        else:
            log_level = logging.ERROR

        # Format error message
        error_msg = str(error)
        if hasattr(error, 'details') and error.details:
            details_str = ", ".join(f"{k}={v}" for k, v in error.details.items())
            error_msg = f"{error_msg} | Details: {details_str}"

        # Add context if provided
        if context:
            context_str = ", ".join(f"{k}={v}" for k, v in context.items())
            error_msg = f"{error_msg} | Context: {context_str}"

        # Log with stack trace for critical errors
        if log_level >= logging.ERROR:
            self.logger.log(log_level, error_msg, exc_info=True)
        else:
            self.logger.log(log_level, error_msg)

    def _handle_git_repository_error(self, error: GitRepositoryError, context: Optional[Dict[str, Any]]) -> bool:
        """Handle git repository errors."""
        self.logger.critical("Not a git repository or git not accessible")
        self.logger.critical("Please ensure you're running in a git repository and git is installed")
        return False  # Fatal error

    def _handle_git_reference_error(self, error: GitReferenceError, context: Optional[Dict[str, Any]]) -> bool:
        """Handle git reference errors."""
        self.logger.error("Invalid git references provided")
        self.logger.error("Please check that base-ref and head-ref exist in the repository")

        # Suggest common alternatives
        suggestions = [
            "Try: --base-ref origin/main --head-ref HEAD",
            "Try: --base-ref HEAD~1 --head-ref HEAD",
            "Run 'git branch -a' to see available branches"
        ]

        for suggestion in suggestions:
            self.logger.info(f"Suggestion: {suggestion}")

        return False  # Cannot continue without valid refs

    def _handle_syntax_error(self, error: SyntaxAnalysisError, context: Optional[Dict[str, Any]]) -> bool:
        """Handle syntax errors in Python files."""
        filename = error.details.get('filename', 'unknown')
        lineno = error.details.get('lineno', 'unknown')

        self.logger.warning(f"Skipping file with syntax error: {filename}:{lineno}")
        self.logger.debug(f"Syntax error details: {error.message}")

        return True  # Can continue with other files

    def _handle_file_access_error(self, error: FileAccessError, context: Optional[Dict[str, Any]]) -> bool:
        """Handle file access errors."""
        filename = error.details.get('filename', 'unknown')
        self.logger.warning(f"Skipping inaccessible file: {filename}")
        return True  # Can continue with other files

    def _handle_dependency_error(self, error: DependencyError, context: Optional[Dict[str, Any]]) -> bool:
        """Handle missing dependency errors."""
        command = error.details.get('command', 'unknown')
        self.logger.critical(f"Required dependency not found: {command}")

        if command == 'git':
            self.logger.critical("Please install git: https://git-scm.com/downloads")

        return False  # Fatal error

    def get_error_summary(self) -> Dict[str, int]:
        """Get summary of all errors encountered."""
        return self.error_counts.copy()

    def has_fatal_errors(self) -> bool:
        """Check if any fatal errors were encountered."""
        fatal_error_types = [
            GitRepositoryError.__name__,
            ConfigurationError.__name__,
            DependencyError.__name__
        ]

        return any(error_type in self.error_counts for error_type in fatal_error_types)


def with_error_handling(error_handler: ErrorHandler,
                       context: Optional[Dict[str, Any]] = None,
                       reraise_fatal: bool = True):
    """
    Decorator for functions that need comprehensive error handling.

    Args:
        error_handler: ErrorHandler instance
        context: Additional context for error logging
        reraise_fatal: Whether to reraise fatal errors
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                return func(*args, **kwargs)
            except BreakingChangesDetectorError as e:
                can_continue = error_handler.handle_error(e, context)
                if not can_continue and reraise_fatal:
                    raise
                return None
            except Exception as e:
                # Wrap unknown exceptions
                wrapped_error = BreakingChangesDetectorError(
                    f"Unexpected error in {func.__name__}: {e}",
                    {"function": func.__name__, "args": str(args)[:100]}
                )
                can_continue = error_handler.handle_error(wrapped_error, context)
                if not can_continue and reraise_fatal:
                    raise wrapped_error
                return None
        return wrapper
    return decorator


def with_file_error_handling(error_handler: ErrorHandler):
    """Decorator specifically for file processing operations that can safely skip files."""
    def decorator(func: Callable[..., T]) -> Callable[..., Optional[T]]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Optional[T]:
            try:
                return func(*args, **kwargs)
            except (SyntaxAnalysisError, FileAccessError) as e:
                error_handler.handle_error(e)
                return None  # Skip this file and continue
            except Exception as e:
                wrapped_error = FileAccessError(
                    f"File processing failed: {e}",
                    {"function": func.__name__}
                )
                error_handler.handle_error(wrapped_error)
                return None
        return wrapper
    return decorator


def with_git_error_handling(error_handler: ErrorHandler):
    """Decorator specifically for git operations that should provide helpful error messages."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except (GitRepositoryError, GitReferenceError) as e:
                error_handler.handle_error(e)
                raise  # Git errors are usually fatal
            except Exception as e:
                if "unknown revision" in str(e).lower():
                    git_error = GitReferenceError(
                        f"Invalid git reference: {e}",
                        {"function": func.__name__}
                    )
                elif "not a git repository" in str(e).lower():
                    git_error = GitRepositoryError(
                        f"Git repository error: {e}",
                        {"function": func.__name__}
                    )
                else:
                    git_error = GitAnalysisError(
                        f"Git operation failed: {e}",
                        {"function": func.__name__}
                    )
                error_handler.handle_error(git_error)
                raise git_error
        return wrapper
    return decorator


def safe_operation(default_return=None, log_errors: bool = True):
    """Simple decorator for operations that should never fail the entire process."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logging.getLogger(func.__module__).warning(
                        f"Safe operation {func.__name__} failed: {e}"
                    )
                return default_return
        return wrapper
    return decorator


def setup_exception_handler(logger: logging.Logger) -> None:
    """Setup global exception handler for uncaught exceptions."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Allow KeyboardInterrupt to be handled normally
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback)
        )

        # Print user-friendly error message
        print("\n" + "="*60, file=sys.stderr)
        print("💥 FATAL ERROR", file=sys.stderr)
        print("="*60, file=sys.stderr)
        print(f"An unexpected error occurred: {exc_value}", file=sys.stderr)
        print("\nPlease check the logs for more details.", file=sys.stderr)
        print("If this error persists, please report it as a bug.", file=sys.stderr)
        print("="*60, file=sys.stderr)

    sys.excepthook = handle_exception


def create_safe_logger(name: str, log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """Create a logger with safe error handling."""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler with error handling
    try:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    except Exception as e:
        print(f"Warning: Could not setup console logging: {e}", file=sys.stderr)

    # File handler with error handling
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Warning: Could not setup file logging: {e}", file=sys.stderr)

    return logger


def validate_system_requirements() -> Dict[str, bool]:
    """Validate system requirements and dependencies."""
    requirements = {}

    # Check Python version
    try:
        import sys
        python_version = sys.version_info
        requirements['python_3_8+'] = python_version >= (3, 8)
    except Exception:
        requirements['python_3_8+'] = False

    # Check git availability
    try:
        import subprocess
        subprocess.run(['git', '--version'], capture_output=True, check=True)
        requirements['git'] = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        requirements['git'] = False

    # Check AST module
    try:
        import importlib.util
        requirements['ast_module'] = importlib.util.find_spec('ast') is not None
    except ImportError:
        requirements['ast_module'] = False

    # Check pathlib
    try:
        import importlib.util
        requirements['pathlib'] = importlib.util.find_spec('pathlib') is not None
    except ImportError:
        requirements['pathlib'] = False

    return requirements


def check_and_report_requirements(logger: logging.Logger) -> bool:
    """Check system requirements and report any issues."""
    requirements = validate_system_requirements()

    all_good = True
    for requirement, satisfied in requirements.items():
        if not satisfied:
            logger.error(f"Missing requirement: {requirement}")
            all_good = False
        else:
            logger.debug(f"Requirement satisfied: {requirement}")

    if not all_good:
        logger.critical("System requirements not met. Please install missing dependencies.")

    return all_good
