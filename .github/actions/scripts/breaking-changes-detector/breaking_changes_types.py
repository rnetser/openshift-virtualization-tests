"""
Type definitions and data structures for the breaking changes detector.

This module contains shared types and enums to avoid circular imports.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set


class ChangeType(Enum):
    """Types of breaking changes that can be detected."""
    FUNCTION_SIGNATURE = "function_signature"
    METHOD_SIGNATURE = "method_signature"
    CLASS_REMOVED = "class_removed"
    FUNCTION_REMOVED = "function_removed"
    METHOD_REMOVED = "method_removed"
    IMPORT_PATH = "import_path"
    TYPE_ANNOTATION = "type_annotation"
    PARAMETER_REMOVED = "parameter_removed"
    PARAMETER_RENAMED = "parameter_renamed"
    RETURN_TYPE_CHANGED = "return_type_changed"


@dataclass
class BreakingChange:
    """Represents a detected breaking change."""
    change_type: ChangeType
    file_path: str
    line_number: int
    element_name: str
    old_signature: str
    new_signature: str
    description: str
    severity: str = "medium"  # low, medium, high, critical
    impact_analysis: Optional[str] = None
    confidence: float = 1.0
    affected_files: Optional[Set[str]] = None

    def __post_init__(self):
        if self.affected_files is None:
            self.affected_files = set()


@dataclass
class UsageLocation:
    """Represents a location where a changed element is used."""
    file_path: str
    line_number: int
    context: str
    usage_type: str  # import, call, reference


@dataclass
class UsageInstance:
    """Represents an instance where breaking change affects code."""
    file_path: str
    line_number: int
    line_content: str
    context: Optional[str] = None
    suggested_fix: Optional[str] = None


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    breaking_changes: List[BreakingChange]
    usage_locations: Optional[dict] = None  # Dict[str, List[UsageLocation]]
    total_files_analyzed: int = 0
    total_changes_detected: int = 0
    exit_code: int = 0
    # Legacy fields for backward compatibility
    usage_instances: Optional[List[UsageInstance]] = None
    summary: Optional[dict] = None
    metadata: Optional[dict] = None
