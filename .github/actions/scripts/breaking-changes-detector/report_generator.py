"""
Report Generation Module

Generates reports in multiple formats (console, JSON, markdown) for breaking changes analysis.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from breaking_changes_types import AnalysisResult, BreakingChange, UsageLocation
from config_manager import ConfigManager


class ReportGenerator:
    """Generates reports in various formats."""

    def __init__(self, config: ConfigManager, logger: logging.Logger):
        """Initialize report generator."""
        self.config = config
        self.logger = logger

    def generate_console_report(self, result: AnalysisResult) -> None:
        """Generate console report with colored output."""
        print("\n" + "="*80)
        print("🔍 BREAKING CHANGES ANALYSIS REPORT")
        print("="*80)

        # Summary
        self._print_summary(result)

        # Breaking changes details
        if result.breaking_changes:
            print("\n📋 DETECTED BREAKING CHANGES:")
            print("-" * 50)

            # Group by severity
            by_severity = self._group_by_severity(result.breaking_changes)

            for severity in ['critical', 'high', 'medium', 'low']:
                changes = by_severity.get(severity, [])
                if changes:
                    self._print_changes_by_severity(severity, changes, result.usage_locations)
        else:
            print("\n✅ No breaking changes detected!")

        # Usage impact summary
        if result.usage_locations:
            self._print_usage_impact(result.usage_locations)

        # Recommendations
        self._print_recommendations(result)

        print("\n" + "="*80)

    def generate_json_report(self, result: AnalysisResult, output_path: str) -> None:
        """Generate JSON report."""
        try:
            self.logger.info(f"Generating JSON report: {output_path}")

            # Convert result to JSON-serializable format
            report_data = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "analysis_version": "1.0.0",
                    "repository_path": self.config.repository_path,
                    "base_ref": self.config.base_ref,
                    "head_ref": self.config.head_ref,
                    "total_files_analyzed": result.total_files_analyzed,
                    "total_changes_detected": result.total_changes_detected,
                    "exit_code": result.exit_code
                },
                "breaking_changes": [
                    self._breaking_change_to_dict(change)
                    for change in result.breaking_changes
                ],
                "usage_locations": {
                    key: [self._usage_location_to_dict(loc) for loc in locations]
                    for key, locations in result.usage_locations.items()
                },
                "summary": {
                    "by_severity": self._summarize_by_severity(result.breaking_changes),
                    "by_type": self._summarize_by_type(result.breaking_changes),
                    "files_with_changes": list({change.file_path for change in result.breaking_changes}),
                    "total_usage_locations": sum(len(locs) for locs in result.usage_locations.values())
                }
            }

            # Write to file
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"JSON report saved to: {output_path}")

        except Exception as e:
            self.logger.error(f"Error generating JSON report: {e}")
            raise

    def generate_markdown_report(self, result: AnalysisResult, output_path: str) -> None:
        """Generate Markdown report."""
        try:
            self.logger.info(f"Generating Markdown report: {output_path}")

            # Generate markdown content
            md_content = self._generate_markdown_content(result)

            # Write to file
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(md_content)

            self.logger.info(f"Markdown report saved to: {output_path}")

        except Exception as e:
            self.logger.error(f"Error generating Markdown report: {e}")
            raise

    def _print_summary(self, result: AnalysisResult) -> None:
        """Print analysis summary."""
        print("📊 Analysis Summary:")
        print(f"   • Files analyzed: {result.total_files_analyzed}")
        print(f"   • Breaking changes detected: {result.total_changes_detected}")
        print(f"   • Exit code: {result.exit_code}")

        if result.breaking_changes:
            by_severity = self._group_by_severity(result.breaking_changes)
            severity_summary = []
            for severity in ['critical', 'high', 'medium', 'low']:
                count = len(by_severity.get(severity, []))
                if count > 0:
                    emoji = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🟢'}[severity]
                    severity_summary.append(f"{emoji} {count} {severity}")

            if severity_summary:
                print(f"   • Severity breakdown: {', '.join(severity_summary)}")

    def _print_changes_by_severity(self, severity: str, changes: List[BreakingChange],
                                 usage_locations: Dict[str, List[UsageLocation]]) -> None:
        """Print breaking changes grouped by severity."""
        emoji_map = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🟢'
        }

        print(f"\n{emoji_map[severity]} {severity.upper()} SEVERITY ({len(changes)} changes):")

        for i, change in enumerate(changes, 1):
            print(f"\n  {i}. {change.description}")
            print(f"     📁 File: {change.file_path}:{change.line_number}")
            print(f"     🔧 Type: {change.change_type.value}")
            print(f"     📝 Element: {change.element_name}")

            if change.old_signature != change.new_signature:
                print(f"     ❌ Old: {change.old_signature}")
                print(f"     ✅ New: {change.new_signature}")

            # Show usage locations if any
            usage_key = f"{change.file_path}:{change.element_name}"
            if usage_key in usage_locations:
                locations = usage_locations[usage_key]
                print(f"     🎯 Usage found in {len(locations)} location(s):")
                for loc in locations[:3]:  # Show first 3 locations
                    print(f"        • {loc.file_path}:{loc.line_number} ({loc.usage_type})")
                if len(locations) > 3:
                    print(f"        ... and {len(locations) - 3} more")
            else:
                print("     ℹ️  No usage detected")

    def _print_usage_impact(self, usage_locations: Dict[str, List[UsageLocation]]) -> None:
        """Print usage impact summary."""
        total_locations = sum(len(locs) for locs in usage_locations.items())
        affected_files = set()

        for locations in usage_locations.values():
            for loc in locations:
                affected_files.add(loc.file_path)

        print("\n🎯 USAGE IMPACT:")
        print(f"   • Total usage locations: {total_locations}")
        print(f"   • Affected files: {len(affected_files)}")

        if affected_files:
            print("   • Files that may need updates:")
            for file_path in sorted(affected_files)[:10]:  # Show first 10
                count = sum(1 for locs in usage_locations.values()
                          for loc in locs if loc.file_path == file_path)
                print(f"     - {file_path} ({count} usage(s))")

            if len(affected_files) > 10:
                print(f"     ... and {len(affected_files) - 10} more files")

    def _print_recommendations(self, result: AnalysisResult) -> None:
        """Print recommendations based on analysis."""
        print("\n💡 RECOMMENDATIONS:")

        if not result.breaking_changes:
            print("   ✅ No breaking changes detected. Safe to proceed!")
            return

        critical_high = [c for c in result.breaking_changes if c.severity in ['critical', 'high']]
        has_usage = any(f"{c.file_path}:{c.element_name}" in result.usage_locations
                       for c in result.breaking_changes)

        if critical_high:
            print("   🚨 Critical/High severity changes detected:")
            print("      - Review all changes carefully before merging")
            print("      - Consider implementing deprecation warnings first")
            print("      - Update documentation and migration guides")

        if has_usage:
            print("   📋 Breaking changes have detected usage:")
            print("      - Update affected code in the same PR")
            print("      - Run comprehensive tests")
            print("      - Consider backward compatibility options")
        else:
            print("   ℹ️  No usage detected for breaking changes:")
            print("      - Changes might be safe if truly unused")
            print("      - Verify with additional testing")
            print("      - Consider if detection missed any usage patterns")

        print("   📚 General recommendations:")
        print("      - Bump major version if this is a public API")
        print("      - Add entries to CHANGELOG.md")
        print("      - Consider using semantic versioning")

    def _group_by_severity(self, changes: List[BreakingChange]) -> Dict[str, List[BreakingChange]]:
        """Group breaking changes by severity."""
        by_severity = {}
        for change in changes:
            severity = change.severity
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(change)
        return by_severity

    def _summarize_by_severity(self, changes: List[BreakingChange]) -> Dict[str, int]:
        """Summarize breaking changes by severity."""
        summary = {}
        for change in changes:
            severity = change.severity
            summary[severity] = summary.get(severity, 0) + 1
        return summary

    def _summarize_by_type(self, changes: List[BreakingChange]) -> Dict[str, int]:
        """Summarize breaking changes by type."""
        summary = {}
        for change in changes:
            change_type = change.change_type.value
            summary[change_type] = summary.get(change_type, 0) + 1
        return summary

    def _breaking_change_to_dict(self, change: BreakingChange) -> Dict[str, Any]:
        """Convert BreakingChange to dictionary."""
        return {
            "change_type": change.change_type.value,
            "file_path": change.file_path,
            "line_number": change.line_number,
            "element_name": change.element_name,
            "old_signature": change.old_signature,
            "new_signature": change.new_signature,
            "description": change.description,
            "severity": change.severity
        }

    def _usage_location_to_dict(self, location: UsageLocation) -> Dict[str, Any]:
        """Convert UsageLocation to dictionary."""
        return {
            "file_path": location.file_path,
            "line_number": location.line_number,
            "context": location.context,
            "usage_type": location.usage_type
        }

    def _generate_markdown_content(self, result: AnalysisResult) -> str:
        """Generate Markdown report content."""
        md_lines = []

        # Header
        md_lines.append("# Breaking Changes Analysis Report")
        md_lines.append("")
        md_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md_lines.append(f"**Repository:** {self.config.repository_path}")
        md_lines.append(f"**Comparison:** {self.config.base_ref}..{self.config.head_ref}")
        md_lines.append("")

        # Summary
        md_lines.append("## 📊 Summary")
        md_lines.append("")
        md_lines.append(f"- **Files analyzed:** {result.total_files_analyzed}")
        md_lines.append(f"- **Breaking changes detected:** {result.total_changes_detected}")
        md_lines.append(f"- **Exit code:** {result.exit_code}")
        md_lines.append("")

        if result.breaking_changes:
            # Severity breakdown
            by_severity = self._group_by_severity(result.breaking_changes)
            md_lines.append("### Severity Breakdown")
            md_lines.append("")

            for severity in ['critical', 'high', 'medium', 'low']:
                count = len(by_severity.get(severity, []))
                if count > 0:
                    emoji = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🟢'}[severity]
                    md_lines.append(f"- {emoji} **{severity.title()}:** {count}")

            md_lines.append("")

            # Breaking changes details
            md_lines.append("## 📋 Breaking Changes")
            md_lines.append("")

            for severity in ['critical', 'high', 'medium', 'low']:
                changes = by_severity.get(severity, [])
                if changes:
                    emoji = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🟢'}[severity]
                    md_lines.append(f"### {emoji} {severity.title()} Severity")
                    md_lines.append("")

                    for i, change in enumerate(changes, 1):
                        md_lines.append(f"#### {i}. {change.description}")
                        md_lines.append("")
                        md_lines.append(f"- **File:** `{change.file_path}:{change.line_number}`")
                        md_lines.append(f"- **Type:** `{change.change_type.value}`")
                        md_lines.append(f"- **Element:** `{change.element_name}`")

                        if change.old_signature != change.new_signature:
                            md_lines.append(f"- **Old signature:** `{change.old_signature}`")
                            md_lines.append(f"- **New signature:** `{change.new_signature}`")

                        # Usage locations
                        usage_key = f"{change.file_path}:{change.element_name}"
                        if usage_key in result.usage_locations:
                            locations = result.usage_locations[usage_key]
                            md_lines.append(f"- **Usage found:** {len(locations)} location(s)")

                            if locations:
                                md_lines.append("  - Affected files:")
                                for loc in locations[:5]:  # Show first 5
                                    md_lines.append(f"    - `{loc.file_path}:{loc.line_number}` ({loc.usage_type})")
                                if len(locations) > 5:
                                    md_lines.append(f"    - ... and {len(locations) - 5} more")
                        else:
                            md_lines.append("- **Usage found:** None detected")

                        md_lines.append("")
        else:
            md_lines.append("## ✅ No Breaking Changes")
            md_lines.append("")
            md_lines.append("No breaking changes were detected in this analysis.")
            md_lines.append("")

        # Usage impact
        if result.usage_locations:
            md_lines.append("## 🎯 Usage Impact")
            md_lines.append("")

            total_locations = sum(len(locs) for locs in result.usage_locations.values())
            affected_files = set()
            for locations in result.usage_locations.values():
                for loc in locations:
                    affected_files.add(loc.file_path)

            md_lines.append(f"- **Total usage locations:** {total_locations}")
            md_lines.append(f"- **Affected files:** {len(affected_files)}")
            md_lines.append("")

            if affected_files:
                md_lines.append("### Files That May Need Updates")
                md_lines.append("")
                for file_path in sorted(affected_files):
                    count = sum(1 for locs in result.usage_locations.values()
                              for loc in locs if loc.file_path == file_path)
                    md_lines.append(f"- `{file_path}` ({count} usage(s))")
                md_lines.append("")

        # Recommendations
        md_lines.append("## 💡 Recommendations")
        md_lines.append("")

        if not result.breaking_changes:
            md_lines.append("✅ No breaking changes detected. Safe to proceed!")
        else:
            critical_high = [c for c in result.breaking_changes if c.severity in ['critical', 'high']]
            has_usage = any(f"{c.file_path}:{c.element_name}" in result.usage_locations
                           for c in result.breaking_changes)

            if critical_high:
                md_lines.append("🚨 **Critical/High severity changes detected:**")
                md_lines.append("- Review all changes carefully before merging")
                md_lines.append("- Consider implementing deprecation warnings first")
                md_lines.append("- Update documentation and migration guides")
                md_lines.append("")

            if has_usage:
                md_lines.append("📋 **Breaking changes have detected usage:**")
                md_lines.append("- Update affected code in the same PR")
                md_lines.append("- Run comprehensive tests")
                md_lines.append("- Consider backward compatibility options")
                md_lines.append("")
            else:
                md_lines.append("ℹ️ **No usage detected for breaking changes:**")
                md_lines.append("- Changes might be safe if truly unused")
                md_lines.append("- Verify with additional testing")
                md_lines.append("- Consider if detection missed any usage patterns")
                md_lines.append("")

            md_lines.append("📚 **General recommendations:**")
            md_lines.append("- Bump major version if this is a public API")
            md_lines.append("- Add entries to CHANGELOG.md")
            md_lines.append("- Consider using semantic versioning")

        md_lines.append("")
        md_lines.append("---")
        md_lines.append("*Report generated by Breaking Changes Detector*")

        return "\n".join(md_lines)
