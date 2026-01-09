"""
WAMA Dev AI - Diff Renderer

Beautiful colored diff display inspired by Claude Code and Git.
Shows additions in green, removals in red.
"""

import difflib
from typing import List, Tuple, Optional
from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box

from config import THEME, BASE_DIR


class DiffRenderer:
    """
    Renders beautiful diffs between two text contents.

    Features:
    - Colored additions (green) and deletions (red)
    - Context lines around changes
    - Line numbers
    - Syntax highlighting
    - Summary statistics
    """

    def __init__(self, console: Optional[Console] = None):
        self._console = console or Console()

    def render_diff(
        self,
        old_content: str,
        new_content: str,
        file_path: Optional[Path] = None,
        context_lines: int = 3,
        show_line_numbers: bool = True,
        syntax_highlight: bool = True,
        language: str = "python",
    ):
        """
        Render a diff between old and new content.

        Args:
            old_content: Original file content
            new_content: Modified file content
            file_path: Path to the file (for display)
            context_lines: Number of context lines around changes
            show_line_numbers: Whether to show line numbers
            syntax_highlight: Whether to syntax highlight code
            language: Language for syntax highlighting
        """
        # Get unified diff
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=str(file_path) if file_path else "original",
            tofile=str(file_path) if file_path else "modified",
            lineterm=""
        ))

        if not diff:
            self._console.print(f"[{THEME['dim']}]No changes[/]")
            return

        # Calculate statistics
        added, removed, changed = self._calculate_stats(diff)

        # Render header
        self._render_header(file_path, added, removed, changed)

        # Render diff hunks
        self._render_hunks(diff, context_lines, language if syntax_highlight else None)

    def _calculate_stats(self, diff: List[str]) -> Tuple[int, int, int]:
        """Calculate diff statistics."""
        added = 0
        removed = 0

        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1

        changed = min(added, removed)
        return added - changed, removed - changed, changed

    def _render_header(
        self,
        file_path: Optional[Path],
        added: int,
        removed: int,
        changed: int
    ):
        """Render the diff header with statistics."""
        # File path
        if file_path:
            try:
                rel_path = file_path.relative_to(BASE_DIR)
            except ValueError:
                rel_path = file_path
            self._console.print(f"[{THEME['file_path']}]📄 {rel_path}[/]")

        # Statistics bar
        stats_parts = []
        if added > 0:
            stats_parts.append(f"[{THEME['added']}]+{added}[/]")
        if removed > 0:
            stats_parts.append(f"[{THEME['removed']}]-{removed}[/]")
        if changed > 0:
            stats_parts.append(f"[yellow]~{changed}[/]")

        if stats_parts:
            stats_text = " ".join(stats_parts)
            self._console.print(f"  {stats_text}")

        self._console.print()

    def _render_hunks(
        self,
        diff: List[str],
        context_lines: int,
        language: Optional[str]
    ):
        """Render diff hunks with coloring."""
        output = Text()

        for line in diff:
            # Skip file headers
            if line.startswith('---') or line.startswith('+++'):
                continue

            # Hunk header
            if line.startswith('@@'):
                output.append(f"\n{line}\n", style="cyan bold")
                continue

            # Additions
            if line.startswith('+'):
                output.append(line.rstrip('\n') + '\n', style=THEME['added'])

            # Deletions
            elif line.startswith('-'):
                output.append(line.rstrip('\n') + '\n', style=THEME['removed'])

            # Context
            else:
                output.append(line.rstrip('\n') + '\n', style=THEME['unchanged'])

        # Display in a panel
        self._console.print(Panel(
            output,
            box=box.ROUNDED,
            border_style="grey50",
            padding=(0, 1),
        ))

    def render_inline_diff(
        self,
        old_content: str,
        new_content: str,
        file_path: Optional[Path] = None,
    ):
        """
        Render an inline diff showing word-level changes.

        Useful for showing small changes within lines.
        """
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        sm = difflib.SequenceMatcher(None, old_lines, new_lines)

        output = Text()

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                for line in old_lines[i1:i2]:
                    output.append(f"  {line}\n", style=THEME['unchanged'])

            elif tag == 'replace':
                # Show old lines as removed
                for line in old_lines[i1:i2]:
                    output.append(f"- {line}\n", style=THEME['removed'])
                # Show new lines as added
                for line in new_lines[j1:j2]:
                    output.append(f"+ {line}\n", style=THEME['added'])

            elif tag == 'delete':
                for line in old_lines[i1:i2]:
                    output.append(f"- {line}\n", style=THEME['removed'])

            elif tag == 'insert':
                for line in new_lines[j1:j2]:
                    output.append(f"+ {line}\n", style=THEME['added'])

        self._console.print(Panel(
            output,
            title=str(file_path) if file_path else "Changes",
            box=box.ROUNDED,
            border_style="grey50",
        ))

    def get_summary(self, old_content: str, new_content: str) -> dict:
        """
        Get a summary of changes without rendering.

        Returns:
            dict with keys: added, removed, changed, total_lines, changed_percent
        """
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        diff = list(difflib.unified_diff(old_lines, new_lines))

        added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))

        total = max(len(old_lines), len(new_lines))
        changed_percent = ((added + removed) / total * 100) if total > 0 else 0

        return {
            "added": added,
            "removed": removed,
            "total_lines": total,
            "changed_percent": round(changed_percent, 1),
            "has_changes": added > 0 or removed > 0,
        }

    def render_summary_table(self, summaries: List[dict]):
        """
        Render a table summarizing changes across multiple files.

        Args:
            summaries: List of dicts from get_summary() with 'file' key added
        """
        from rich.table import Table

        table = Table(title="Changes Summary", box=box.ROUNDED)
        table.add_column("File", style="blue")
        table.add_column("Added", style="green", justify="right")
        table.add_column("Removed", style="red", justify="right")
        table.add_column("Changed %", justify="right")

        total_added = 0
        total_removed = 0

        for summary in summaries:
            if summary.get("has_changes"):
                table.add_row(
                    summary.get("file", "unknown"),
                    f"+{summary['added']}",
                    f"-{summary['removed']}",
                    f"{summary['changed_percent']}%"
                )
                total_added += summary["added"]
                total_removed += summary["removed"]

        # Total row
        table.add_row(
            "[bold]Total[/]",
            f"[bold green]+{total_added}[/]",
            f"[bold red]-{total_removed}[/]",
            ""
        )

        self._console.print(table)
