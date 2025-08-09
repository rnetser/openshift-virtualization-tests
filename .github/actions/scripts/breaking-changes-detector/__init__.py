"""
Breaking Changes Detector for GitHub Actions

A comprehensive tool for detecting potential breaking changes in Python codebases
through git diffs and AST analysis.
"""

__version__ = "1.0.0"
__author__ = "GitHub Actions"

from .breaking_changes_detector import BreakingChangesDetector
from .config_manager import ConfigManager
from .types import AnalysisResult, BreakingChange, ChangeType, UsageLocation

__all__ = [
    "BreakingChangesDetector",
    "BreakingChange",
    "ChangeType",
    "AnalysisResult",
    "UsageLocation",
    "ConfigManager"
]
