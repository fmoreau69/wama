"""
WAMA Dev AI - Rich Console Interface

Beautiful terminal output inspired by Claude Code.
Uses the Rich library for formatting.
"""

from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.live import Live
from rich.tree import Tree
from rich.text import Text
from rich import box
from typing import Optional, List, Dict, Any
from pathlib import Path
import sys

from config import THEME, BASE_DIR


class Console:
    """
    Rich console wrapper for beautiful terminal output.

    Provides Claude Code-like formatting for:
    - Status messages (info, success, warning, error)
    - File listings and trees
    - Code display with syntax highlighting
    - Progress indicators
    - Diffs (via DiffRenderer)
    """

    def __init__(self):
        self._console = RichConsole(
            force_terminal=True,
            color_system="auto",
            highlight=True,
        )
        self._spinner = None

    # =========================================================================
    # Basic Output
    # =========================================================================

    def print(self, *args, **kwargs):
        """Print to console."""
        self._console.print(*args, **kwargs)

    def rule(self, title: str = "", style: str = "dim"):
        """Print a horizontal rule."""
        self._console.rule(title, style=style)

    def clear(self):
        """Clear the console."""
        self._console.clear()

    # =========================================================================
    # Status Messages
    # =========================================================================

    def info(self, message: str, icon: str = "ℹ"):
        """Print info message."""
        self._console.print(f"[{THEME['info']}]{icon}[/] {message}")

    def success(self, message: str, icon: str = "✓"):
        """Print success message."""
        self._console.print(f"[{THEME['success']}]{icon}[/] {message}")

    def warning(self, message: str, icon: str = "⚠"):
        """Print warning message."""
        self._console.print(f"[{THEME['warning']}]{icon}[/] {message}")

    def error(self, message: str, icon: str = "✗"):
        """Print error message."""
        self._console.print(f"[{THEME['error']}]{icon}[/] {message}")

    def step(self, step_num: int, total: int, message: str):
        """Print a step in a process."""
        self._console.print(
            f"[{THEME['dim']}][{step_num}/{total}][/] {message}"
        )

    def thinking(self, message: str = "Thinking..."):
        """Print a thinking message with animation."""
        self._console.print(f"[{THEME['dim']}]💭 {message}[/]")

    # =========================================================================
    # Panels and Sections
    # =========================================================================

    def panel(
        self,
        content: str,
        title: str = "",
        border_style: str = "blue",
        expand: bool = True
    ):
        """Display content in a panel."""
        self._console.print(Panel(
            content,
            title=title,
            border_style=border_style,
            expand=expand,
            padding=(1, 2),
        ))

    def header(self, title: str, subtitle: str = ""):
        """Display a header."""
        header_text = f"[bold]{title}[/bold]"
        if subtitle:
            header_text += f"\n[{THEME['dim']}]{subtitle}[/]"

        self._console.print(Panel(
            header_text,
            box=box.DOUBLE,
            border_style="cyan",
            padding=(0, 2),
        ))

    def section(self, title: str):
        """Start a new section."""
        self._console.print()
        self._console.rule(f"[bold]{title}[/bold]", style="cyan")
        self._console.print()

    # =========================================================================
    # Code Display
    # =========================================================================

    def code(
        self,
        code: str,
        language: str = "python",
        title: Optional[str] = None,
        line_numbers: bool = True,
        highlight_lines: Optional[set] = None
    ):
        """Display syntax-highlighted code."""
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=line_numbers,
            word_wrap=True,
            highlight_lines=highlight_lines,
        )

        if title:
            self._console.print(Panel(
                syntax,
                title=f"[bold]{title}[/bold]",
                border_style="grey50",
            ))
        else:
            self._console.print(syntax)

    def code_snippet(
        self,
        code: str,
        start_line: int,
        language: str = "python",
        context_lines: int = 3
    ):
        """Display a code snippet with line numbers."""
        syntax = Syntax(
            code,
            language,
            theme="monokai",
            line_numbers=True,
            start_line=start_line,
            word_wrap=True,
        )
        self._console.print(syntax)

    # =========================================================================
    # File Display
    # =========================================================================

    def file_path(self, path: Path, prefix: str = ""):
        """Display a file path."""
        try:
            rel_path = path.relative_to(BASE_DIR)
        except ValueError:
            rel_path = path

        self._console.print(
            f"{prefix}[{THEME['file_path']}]{rel_path}[/]"
        )

    def file_tree(self, files: List[Path], title: str = "Files"):
        """Display files as a tree."""
        tree = Tree(f"[bold]{title}[/bold]")

        # Group files by directory
        by_dir: Dict[Path, List[Path]] = {}
        for f in files:
            try:
                rel = f.relative_to(BASE_DIR)
                parent = rel.parent
            except ValueError:
                parent = f.parent
                rel = f

            if parent not in by_dir:
                by_dir[parent] = []
            by_dir[parent].append(rel)

        # Build tree
        for dir_path in sorted(by_dir.keys()):
            if str(dir_path) == ".":
                branch = tree
            else:
                branch = tree.add(f"[bold blue]{dir_path}/[/]")

            for file_path in sorted(by_dir[dir_path]):
                branch.add(f"[green]{file_path.name}[/]")

        self._console.print(tree)

    def file_list(self, files: List[Path], title: str = "Files"):
        """Display files as a simple list."""
        table = Table(
            title=title,
            box=box.SIMPLE,
            show_header=False,
            padding=(0, 1),
        )
        table.add_column("Icon", style="dim", width=2)
        table.add_column("Path", style=THEME['file_path'])

        for f in files:
            try:
                rel = f.relative_to(BASE_DIR)
            except ValueError:
                rel = f

            icon = "📄" if f.suffix in {".py", ".js"} else "📝"
            table.add_row(icon, str(rel))

        self._console.print(table)

    # =========================================================================
    # Tables
    # =========================================================================

    def table(
        self,
        data: List[Dict[str, Any]],
        title: str = "",
        columns: Optional[List[str]] = None
    ):
        """Display data as a table."""
        if not data:
            return

        if columns is None:
            columns = list(data[0].keys())

        table = Table(title=title, box=box.ROUNDED)

        for col in columns:
            table.add_column(col.replace("_", " ").title())

        for row in data:
            table.add_row(*[str(row.get(col, "")) for col in columns])

        self._console.print(table)

    # =========================================================================
    # Progress
    # =========================================================================

    def progress(self) -> Progress:
        """Create a progress bar context manager."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=self._console,
        )

    def spinner(self, message: str = "Processing...") -> Live:
        """Create a spinner context manager."""
        from rich.spinner import Spinner
        return Live(
            Spinner("dots", text=message),
            console=self._console,
            transient=True,
        )

    # =========================================================================
    # Input
    # =========================================================================

    def prompt(self, message: str, default: str = "") -> str:
        """Get input from user."""
        from rich.prompt import Prompt
        return Prompt.ask(
            f"[{THEME['prompt']}]{message}[/]",
            default=default,
            console=self._console,
        )

    def confirm(self, message: str, default: bool = False) -> bool:
        """Get yes/no confirmation."""
        from rich.prompt import Confirm
        return Confirm.ask(
            f"[{THEME['prompt']}]{message}[/]",
            default=default,
            console=self._console,
        )

    def select(self, message: str, choices: List[str]) -> str:
        """Select from a list of choices."""
        self._console.print(f"[{THEME['prompt']}]{message}[/]")
        for i, choice in enumerate(choices, 1):
            self._console.print(f"  [{THEME['dim']}]{i}.[/] {choice}")

        while True:
            response = self.prompt("Choice", default="1")
            try:
                idx = int(response) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                if response in choices:
                    return response

            self.warning("Invalid choice, please try again")

    # =========================================================================
    # Model Output
    # =========================================================================

    def model_response(self, model_name: str, response: str):
        """Display a model's response."""
        self._console.print(Panel(
            Markdown(response),
            title=f"[{THEME['model']}]🤖 {model_name}[/]",
            border_style="cyan",
            padding=(1, 2),
        ))

    def model_thinking(self, model_name: str):
        """Show that a model is thinking."""
        self._console.print(
            f"[{THEME['dim']}]🤔 {model_name} is thinking...[/]"
        )

    def token_usage(self, prompt_tokens: int, completion_tokens: int):
        """Display token usage."""
        total = prompt_tokens + completion_tokens
        self._console.print(
            f"[{THEME['dim']}]📊 Tokens: "
            f"{prompt_tokens} prompt + {completion_tokens} completion = {total} total[/]"
        )


# Global console instance
console = Console()
