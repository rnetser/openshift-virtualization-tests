"""
Usage Detection Module

Searches the codebase for usage patterns of changed elements to assess
the impact of breaking changes.
"""

import ast
import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from breaking_changes_types import UsageLocation
from config_manager import ConfigManager


@dataclass
class SearchPattern:
    """A pattern to search for in the codebase."""
    pattern: str
    pattern_type: str  # regex, ast, literal
    element_name: str
    context: str


class UsageDetector:
    """Detects usage patterns of changed elements in the codebase."""

    def __init__(self, config: ConfigManager, logger: logging.Logger):
        """Initialize usage detector."""
        self.config = config
        self.logger = logger
        self.repo_path = Path(config.repository_path).resolve()

    def find_usage_locations(self, element_name: str, source_file: str) -> List[UsageLocation]:
        """Find all locations where an element is used in the codebase."""
        try:
            self.logger.debug(f"Searching for usage of '{element_name}' from {source_file}")

            # Generate search patterns
            patterns = self._generate_search_patterns(element_name, source_file)

            # Get all Python files to search
            files_to_search = self._get_files_to_search()

            # Search for usage in each file
            all_locations = []
            for file_path in files_to_search:
                # Skip the source file itself
                if file_path == source_file:
                    continue

                try:
                    locations = self._search_file_for_usage(file_path, patterns)
                    all_locations.extend(locations)
                except Exception as e:
                    self.logger.debug(f"Error searching {file_path}: {e}")
                    continue

            self.logger.debug(f"Found {len(all_locations)} usage locations for '{element_name}'")
            return all_locations

        except Exception as e:
            self.logger.error(f"Error finding usage locations for {element_name}: {e}")
            return []

    def _generate_search_patterns(self, element_name: str, source_file: str) -> List[SearchPattern]:
        """Generate search patterns for different types of usage."""
        patterns = []

        # Extract module path from source file
        module_path = self._get_module_path(source_file)

        # Pattern 1: Direct import from module
        # from module.path import element_name
        if module_path:
            patterns.append(SearchPattern(
                pattern=rf"from\s+{re.escape(module_path)}\s+import\s+.*\b{re.escape(element_name)}\b",
                pattern_type="regex",
                element_name=element_name,
                context="direct_import"
            ))

        # Pattern 2: Module import with usage
        # import module.path
        # module.path.element_name()
        if module_path:
            patterns.append(SearchPattern(
                pattern=rf"import\s+{re.escape(module_path)}",
                pattern_type="regex",
                element_name=element_name,
                context="module_import"
            ))

            patterns.append(SearchPattern(
                pattern=rf"{re.escape(module_path)}\.{re.escape(element_name)}\b",
                pattern_type="regex",
                element_name=element_name,
                context="qualified_usage"
            ))

        # Pattern 3: Direct usage (after import)
        # element_name()
        patterns.append(SearchPattern(
            pattern=rf"\b{re.escape(element_name)}\s*\(",
            pattern_type="regex",
            element_name=element_name,
            context="function_call"
        ))

        # Pattern 4: Class instantiation
        # element_name()
        patterns.append(SearchPattern(
            pattern=rf"\b{re.escape(element_name)}\s*\(",
            pattern_type="regex",
            element_name=element_name,
            context="class_instantiation"
        ))

        # Pattern 5: Attribute access
        # obj.element_name
        patterns.append(SearchPattern(
            pattern=rf"\.{re.escape(element_name)}\b",
            pattern_type="regex",
            element_name=element_name,
            context="attribute_access"
        ))

        # Pattern 6: Method calls on classes
        if "." in element_name:
            class_name, method_name = element_name.rsplit(".", 1)
            patterns.append(SearchPattern(
                pattern=rf"\b{re.escape(class_name)}\s*\([^)]*\)\.{re.escape(method_name)}\s*\(",
                pattern_type="regex",
                element_name=element_name,
                context="method_call"
            ))

        # Pattern 7: Star imports (risky)
        # from module.path import *
        if module_path:
            patterns.append(SearchPattern(
                pattern=rf"from\s+{re.escape(module_path)}\s+import\s+\*",
                pattern_type="regex",
                element_name=element_name,
                context="star_import"
            ))

        return patterns

    def _get_module_path(self, file_path: str) -> Optional[str]:
        """Convert file path to Python module path."""
        try:
            # Convert file path to module path
            path = Path(file_path)

            # Remove .py extension
            if path.suffix == '.py':
                path = path.with_suffix('')

            # Convert to module notation
            parts = []
            for part in path.parts:
                if part == '..':
                    continue
                if part.isidentifier():
                    parts.append(part)
                else:
                    # Handle files with non-identifier names
                    break

            if parts:
                module_path = '.'.join(parts)
                # Remove common prefixes that aren't part of the module path
                if module_path.startswith('src.'):
                    module_path = module_path[4:]
                return module_path

            return None

        except Exception as e:
            self.logger.debug(f"Could not determine module path for {file_path}: {e}")
            return None

    def _get_files_to_search(self) -> List[str]:
        """Get list of Python files to search for usage."""
        files = []

        for root, dirs, filenames in os.walk(self.repo_path):
            # Skip hidden directories and common ignore patterns
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules']]

            for filename in filenames:
                if filename.endswith('.py'):
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, self.repo_path)

                    if self._should_search_file(rel_path):
                        files.append(rel_path)

        return files

    def _should_search_file(self, file_path: str) -> bool:
        """Check if a file should be searched based on include/exclude patterns."""
        # Check exclude patterns first
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return False

        # Check include patterns
        for pattern in self.config.include_patterns:
            if fnmatch.fnmatch(file_path, pattern):
                return True

        return False

    def _search_file_for_usage(self, file_path: str, patterns: List[SearchPattern]) -> List[UsageLocation]:
        """Search a single file for usage patterns."""
        locations = []

        try:
            full_path = self.repo_path / file_path
            with open(full_path, encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # Search using regex patterns
            locations.extend(self._search_with_regex(file_path, content, patterns))

            # Search using AST analysis for more precise matches
            locations.extend(self._search_with_ast(file_path, content, patterns))

        except Exception as e:
            self.logger.debug(f"Error reading {file_path}: {e}")

        return locations

    def _search_with_regex(self, file_path: str, content: str,
                          patterns: List[SearchPattern]) -> List[UsageLocation]:
        """Search file content using regex patterns."""
        locations = []
        lines = content.split('\n')

        for pattern in patterns:
            if pattern.pattern_type != "regex":
                continue

            try:
                regex = re.compile(pattern.pattern, re.MULTILINE)

                for line_num, line in enumerate(lines, 1):
                    matches = regex.finditer(line)
                    for _match in matches:
                        # Get some context around the match
                        start_line = max(0, line_num - 2)
                        end_line = min(len(lines), line_num + 2)
                        context_lines = lines[start_line:end_line]
                        context = '\n'.join(context_lines)

                        locations.append(UsageLocation(
                            file_path=file_path,
                            line_number=line_num,
                            context=context,
                            usage_type=pattern.context
                        ))

            except re.error as e:
                self.logger.debug(f"Invalid regex pattern {pattern.pattern}: {e}")
                continue

        return locations

    def _search_with_ast(self, file_path: str, content: str,
                        patterns: List[SearchPattern]) -> List[UsageLocation]:
        """Search file content using AST analysis for precise matches."""
        locations = []

        try:
            tree = ast.parse(content, filename=file_path)

            # Use AST visitor to find specific usage patterns
            visitor = UsageVisitor(patterns, content.split('\n'))
            visitor.visit(tree)

            for usage in visitor.found_usages:
                locations.append(UsageLocation(
                    file_path=file_path,
                    line_number=usage['line_number'],
                    context=usage['context'],
                    usage_type=usage['usage_type']
                ))

        except SyntaxError:
            # Skip files with syntax errors
            pass
        except Exception as e:
            self.logger.debug(f"AST search error in {file_path}: {e}")

        return locations


class UsageVisitor(ast.NodeVisitor):
    """AST visitor to find specific usage patterns."""

    def __init__(self, patterns: List[SearchPattern], lines: List[str]):
        self.patterns = patterns
        self.lines = lines
        self.found_usages = []
        self.imports = {}  # Track imports in the file

    def visit_Import(self, node: ast.Import):
        """Track import statements."""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports[name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from imports."""
        module = node.module or ""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            if alias.name == "*":
                # Star import - mark as risky
                self._add_usage(node.lineno, "star_import", f"from {module} import *")
            else:
                self.imports[name] = f"{module}.{alias.name}" if module else alias.name
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Check function calls."""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            self._check_usage_pattern(func_name, node.lineno, "function_call")
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                obj_name = node.func.value.id
                attr_name = node.func.attr
                full_name = f"{obj_name}.{attr_name}"
                self._check_usage_pattern(full_name, node.lineno, "method_call")
                self._check_usage_pattern(attr_name, node.lineno, "method_call")

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Check attribute access."""
        if isinstance(node.value, ast.Name):
            obj_name = node.value.id
            attr_name = node.attr
            full_name = f"{obj_name}.{attr_name}"
            self._check_usage_pattern(full_name, node.lineno, "attribute_access")
            self._check_usage_pattern(attr_name, node.lineno, "attribute_access")

        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Check name references."""
        self._check_usage_pattern(node.id, node.lineno, "name_reference")
        self.generic_visit(node)

    def _check_usage_pattern(self, name: str, line_number: int, usage_type: str):
        """Check if a name matches any of our search patterns."""
        for pattern in self.patterns:
            if pattern.element_name in name or name == pattern.element_name:
                # Check if this usage is through an import we've tracked
                qualified_name = self.imports.get(name, name)
                if pattern.element_name in qualified_name:
                    self._add_usage(line_number, usage_type, name)

    def _add_usage(self, line_number: int, usage_type: str, name: str):
        """Add a found usage to the results."""
        # Get context around the line
        start_line = max(0, line_number - 3)
        end_line = min(len(self.lines), line_number + 2)
        context_lines = self.lines[start_line:end_line]
        context = '\n'.join(context_lines)

        self.found_usages.append({
            'line_number': line_number,
            'usage_type': usage_type,
            'context': context,
            'name': name
        })
