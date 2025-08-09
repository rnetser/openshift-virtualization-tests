"""
AST Analysis Module

Analyzes Python Abstract Syntax Trees to detect breaking changes in code structure.
"""

import ast
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from breaking_changes_types import BreakingChange, ChangeType
from config_manager import ConfigManager
from git_analyzer import GitAnalyzer


@dataclass
class FunctionInfo:
    """Information about a function or method."""
    name: str
    args: List[str]
    defaults: List[str]
    vararg: Optional[str]
    kwarg: Optional[str]
    annotations: Dict[str, str]
    return_annotation: Optional[str]
    line_number: int
    is_method: bool = False
    class_name: Optional[str] = None
    decorators: List[str] = None

    def __post_init__(self):
        if self.decorators is None:
            self.decorators = []


@dataclass
class ClassInfo:
    """Information about a class."""
    name: str
    bases: List[str]
    methods: List[FunctionInfo]
    line_number: int
    decorators: List[str] = None

    def __post_init__(self):
        if self.decorators is None:
            self.decorators = []


@dataclass
class ImportInfo:
    """Information about an import statement."""
    module: str
    names: List[str]
    aliases: Dict[str, str]
    line_number: int
    is_from_import: bool = False


class ASTAnalyzer:
    """Analyzes Python AST to detect breaking changes."""

    def __init__(self, config: ConfigManager, logger: logging.Logger):
        """Initialize AST analyzer."""
        self.config = config
        self.logger = logger
        self.git_analyzer = GitAnalyzer(config, logger)

    def analyze_file_changes(self, file_path: str) -> List[BreakingChange]:
        """Analyze a file for breaking changes between git refs."""
        try:
            self.logger.debug(f"Analyzing file: {file_path}")

            # Get file content for both refs
            file_changes = self.git_analyzer.get_file_changes(file_path)

            if not file_changes.old_content and not file_changes.new_content:
                self.logger.debug(f"No content to analyze for {file_path}")
                return []

            # Parse old and new ASTs
            old_ast = self._parse_ast(file_changes.old_content, file_path, "old")
            new_ast = self._parse_ast(file_changes.new_content, file_path, "new")

            if old_ast is None and new_ast is None:
                self.logger.warning(f"Could not parse AST for {file_path}")
                return []

            # Extract information from both ASTs
            old_info = self._extract_ast_info(old_ast) if old_ast else {}
            new_info = self._extract_ast_info(new_ast) if new_ast else {}

            # Compare and find breaking changes
            breaking_changes = self._compare_ast_info(old_info, new_info, file_path)

            self.logger.debug(f"Found {len(breaking_changes)} breaking changes in {file_path}")
            return breaking_changes

        except Exception as e:
            self.logger.error(f"Error analyzing {file_path}: {e}")
            return []

    def _parse_ast(self, content: str, file_path: str, version: str) -> Optional[ast.AST]:
        """Parse Python code into AST."""
        if not content.strip():
            return None

        try:
            return ast.parse(content, filename=file_path)
        except SyntaxError as e:
            self.logger.warning(f"Syntax error in {version} version of {file_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to parse {version} AST for {file_path}: {e}")
            return None

    def _extract_ast_info(self, tree: ast.AST) -> Dict[str, Any]:
        """Extract relevant information from AST."""
        info = {
            'functions': {},
            'classes': {},
            'imports': {},
            'variables': set(),
            'constants': {}
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_info = self._extract_function_info(node)
                info['functions'][func_info.name] = func_info

            elif isinstance(node, ast.AsyncFunctionDef):
                func_info = self._extract_function_info(node, is_async=True)
                info['functions'][func_info.name] = func_info

            elif isinstance(node, ast.ClassDef):
                class_info = self._extract_class_info(node)
                info['classes'][class_info.name] = class_info

            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                import_info = self._extract_import_info(node)
                for name in import_info.names:
                    info['imports'][name] = import_info

            elif isinstance(node, ast.Assign):
                # Extract module-level variables
                if hasattr(node, 'targets'):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            info['variables'].add(target.id)

        return info

    def _extract_function_info(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
                             is_async: bool = False) -> FunctionInfo:
        """Extract information from a function definition."""
        args = []
        defaults = []
        annotations = {}

        # Process arguments
        if node.args:
            # Regular arguments
            for arg in node.args.args:
                args.append(arg.arg)
                if arg.annotation:
                    annotations[arg.arg] = ast.unparse(arg.annotation)

            # Default values
            if node.args.defaults:
                defaults = [ast.unparse(default) for default in node.args.defaults]

        # Process vararg and kwarg
        vararg = node.args.vararg.arg if node.args.vararg else None
        kwarg = node.args.kwarg.arg if node.args.kwarg else None

        # Process return annotation
        return_annotation = None
        if node.returns:
            return_annotation = ast.unparse(node.returns)

        # Process decorators
        decorators = []
        for decorator in node.decorator_list:
            decorators.append(ast.unparse(decorator))

        # Check if it's a method (has 'self' or 'cls' as first parameter)
        is_method = False
        class_name = None
        if args and args[0] in ['self', 'cls']:
            is_method = True
            # Try to find the class name by walking up the AST
            # This is a simplified approach - in practice, you'd need more context

        return FunctionInfo(
            name=node.name,
            args=args,
            defaults=defaults,
            vararg=vararg,
            kwarg=kwarg,
            annotations=annotations,
            return_annotation=return_annotation,
            line_number=node.lineno,
            is_method=is_method,
            class_name=class_name,
            decorators=decorators
        )

    def _extract_class_info(self, node: ast.ClassDef) -> ClassInfo:
        """Extract information from a class definition."""
        bases = []
        for base in node.bases:
            bases.append(ast.unparse(base))

        decorators = []
        for decorator in node.decorator_list:
            decorators.append(ast.unparse(decorator))

        # Extract methods
        methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_info = self._extract_function_info(item)
                method_info.is_method = True
                method_info.class_name = node.name
                methods.append(method_info)

        return ClassInfo(
            name=node.name,
            bases=bases,
            methods=methods,
            line_number=node.lineno,
            decorators=decorators
        )

    def _extract_import_info(self, node: Union[ast.Import, ast.ImportFrom]) -> ImportInfo:
        """Extract information from import statements."""
        names = []
        aliases = {}

        for alias in node.names:
            names.append(alias.name)
            if alias.asname:
                aliases[alias.name] = alias.asname

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            is_from_import = True
        else:
            module = ""
            is_from_import = False

        return ImportInfo(
            module=module,
            names=names,
            aliases=aliases,
            line_number=node.lineno,
            is_from_import=is_from_import
        )

    def _compare_ast_info(self, old_info: Dict[str, Any], new_info: Dict[str, Any],
                         file_path: str) -> List[BreakingChange]:
        """Compare old and new AST info to find breaking changes."""
        breaking_changes = []

        # Check removed functions
        breaking_changes.extend(self._check_removed_functions(old_info, new_info, file_path))

        # Check function signature changes
        breaking_changes.extend(self._check_function_signature_changes(old_info, new_info, file_path))

        # Check removed classes
        breaking_changes.extend(self._check_removed_classes(old_info, new_info, file_path))

        # Check class method changes
        breaking_changes.extend(self._check_class_method_changes(old_info, new_info, file_path))

        # Check import changes
        breaking_changes.extend(self._check_import_changes(old_info, new_info, file_path))

        return breaking_changes

    def _check_removed_functions(self, old_info: Dict, new_info: Dict,
                               file_path: str) -> List[BreakingChange]:
        """Check for removed functions."""
        breaking_changes = []

        old_functions = old_info.get('functions', {})
        new_functions = new_info.get('functions', {})

        for func_name, func_info in old_functions.items():
            if func_name not in new_functions:
                breaking_changes.append(BreakingChange(
                    change_type=ChangeType.FUNCTION_REMOVED,
                    file_path=file_path,
                    line_number=func_info.line_number,
                    element_name=func_name,
                    old_signature=self._format_function_signature(func_info),
                    new_signature="<removed>",
                    description=f"Function '{func_name}' was removed",
                    severity="high"
                ))

        return breaking_changes

    def _check_function_signature_changes(self, old_info: Dict, new_info: Dict,
                                        file_path: str) -> List[BreakingChange]:
        """Check for function signature changes."""
        breaking_changes = []

        old_functions = old_info.get('functions', {})
        new_functions = new_info.get('functions', {})

        for func_name in old_functions:
            if func_name in new_functions:
                old_func = old_functions[func_name]
                new_func = new_functions[func_name]

                changes = self._compare_function_signatures(old_func, new_func)
                for change in changes:
                    breaking_changes.append(BreakingChange(
                        change_type=change['type'],
                        file_path=file_path,
                        line_number=new_func.line_number,
                        element_name=func_name,
                        old_signature=self._format_function_signature(old_func),
                        new_signature=self._format_function_signature(new_func),
                        description=change['description'],
                        severity=change['severity']
                    ))

        return breaking_changes

    def _check_removed_classes(self, old_info: Dict, new_info: Dict,
                             file_path: str) -> List[BreakingChange]:
        """Check for removed classes."""
        breaking_changes = []

        old_classes = old_info.get('classes', {})
        new_classes = new_info.get('classes', {})

        for class_name, class_info in old_classes.items():
            if class_name not in new_classes:
                breaking_changes.append(BreakingChange(
                    change_type=ChangeType.CLASS_REMOVED,
                    file_path=file_path,
                    line_number=class_info.line_number,
                    element_name=class_name,
                    old_signature=f"class {class_name}({', '.join(class_info.bases)})",
                    new_signature="<removed>",
                    description=f"Class '{class_name}' was removed",
                    severity="high"
                ))

        return breaking_changes

    def _check_class_method_changes(self, old_info: Dict, new_info: Dict,
                                  file_path: str) -> List[BreakingChange]:
        """Check for class method changes."""
        breaking_changes = []

        old_classes = old_info.get('classes', {})
        new_classes = new_info.get('classes', {})

        for class_name in old_classes:
            if class_name in new_classes:
                old_class = old_classes[class_name]
                new_class = new_classes[class_name]

                # Create method dictionaries
                old_methods = {m.name: m for m in old_class.methods}
                new_methods = {m.name: m for m in new_class.methods}

                # Check for removed methods
                for method_name, method_info in old_methods.items():
                    if method_name not in new_methods:
                        breaking_changes.append(BreakingChange(
                            change_type=ChangeType.METHOD_REMOVED,
                            file_path=file_path,
                            line_number=method_info.line_number,
                            element_name=f"{class_name}.{method_name}",
                            old_signature=self._format_function_signature(method_info),
                            new_signature="<removed>",
                            description=f"Method '{method_name}' was removed from class '{class_name}'",
                            severity="high"
                        ))

                # Check for method signature changes
                for method_name in old_methods:
                    if method_name in new_methods:
                        old_method = old_methods[method_name]
                        new_method = new_methods[method_name]

                        changes = self._compare_function_signatures(old_method, new_method)
                        for change in changes:
                            breaking_changes.append(BreakingChange(
                                change_type=ChangeType.METHOD_SIGNATURE,
                                file_path=file_path,
                                line_number=new_method.line_number,
                                element_name=f"{class_name}.{method_name}",
                                old_signature=self._format_function_signature(old_method),
                                new_signature=self._format_function_signature(new_method),
                                description=f"Method '{method_name}' in class '{class_name}': {change['description']}",
                                severity=change['severity']
                            ))

        return breaking_changes

    def _check_import_changes(self, old_info: Dict, new_info: Dict,
                            file_path: str) -> List[BreakingChange]:
        """Check for import path changes that might affect external usage."""
        breaking_changes = []

        # For now, we focus on public API changes rather than internal imports
        # Import changes are typically not breaking unless they affect public exports

        return breaking_changes

    def _compare_function_signatures(self, old_func: FunctionInfo,
                                   new_func: FunctionInfo) -> List[Dict[str, Any]]:
        """Compare two function signatures and identify breaking changes."""
        changes = []

        # Check for parameter removal
        removed_params = set(old_func.args) - set(new_func.args)
        for param in removed_params:
            changes.append({
                'type': ChangeType.PARAMETER_REMOVED,
                'description': f"Parameter '{param}' was removed",
                'severity': 'high'
            })

        # Check for parameter reordering (positional parameters)
        if len(old_func.args) > 0 and len(new_func.args) > 0:
            # Only check parameters that exist in both versions
            common_params = [p for p in old_func.args if p in new_func.args]
            old_order = [p for p in old_func.args if p in common_params]
            new_order = [p for p in new_func.args if p in common_params]

            if old_order != new_order:
                changes.append({
                    'type': ChangeType.FUNCTION_SIGNATURE,
                    'description': "Parameter order changed",
                    'severity': 'high'
                })

        # Check for default value changes
        old_defaults_dict = {}
        if old_func.defaults:
            # Map defaults to parameters (defaults apply to last N parameters)
            num_defaults = len(old_func.defaults)
            params_with_defaults = old_func.args[-num_defaults:]
            old_defaults_dict = dict(zip(params_with_defaults, old_func.defaults))

        new_defaults_dict = {}
        if new_func.defaults:
            num_defaults = len(new_func.defaults)
            params_with_defaults = new_func.args[-num_defaults:]
            new_defaults_dict = dict(zip(params_with_defaults, new_func.defaults))

        # Check if required parameters became optional or vice versa
        for param in old_func.args:
            if param in new_func.args:
                old_has_default = param in old_defaults_dict
                new_has_default = param in new_defaults_dict

                if old_has_default and not new_has_default:
                    changes.append({
                        'type': ChangeType.FUNCTION_SIGNATURE,
                        'description': f"Parameter '{param}' became required (default value removed)",
                        'severity': 'high'
                    })
                elif not old_has_default and new_has_default:
                    changes.append({
                        'type': ChangeType.FUNCTION_SIGNATURE,
                        'description': f"Parameter '{param}' became optional (default value added)",
                        'severity': 'low'
                    })
                elif old_has_default and new_has_default:
                    if old_defaults_dict[param] != new_defaults_dict[param]:
                        changes.append({
                            'type': ChangeType.FUNCTION_SIGNATURE,
                            'description': f"Default value for parameter '{param}' changed",
                            'severity': 'medium'
                        })

        # Check for return type annotation changes
        if old_func.return_annotation != new_func.return_annotation:
            if old_func.return_annotation and new_func.return_annotation:
                changes.append({
                    'type': ChangeType.RETURN_TYPE_CHANGED,
                    'description': f"Return type annotation changed from '{old_func.return_annotation}' to '{new_func.return_annotation}'",
                    'severity': 'medium'
                })
            elif old_func.return_annotation and not new_func.return_annotation:
                changes.append({
                    'type': ChangeType.RETURN_TYPE_CHANGED,
                    'description': "Return type annotation removed",
                    'severity': 'low'
                })
            elif not old_func.return_annotation and new_func.return_annotation:
                changes.append({
                    'type': ChangeType.RETURN_TYPE_CHANGED,
                    'description': f"Return type annotation added: '{new_func.return_annotation}'",
                    'severity': 'low'
                })

        # Check for type annotation changes on parameters
        for param in old_func.args:
            if param in new_func.args:
                old_annotation = old_func.annotations.get(param)
                new_annotation = new_func.annotations.get(param)

                if old_annotation != new_annotation:
                    if old_annotation and new_annotation:
                        changes.append({
                            'type': ChangeType.TYPE_ANNOTATION,
                            'description': f"Type annotation for parameter '{param}' changed from '{old_annotation}' to '{new_annotation}'",
                            'severity': 'medium'
                        })
                    elif old_annotation and not new_annotation:
                        changes.append({
                            'type': ChangeType.TYPE_ANNOTATION,
                            'description': f"Type annotation for parameter '{param}' removed",
                            'severity': 'low'
                        })
                    elif not old_annotation and new_annotation:
                        changes.append({
                            'type': ChangeType.TYPE_ANNOTATION,
                            'description': f"Type annotation for parameter '{param}' added: '{new_annotation}'",
                            'severity': 'low'
                        })

        return changes

    def _format_function_signature(self, func_info: FunctionInfo) -> str:
        """Format a function signature for display."""
        signature_parts = [func_info.name, "("]

        params = []
        for i, arg in enumerate(func_info.args):
            param = arg

            # Add type annotation
            if arg in func_info.annotations:
                param += f": {func_info.annotations[arg]}"

            # Add default value
            if func_info.defaults:
                defaults_start = len(func_info.args) - len(func_info.defaults)
                if i >= defaults_start:
                    default_idx = i - defaults_start
                    param += f" = {func_info.defaults[default_idx]}"

            params.append(param)

        if func_info.vararg:
            params.append(f"*{func_info.vararg}")

        if func_info.kwarg:
            params.append(f"**{func_info.kwarg}")

        signature_parts.append(", ".join(params))
        signature_parts.append(")")

        if func_info.return_annotation:
            signature_parts.append(f" -> {func_info.return_annotation}")

        return "".join(signature_parts)
