#!/usr/bin/env python3
"""
WAMA Dev AI - Command Line Interface

An intelligent development assistant inspired by Claude Code,
using local LLMs via Ollama.

Usage:
    python -m wama-dev-ai.cli
    python wama-dev-ai/cli.py
"""

import sys
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
import argparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.live import Live
from rich.spinner import Spinner
from rich.markdown import Markdown

from config import BASE_DIR, MODELS, WORKFLOWS, PROMPTS_DIR, OUTPUT_DIR
from ui.console import console
from ui.diff import DiffRenderer
from core.llm import LLMClient
from core.files import FileDiscovery
from core.tools import ToolRegistry, ToolCall


class WAMADevAI:
    """
    Main AI development assistant.

    Provides an interactive CLI for AI-assisted development.
    """

    def __init__(self):
        self.llm = LLMClient()
        self.files = FileDiscovery(llm_client=self.llm)
        self.tools = ToolRegistry(llm=self.llm)  # Pass LLM for semantic search (RAG)
        self.diff_renderer = DiffRenderer(console._console)
        self._conversation_mode = False
        # Persistent conversation state
        self._last_request = None
        self._last_messages = []
        self._last_executed_calls = set()

    # =========================================================================
    # Main Entry Points
    # =========================================================================

    def run_interactive(self):
        """Run interactive mode."""
        self._show_welcome()

        while True:
            try:
                self._interactive_loop()
            except KeyboardInterrupt:
                console.print("\n")
                if console.confirm("Exit WAMA Dev AI?", default=True):
                    console.success("Goodbye!")
                    break

    def run_task(self, task: str, workflow: str = "standard", target: Optional[str] = None):
        """
        Run a specific task.

        Args:
            task: Task description
            workflow: Workflow to use
            target: Target file/directory (optional)
        """
        console.header("WAMA Dev AI", f"Task: {task[:50]}...")

        # Find relevant files
        console.section("Finding Relevant Files")
        if target:
            target_path = Path(target)
            if target_path.is_file():
                files = [self.files._get_file_info(target_path)]
            else:
                files = self.files.list_directory(target_path)
        else:
            files = self.files.find_for_task(task)

        if not files:
            console.warning("No relevant files found")
            return

        console.file_list([f.path for f in files], f"Found {len(files)} relevant files")

        # Run workflow
        workflow_config = WORKFLOWS.get(workflow, WORKFLOWS["standard"])
        console.section(f"Running {workflow_config.name} Workflow")

        for i, model_name in enumerate(workflow_config.models, 1):
            model = MODELS.get(model_name)
            if not model:
                continue

            console.step(i, len(workflow_config.models), f"{model.name}: {model.description}")

            # Process each file
            for file_info in files:
                self._process_file(file_info.path, task, model_name)

    def _process_file(self, file_path: Path, task: str, model: str):
        """Process a single file with a model."""
        console.file_path(file_path, prefix="▶ ")

        try:
            original_content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            console.error(f"Cannot read file: {e}")
            return

        # Build prompt
        prompt = self._build_prompt(task, original_content, model)

        # Generate with spinner
        with console.spinner(f"Generating with {MODELS[model].name}..."):
            response = self.llm.generate(prompt, model=model)

        if not response.success:
            console.error(f"Generation failed: {response.error}")
            return

        # Extract code from response
        new_content = self.llm.extract_code(response.content)

        # Show diff
        if new_content != original_content:
            self.diff_renderer.render_diff(original_content, new_content, file_path)

            # Confirm changes
            if console.confirm("Apply these changes?", default=False):
                # Backup original
                backup_path = OUTPUT_DIR / f"{file_path.name}.bak"
                backup_path.write_text(original_content, encoding='utf-8')

                # Apply changes
                file_path.write_text(new_content, encoding='utf-8')
                console.success(f"Changes applied (backup: {backup_path.name})")
        else:
            console.info("No changes needed")

    # =========================================================================
    # Interactive Mode
    # =========================================================================

    def _show_welcome(self):
        """Show welcome message."""
        console.clear()
        console.header(
            "WAMA Dev AI",
            "AI-powered development assistant using local LLMs"
        )

        # Check available models
        console.section("Checking Models")
        available = self.llm.list_models()

        for role, model in MODELS.items():
            status = "✓" if any(model.ollama_id.split(":")[0] in m for m in available) else "✗"
            color = "green" if status == "✓" else "red"
            console.print(f"  [{color}]{status}[/] {model.name} ({role})")

        console.print()
        console.info("Type your request or use commands:")
        console.print("  [dim]/help[/]     - Show help")
        console.print("  [dim]/search[/]   - Search files")
        console.print("  [dim]/read[/]     - Read a file")
        console.print("  [dim]/workflow[/] - Run a workflow")
        console.print("  [dim]/exit[/]     - Exit")
        console.print()

    def _interactive_loop(self):
        """Main interactive loop."""
        user_input = console.prompt("You").strip()

        if not user_input:
            return

        # Handle commands
        if user_input.startswith("/"):
            self._handle_command(user_input)
            return

        # Handle natural language request
        self._handle_request(user_input)

    def _handle_command(self, command: str):
        """Handle slash commands."""
        parts = command[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "help":
            self._show_help()

        elif cmd == "search":
            if args:
                self._cmd_search(args)
            else:
                query = console.prompt("Search query")
                self._cmd_search(query)

        elif cmd == "read":
            if args:
                self._cmd_read(args)
            else:
                path = console.prompt("File path")
                self._cmd_read(path)

        elif cmd == "workflow":
            self._cmd_workflow(args)

        elif cmd == "models":
            self._cmd_models()

        elif cmd == "clear":
            console.clear()

        elif cmd in ("exit", "quit", "q"):
            raise KeyboardInterrupt

        else:
            console.warning(f"Unknown command: {cmd}")
            console.info("Type /help for available commands")

    def _handle_request(self, request: str):
        """Handle a natural language request with agentic tool loop."""
        console.thinking("Analyzing your request...")

        # Load system prompt
        system_prompt = self._load_prompt("system.txt")

        # Detect if this is a continuation request
        continue_keywords = ['continue', 'poursuivre', 'poursuit', 'continue', 'go on', 'keep going', 'suite', 'poursuis']
        is_continuation = (
            self._last_request and
            self._last_messages and
            any(kw in request.lower() for kw in continue_keywords)
        )

        if is_continuation:
            console.info(f"📌 Continuing previous request: {self._last_request[:50]}...")
            original_request = self._last_request
            messages = self._last_messages.copy()
            executed_tool_calls = self._last_executed_calls.copy()
            # Add continuation prompt
            user_prompt = f"""The user asked you to continue.

ORIGINAL REQUEST: {original_request}

IMPORTANT: You have already gathered information. NOW YOU MUST SYNTHESIZE IT.
DO NOT make any more tool calls. Instead:
1. Review all the information you collected in the conversation above
2. Provide a complete, structured answer to the original request
3. Use markdown formatting (tables, bullet points) for clarity

YOUR FINAL ANSWER:"""
        else:
            # New request - reset context
            original_request = request
            messages = []
            executed_tool_calls = set()
            # Build initial user prompt
            user_prompt = f"""User request: {request}

IMPORTANT: Make ONE tool call, then STOP and wait for results.

SMART SEARCH STRATEGY:
1. Use search_content(query) to find SPECIFIC functions/keywords and their LINE NUMBERS
2. Then read_file with start_line/end_line around those line numbers
3. This is MUCH faster than reading entire files section by section

Example: To find a preview function, search_content("showPreview") will show you exactly which files and lines contain it.

Do NOT assume file paths - wait for search results first."""

        # Save current request
        self._last_request = original_request

        # Agentic loop - continue until no more tool calls
        max_iterations = 25
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            remaining_iterations = max_iterations - iteration
            console.print()

            if iteration == 1:
                console.print(f"[bold cyan]🤖 Assistant:[/]")
            else:
                console.print(f"[bold cyan]🤖 Assistant (continuing):[/]")

            # Add iteration reminder to system prompt when getting close to limit
            iteration_reminder = ""
            if remaining_iterations <= 5:
                iteration_reminder = f"\n\n⚠️ IMPORTANT: Only {remaining_iterations} iterations remaining. You MUST provide a final answer soon. Synthesize what you have learned and respond to the user."
            elif remaining_iterations <= 10:
                iteration_reminder = f"\n\n📝 Note: {remaining_iterations} iterations remaining. Start preparing your final answer."

            current_system_prompt = system_prompt + iteration_reminder

            # Stream response, but stop after first tool call
            full_response = ""
            tool_call_detected = False
            printed_length = 0

            for chunk in self.llm.stream(user_prompt, model="dev", system_prompt=current_system_prompt, history=messages):
                full_response += chunk

                # Check if we've completed a tool call (closing tag or end of JSON)
                if not tool_call_detected and self._has_complete_tool_call(full_response):
                    tool_call_detected = True
                    # Truncate at the end of the tool call
                    full_response = self._truncate_after_tool_call(full_response)
                    # Print only the part not yet printed
                    remaining = full_response[printed_length:]
                    if remaining:
                        console.print(remaining, end="")
                    console.print()
                    break

                # Print chunk as it arrives
                console.print(chunk, end="")
                printed_length += len(chunk)

            if not tool_call_detected:
                console.print()  # Newline if no tool call

            console.print()

            # Save to message history
            messages.append({"role": "assistant", "content": full_response})

            # Check for tool calls
            tool_calls = self.tools.parse_tool_calls(full_response)

            # Debug: show if tool calls were found
            if tool_calls:
                console.info(f"Found {len(tool_calls)} tool call(s)")
            else:
                console.warning("No tool calls detected in response")
                # Show a snippet for debugging
                if '"name"' in full_response and '"arguments"' in full_response:
                    console.warning("Response contains JSON-like tool call but wasn't parsed")

            if not tool_calls:
                # No more tool calls, we're done
                break

            # Check for duplicate/looping tool calls
            new_tool_calls = []
            for call in tool_calls:
                # Create a signature for this tool call
                call_sig = self._get_tool_call_signature(call)

                # Debug: show the signature being checked
                console.print(f"[dim]  Checking: {call_sig[:80]}...[/]" if len(call_sig) > 80 else f"[dim]  Checking: {call_sig}[/]")

                if call_sig in executed_tool_calls:
                    console.warning(f"⚠ Duplicate tool call detected: {call.tool_name}")
                    console.warning(f"  This sig: {call_sig[:80]}")
                    # Show what's in history for debugging
                    console.print("[dim]  Previously executed:[/]")
                    for prev_sig in list(executed_tool_calls)[-5:]:  # Last 5
                        console.print(f"[dim]    - {prev_sig[:60]}...[/]")
                    console.warning("  Skipping this call.")
                    # Don't break immediately - just skip this call and continue
                    # Add guidance to help LLM progress
                    messages.append({"role": "user", "content": f"""
You already executed: {call.tool_name}({call.arguments})

Use the results from before. If you need MORE of a file, use DIFFERENT line numbers.
If you have enough information, proceed to edit_file."""})
                else:
                    new_tool_calls.append(call)
                    executed_tool_calls.add(call_sig)
                    console.print(f"[dim]  → New call, adding to history[/]")

            if not new_tool_calls:
                # All calls were duplicates - force synthesis
                console.warning("⚠ Duplicate tool calls detected. Forcing synthesis...")
                # Ask for synthesis one more time
                synthesis_prompt = f"""ORIGINAL REQUEST: {original_request}

⚠️ You've already gathered a lot of information but made a duplicate tool call.
NOW YOU MUST PROVIDE YOUR FINAL ANSWER.

DO NOT make any more tool calls. Synthesize what you have learned and provide a clear, structured response.
Use markdown formatting (tables, bullet points) for clarity.

YOUR FINAL ANSWER:"""
                messages.append({"role": "user", "content": synthesis_prompt})
                # Run one final synthesis pass
                for chunk in self.llm.stream(synthesis_prompt, model="dev", system_prompt=system_prompt, history=messages):
                    console.print(chunk, end="")
                console.print("\n")
                break

            tool_calls = new_tool_calls

            # Execute tool calls and collect results
            tool_results = self._execute_tool_calls_with_results(tool_calls)

            if not tool_results:
                # All tools were skipped or failed
                break

            # Build follow-up prompt with tool results
            results_text = "\n\n".join([
                f"### Tool: {r['tool']}\n**Result:**\n```\n{r['output'][:4000]}\n```"
                for r in tool_results
            ])

            user_prompt = f"""ORIGINAL REQUEST: {original_request}

Tool execution results:

{results_text}

Continue with the ORIGINAL REQUEST above. Focus on what the user asked for.
IMPORTANT: Do NOT repeat tool calls you already made. Check your history.
If you need more of a large file, use read_file with start_line/end_line.
If you're ready to make changes, use edit_file with exact strings from the file."""

            # Add user follow-up to history BEFORE next iteration
            # (stream() adds it to its local copy, but we need it in our history too)
            messages.append({"role": "user", "content": user_prompt})

        # Save conversation state for potential continuation
        self._last_messages = messages.copy()
        self._last_executed_calls = executed_tool_calls.copy()

        if iteration >= max_iterations:
            console.warning("Maximum iterations reached. You can type 'poursuivre' to continue.")

    def _execute_tool_calls_with_results(self, calls: List[ToolCall]) -> List[Dict[str, Any]]:
        """Execute tool calls and return results for the agentic loop."""
        results = []

        for call in calls:
            tool = self.tools.get(call.tool_name)
            if not tool:
                console.warning(f"Unknown tool: {call.tool_name}")
                continue

            # Show what we're about to do
            args_display = ", ".join(f"{k}={repr(v)[:50]}" for k, v in call.arguments.items())
            console.info(f"📎 {call.tool_name}({args_display})")

            if tool.requires_confirmation:
                if not console.confirm("Execute this tool?", default=False):
                    console.info("Skipped by user")
                    results.append({
                        "tool": call.tool_name,
                        "output": "SKIPPED: User declined to execute this tool."
                    })
                    continue

            result = self.tools.execute(call)

            if result.success:
                console.success(f"✓ {call.tool_name} completed")
                # Show preview of output - larger for read_file
                if result.output:
                    max_preview = 2000 if call.tool_name == "read_file" else 500
                    preview = result.output[:max_preview]
                    if len(result.output) > max_preview:
                        preview += f"\n... ({len(result.output)} chars total)"
                    console.code(preview, language="text")

                results.append({
                    "tool": call.tool_name,
                    "output": result.output
                })
            else:
                console.error(f"✗ {call.tool_name} failed: {result.error}")
                results.append({
                    "tool": call.tool_name,
                    "output": f"ERROR: {result.error}"
                })

        return results

    def _execute_tool_calls(self, calls: List[ToolCall]):
        """Execute tool calls from the LLM response."""
        for call in calls:
            tool = self.tools.get(call.tool_name)
            if not tool:
                console.warning(f"Unknown tool: {call.tool_name}")
                continue

            console.info(f"Tool: {call.tool_name}({call.arguments})")

            if tool.requires_confirmation:
                if not console.confirm("Execute this tool?", default=False):
                    console.info("Skipped")
                    continue

            result = self.tools.execute(call)
            if result.success:
                console.success("Tool executed successfully")
                if result.output:
                    console.code(result.output[:500], language="text")
            else:
                console.error(f"Tool failed: {result.error}")

    # =========================================================================
    # Tool Call Detection Helpers
    # =========================================================================

    def _get_tool_call_signature(self, call: ToolCall) -> str:
        """Create a unique signature for a tool call to detect duplicates."""
        # For read_file, include start_line/end_line to allow reading different sections
        # For other tools, just use the full arguments
        args = call.arguments.copy()

        # Normalize path argument
        if 'path' in args:
            args['path'] = str(args['path']).replace('\\', '/')

        return f"{call.tool_name}:{json.dumps(args, sort_keys=True)}"

    def _has_complete_tool_call(self, text: str) -> bool:
        """Check if text contains a complete tool call (JSON format)."""
        # List of tool names to detect
        tool_names = 'search_files|search_content|read_file|write_file|edit_file|list_directory|run_command|get_project_info'

        # Look for complete JSON tool calls - simpler patterns
        patterns = [
            r'</tool_call>',  # End of XML format
            rf'"name"\s*:\s*"({tool_names})"\s*,\s*"arguments"\s*:\s*\{{[^}}]+\}}',  # JSON with tool name and args
        ]
        for pattern in patterns:
            if re.search(pattern, text, re.DOTALL):
                return True
        return False

    def _truncate_after_tool_call(self, text: str) -> str:
        """Truncate text after the first complete tool call."""
        tool_names = 'search_files|search_content|read_file|write_file|edit_file|list_directory|run_command|get_project_info'

        # Find end of XML tool call
        xml_match = re.search(r'</tool_call>', text)
        if xml_match:
            return text[:xml_match.end()]

        # Find end of JSON tool call with arguments
        # Match: {"name": "tool", "arguments": {...}}
        json_match = re.search(rf'"name"\s*:\s*"({tool_names})"\s*,\s*"arguments"\s*:\s*\{{[^}}]+\}}\s*\}}', text, re.DOTALL)
        if json_match:
            return text[:json_match.end()]

        return text

    # =========================================================================
    # Commands
    # =========================================================================

    def _show_help(self):
        """Show help information."""
        console.panel("""
[bold]WAMA Dev AI Commands[/bold]

[cyan]/help[/]              Show this help
[cyan]/search <query>[/]    Search for files by content or name
[cyan]/read <path>[/]       Read and display a file
[cyan]/workflow[/]          Run a development workflow
[cyan]/models[/]            Show available models
[cyan]/clear[/]             Clear the screen
[cyan]/exit[/]              Exit the application

[bold]Natural Language[/bold]

Just type your request in natural language:
- "Fix the bug in views.py where..."
- "Add a new API endpoint for..."
- "Explain how the imager backend works"
- "Refactor the transcriber to..."
        """, title="Help")

    def _cmd_search(self, query: str):
        """Search for files."""
        console.info(f"Searching for: {query}")

        # Try content search
        results = self.files.find_by_content(query)

        if not results:
            # Try name search
            results = self.files.find_by_name(f"*{query}*")

        if results:
            console.file_tree([f.path for f in results[:20]], f"Found {len(results)} files")
        else:
            console.warning("No files found")

    def _cmd_read(self, path: str):
        """Read and display a file."""
        file_path = BASE_DIR / path

        if not file_path.exists():
            console.error(f"File not found: {path}")
            return

        try:
            content = file_path.read_text(encoding='utf-8')
            lang = "python" if file_path.suffix == ".py" else file_path.suffix[1:]
            console.code(content, language=lang, title=str(path))
        except Exception as e:
            console.error(f"Cannot read file: {e}")

    def _cmd_workflow(self, args: str):
        """Run a workflow."""
        # Show workflow options
        console.print("[bold]Available Workflows:[/bold]")
        for name, wf in WORKFLOWS.items():
            console.print(f"  [cyan]{name}[/]: {wf.description}")

        workflow = console.prompt("Choose workflow", default="standard")
        if workflow not in WORKFLOWS:
            console.warning("Invalid workflow")
            return

        task = console.prompt("Describe your task")
        target = console.prompt("Target (file/folder, or Enter for auto)", default="")

        self.run_task(task, workflow, target or None)

    def _cmd_models(self):
        """Show model information."""
        console.section("Available Models")

        available = self.llm.list_models()

        data = []
        for role, model in MODELS.items():
            is_available = any(model.ollama_id.split(":")[0] in m for m in available)
            data.append({
                "role": role,
                "name": model.name,
                "model_id": model.ollama_id,
                "status": "✓ Available" if is_available else "✗ Not installed",
            })

        console.table(data, columns=["role", "name", "model_id", "status"])

    # =========================================================================
    # Utilities
    # =========================================================================

    def _load_prompt(self, name: str) -> str:
        """Load a prompt template."""
        path = PROMPTS_DIR / name
        if path.exists():
            return path.read_text(encoding='utf-8')
        return ""

    def _build_prompt(self, task: str, code: str, model: str) -> str:
        """Build a prompt for a specific model role."""
        if model == "dev":
            template = self._load_prompt("dev.txt")
            return template.format(task=task, files=code[:4000])

        elif model == "debug":
            template = self._load_prompt("debug.txt")
            return template.format(code=code[:4000])

        elif model == "architect":
            template = self._load_prompt("architect.txt")
            return template.format(code=code[:4000])

        else:
            return f"Task: {task}\n\nCode:\n{code[:4000]}"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WAMA Dev AI - AI-powered development assistant"
    )
    parser.add_argument(
        "-t", "--task",
        help="Task to execute (non-interactive mode)"
    )
    parser.add_argument(
        "-w", "--workflow",
        default="standard",
        choices=list(WORKFLOWS.keys()),
        help="Workflow to use"
    )
    parser.add_argument(
        "-f", "--file",
        help="Target file or directory"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="WAMA Dev AI 0.1.0"
    )

    args = parser.parse_args()

    app = WAMADevAI()

    if args.task:
        # Non-interactive mode
        app.run_task(args.task, args.workflow, args.file)
    else:
        # Interactive mode
        app.run_interactive()


if __name__ == "__main__":
    main()
