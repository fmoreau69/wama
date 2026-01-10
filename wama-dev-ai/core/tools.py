"""
WAMA Dev AI - Tool System

Tool-based architecture allowing LLMs to call functions.
Inspired by Claude Code's tool use pattern.
"""

from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path
import json
import subprocess
import re

from config import BASE_DIR, EXCLUDE_DIRS


@dataclass
class Tool:
    """Definition of a tool that can be called by the LLM."""
    name: str
    description: str
    parameters: Dict[str, Any]
    function: Callable
    requires_confirmation: bool = False


@dataclass
class ToolCall:
    """A tool call request from the LLM."""
    tool_name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    output: str
    error: Optional[str] = None


class ToolRegistry:
    """
    Registry of available tools for the AI agent.

    Tools allow the LLM to:
    - Read files
    - Search for files
    - Edit files
    - Run commands
    - Get project info
    """

    def __init__(self, base_dir: Path = BASE_DIR):
        self._tools: Dict[str, Tool] = {}
        self._base_dir = base_dir
        self._register_builtin_tools()

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tools_description(self) -> str:
        """Get a formatted description of all tools for the LLM."""
        descriptions = []
        for tool in self._tools.values():
            params_str = ", ".join(
                f"{k}: {v.get('type', 'any')}"
                for k, v in tool.parameters.items()
            )
            descriptions.append(
                f"- {tool.name}({params_str}): {tool.description}"
            )
        return "\n".join(descriptions)

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        tool = self._tools.get(call.tool_name)

        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {call.tool_name}"
            )

        try:
            result = tool.function(**call.arguments)
            return ToolResult(success=True, output=str(result))
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e)
            )

    def parse_tool_calls(self, response: str) -> List[ToolCall]:
        """
        Parse tool calls from LLM response.

        Supported formats:
        1. <tool_call>{"name": "tool_name", "arguments": {...}}</tool_call>
        2. TOOL: tool_name\nARGS: {...}
        3. ```json\n{"name": "tool_name", "arguments": {...}}\n```
        4. Plain JSON: {"name": "tool_name", "arguments": {...}}
        5. Function call style: tool_name(arg1="value1", arg2="value2")
        """
        calls = []
        seen_calls = set()  # Avoid duplicates

        def add_call(name: str, arguments: dict):
            """Add a call if not already seen."""
            key = (name, json.dumps(arguments, sort_keys=True))
            if key not in seen_calls and name in self._tools:
                seen_calls.add(key)
                calls.append(ToolCall(tool_name=name, arguments=arguments))

        # Format 1: XML-like tags
        xml_pattern = r'<tool_call>\s*({.*?})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                data = json.loads(match.group(1))
                add_call(data.get("name", ""), data.get("arguments", {}))
            except json.JSONDecodeError:
                continue

        # Format 2: TOOL/ARGS format
        tool_pattern = r'TOOL:\s*(\w+)\s*\n\s*ARGS:\s*({.*?})(?:\n|$)'
        for match in re.finditer(tool_pattern, response, re.DOTALL):
            try:
                add_call(match.group(1), json.loads(match.group(2)))
            except json.JSONDecodeError:
                continue

        # Format 3: JSON in code blocks
        code_block_pattern = r'```(?:json)?\s*\n?\s*({[^`]*"name"\s*:\s*"[^"]+_?(?:file|content|directory|command|project)[^"]*"[^`]*})\s*\n?```'
        for match in re.finditer(code_block_pattern, response, re.DOTALL | re.IGNORECASE):
            try:
                data = json.loads(match.group(1))
                if "name" in data:
                    add_call(data.get("name", ""), data.get("arguments", {}))
            except json.JSONDecodeError:
                continue

        # Format 4: Plain JSON with tool name
        # Look for JSON objects that contain "name" matching a tool name
        # Handle nested braces in arguments
        tool_names_pattern = '|'.join(self._tools.keys())
        plain_json_pattern = rf'\{{\s*"name"\s*:\s*"({tool_names_pattern})"\s*,\s*"arguments"\s*:\s*(\{{[^{{}}]*\}})\s*\}}'
        for match in re.finditer(plain_json_pattern, response, re.DOTALL):
            try:
                tool_name = match.group(1)
                args_json = match.group(2)
                arguments = json.loads(args_json)
                add_call(tool_name, arguments)
            except json.JSONDecodeError:
                continue

        # Format 4b: Plain JSON - try to find and parse any JSON object with tool name
        for tool_name in self._tools.keys():
            simple_pattern = rf'\{{\s*"name"\s*:\s*"{tool_name}"\s*,\s*"arguments"\s*:\s*\{{([^}}]+)\}}\s*\}}'
            for match in re.finditer(simple_pattern, response, re.DOTALL):
                try:
                    args_str = '{' + match.group(1) + '}'
                    arguments = json.loads(args_str)
                    add_call(tool_name, arguments)
                except json.JSONDecodeError:
                    continue

        # Format 5: Function call style - tool_name(arg1="value1")
        for tool_name in self._tools.keys():
            func_pattern = rf'\b{tool_name}\s*\(\s*([^)]*)\s*\)'
            for match in re.finditer(func_pattern, response):
                args_str = match.group(1)
                arguments = self._parse_function_args(args_str)
                if arguments is not None:
                    add_call(tool_name, arguments)

        return calls

    def _parse_function_args(self, args_str: str) -> Optional[Dict[str, Any]]:
        """Parse function-style arguments like: arg1="value1", arg2=123"""
        if not args_str.strip():
            return {}

        arguments = {}
        # Match key=value or key="value" patterns
        arg_pattern = r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\d+(?:\.\d+)?)|(\w+))'
        for match in re.finditer(arg_pattern, args_str):
            key = match.group(1)
            # Get the first non-None value group
            value = match.group(2) or match.group(3) or match.group(4) or match.group(5)
            if value is not None:
                # Try to convert to int/float if numeric
                if match.group(4):
                    value = float(value) if '.' in value else int(value)
                arguments[key] = value

        return arguments if arguments else None

    # =========================================================================
    # Built-in Tools
    # =========================================================================

    def _register_builtin_tools(self):
        """Register built-in tools."""

        # Read File
        self.register(Tool(
            name="read_file",
            description="Read the contents of a file",
            parameters={
                "path": {"type": "string", "description": "Path to the file (relative to project root)"},
                "start_line": {"type": "integer", "description": "Start line (optional)", "required": False},
                "end_line": {"type": "integer", "description": "End line (optional)", "required": False},
            },
            function=self._read_file
        ))

        # Write File
        self.register(Tool(
            name="write_file",
            description="Write content to a file (creates or overwrites)",
            parameters={
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            function=self._write_file,
            requires_confirmation=True
        ))

        # Edit File
        self.register(Tool(
            name="edit_file",
            description="Replace a specific string in a file",
            parameters={
                "path": {"type": "string", "description": "Path to the file"},
                "old_string": {"type": "string", "description": "String to find"},
                "new_string": {"type": "string", "description": "String to replace with"},
            },
            function=self._edit_file,
            requires_confirmation=True
        ))

        # Search Files
        self.register(Tool(
            name="search_files",
            description="Search for files by name pattern",
            parameters={
                "pattern": {"type": "string", "description": "Glob pattern (e.g., '*.py', 'views.py')"},
            },
            function=self._search_files
        ))

        # Search Content
        self.register(Tool(
            name="search_content",
            description="Search for text in files (grep-like)",
            parameters={
                "query": {"type": "string", "description": "Text to search for"},
                "extensions": {"type": "string", "description": "File extensions (comma-separated, e.g., '.py,.js')", "required": False},
            },
            function=self._search_content
        ))

        # List Directory
        self.register(Tool(
            name="list_directory",
            description="List files in a directory",
            parameters={
                "path": {"type": "string", "description": "Directory path (relative to project root)"},
            },
            function=self._list_directory
        ))

        # Run Command
        self.register(Tool(
            name="run_command",
            description="Run a shell command",
            parameters={
                "command": {"type": "string", "description": "Command to run"},
            },
            function=self._run_command,
            requires_confirmation=True
        ))

        # Get Project Info
        self.register(Tool(
            name="get_project_info",
            description="Get information about the project structure",
            parameters={},
            function=self._get_project_info
        ))

    def _read_file(self, path: str, start_line: int = None, end_line: int = None) -> str:
        """Read file contents."""
        file_path = self._resolve_path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = file_path.read_text(encoding='utf-8')

        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            start = (start_line or 1) - 1
            end = end_line or len(lines)
            lines = lines[start:end]
            content = "\n".join(lines)

        return content

    def _write_file(self, path: str, content: str) -> str:
        """Write content to file."""
        file_path = self._resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')
        return f"Written {len(content)} bytes to {path}"

    def _edit_file(self, path: str, old_string: str, new_string: str) -> str:
        """Replace string in file."""
        file_path = self._resolve_path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = file_path.read_text(encoding='utf-8')

        if old_string not in content:
            raise ValueError(f"String not found in file: {old_string[:50]}...")

        new_content = content.replace(old_string, new_string, 1)
        file_path.write_text(new_content, encoding='utf-8')

        return f"Replaced string in {path}"

    def _search_files(self, pattern: str) -> str:
        """Search for files by pattern. Returns only files, not directories."""
        results = []
        directories_found = []

        for path in self._base_dir.rglob(pattern):
            try:
                rel = path.relative_to(self._base_dir)
            except ValueError:
                rel = path

            if path.is_dir():
                # Track directories but list their contents
                directories_found.append(rel)
                # List files in this directory
                for child in path.rglob("*"):
                    if child.is_file() and self._should_include(child):
                        try:
                            child_rel = child.relative_to(self._base_dir)
                            results.append(str(child_rel))
                        except ValueError:
                            results.append(str(child))
            elif path.is_file() and self._should_include(path):
                results.append(str(rel))

        if not results:
            if directories_found:
                return f"Found directories but no matching files:\n" + "\n".join(str(d) for d in directories_found)
            return "No files found"

        # Remove duplicates and sort
        results = sorted(set(results))
        return "\n".join(results[:50])  # Limit to 50 results

    def _search_content(self, query: str, extensions: str = ".py") -> str:
        """Search for content in files."""
        ext_list = [e.strip() for e in extensions.split(",")]
        results = []

        for ext in ext_list:
            if not ext.startswith("."):
                ext = f".{ext}"

            for path in self._base_dir.rglob(f"*{ext}"):
                if not self._should_include(path):
                    continue

                try:
                    content = path.read_text(encoding='utf-8', errors='ignore')
                    if query.lower() in content.lower():
                        rel = path.relative_to(self._base_dir)
                        # Find matching lines
                        for i, line in enumerate(content.splitlines(), 1):
                            if query.lower() in line.lower():
                                results.append(f"{rel}:{i}: {line.strip()[:80]}")
                                if len(results) >= 30:
                                    break
                except Exception:
                    continue

                if len(results) >= 30:
                    break

        if not results:
            return f"No matches found for '{query}'"

        return "\n".join(results)

    def _list_directory(self, path: str = ".") -> str:
        """List directory contents."""
        dir_path = self._resolve_path(path)

        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        items = []
        for item in sorted(dir_path.iterdir()):
            if item.name.startswith("."):
                continue

            prefix = "📁" if item.is_dir() else "📄"
            items.append(f"{prefix} {item.name}")

        return "\n".join(items) if items else "Empty directory"

    def _run_command(self, command: str) -> str:
        """Run a shell command."""
        result = subprocess.run(
            command,
            shell=True,
            cwd=self._base_dir,
            capture_output=True,
            text=True,
            timeout=60
        )

        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"

        return output or "(no output)"

    def _get_project_info(self) -> str:
        """Get project information."""
        info = []
        info.append(f"Project root: {self._base_dir}")

        # Count files by type
        counts = {}
        for path in self._base_dir.rglob("*"):
            if path.is_file() and self._should_include(path):
                ext = path.suffix or "no extension"
                counts[ext] = counts.get(ext, 0) + 1

        info.append("\nFile counts by extension:")
        for ext, count in sorted(counts.items(), key=lambda x: -x[1])[:10]:
            info.append(f"  {ext}: {count}")

        # Key directories
        info.append("\nKey directories:")
        for name in ["wama", "templates", "static", "tests", "docs"]:
            path = self._base_dir / name
            if path.exists():
                info.append(f"  📁 {name}/")

        return "\n".join(info)

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to base directory."""
        p = Path(path)
        if not p.is_absolute():
            p = self._base_dir / p
        return p.resolve()

    def _should_include(self, path: Path) -> bool:
        """Check if path should be included."""
        for part in path.parts:
            if part in EXCLUDE_DIRS:
                return False
        return True
