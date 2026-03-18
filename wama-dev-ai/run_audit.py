#!/usr/bin/env python3
"""
wama-dev-ai — Audit Runner (Phase 1)

READ-ONLY mode: analyses the WAMA codebase and writes structured reports
to wama-dev-ai/outputs/ for review by Claude + human.

NO code is written or modified.  NO git interaction.

Usage:
    python wama-dev-ai/run_audit.py
    python wama-dev-ai/run_audit.py --task "UI compliance check"
    python wama-dev-ai/run_audit.py --model fast
    python wama-dev-ai/run_audit.py --non-interactive   # for cron jobs

Cron example (nightly at 2am):
    0 2 * * * cd /path/to/wama && python wama-dev-ai/run_audit.py --non-interactive >> logs/audit.log 2>&1
"""

import sys
import os
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Bypass proxy for localhost BEFORE any other imports
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
os.chdir(PROJECT_DIR)

from config import (
    BASE_DIR, OUTPUT_DIR, PROMPTS_DIR,
    select_model_for_role, get_memory_status,
)
from core.llm import LLMClient
from core.tools import ToolRegistry, ToolCall, Tool, ToolResult
from core.history import ConversationHistory

logger = logging.getLogger(__name__)


# =============================================================================
# Restricted ToolRegistry for audit mode
# =============================================================================

class AuditToolRegistry(ToolRegistry):
    """
    ToolRegistry with dangerous tools removed and write_report added.

    Allowed  : read_file, search_files, search_content, list_directory,
               get_project_info, find_related, write_report
    Disabled : write_file, edit_file, run_command
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._disable_dangerous_tools()
        self._register_audit_tools()

    def _disable_dangerous_tools(self):
        """Remove tools that could modify the codebase."""
        for name in ('write_file', 'edit_file', 'run_command'):
            if name in self._tools:
                del self._tools[name]
                logger.debug(f"[audit] Disabled tool: {name}")

    def _register_audit_tools(self):
        """Register audit-specific tools."""

        def _write_report(filename: str, content: str) -> str:
            """Write a report to the outputs/ directory."""
            # Security: only allow writes inside OUTPUT_DIR
            if '..' in filename or '/' in filename or '\\' in filename:
                raise ValueError("Invalid filename: path traversal not allowed")
            if not filename.endswith(('.json', '.md', '.txt')):
                raise ValueError("Report must be .json, .md or .txt")

            out_path = OUTPUT_DIR / filename
            out_path.write_text(content, encoding='utf-8')
            return f"Report written: {out_path} ({len(content)} bytes)"

        self.register(Tool(
            name="write_report",
            description=(
                "Write an audit report to the outputs/ folder. "
                "ONLY allowed write operation in audit mode. "
                "filename must not contain path separators. "
                "Supported extensions: .json, .md, .txt"
            ),
            parameters={
                "filename": {
                    "type": "string",
                    "description": "Report filename (e.g. 'audit_2026-03-18.json')",
                },
                "content": {
                    "type": "string",
                    "description": "Report content (JSON string or markdown)",
                },
            },
            function=_write_report,
            requires_confirmation=False,
        ))


# =============================================================================
# Audit Agent
# =============================================================================

class AuditAgent:
    """
    Minimal agent loop for audit mode.
    Uses AuditToolRegistry (read-only + write_report).
    Suitable for interactive use and cron/non-interactive use.
    """

    MAX_TOOL_ROUNDS = 20   # Safety: stop after N tool call rounds

    def __init__(self, model_role: str = "architect", verbose: bool = True):
        self.llm = LLMClient()
        self.tools = AuditToolRegistry(llm=self.llm)
        self.verbose = verbose

        # Adaptive model selection
        try:
            mem = get_memory_status()
            if verbose:
                print(f"[Audit] Memory: {mem['available_gb']:.1f} GiB available")
            self._model_key, self._model_cfg = select_model_for_role(model_role, verbose=verbose)
            if verbose:
                print(f"[Audit] Model: {self._model_cfg.name} ({self._model_cfg.ollama_id})")
        except RuntimeError as e:
            print(f"[Audit] WARNING: {e}")
            self._model_key = "fast"
            self._model_cfg = None

        # Load audit system prompt
        audit_prompt_path = PROMPTS_DIR / "audit.txt"
        if audit_prompt_path.exists():
            self._system_prompt = audit_prompt_path.read_text(encoding='utf-8')
        else:
            self._system_prompt = (
                "You are wama-dev-ai in AUDIT MODE. "
                "Analyse the WAMA codebase read-only. "
                "Write reports using write_report tool only."
            )

    def run(self, task: str) -> str:
        """
        Run the audit agent for a given task.
        Returns the final text response from the model.
        """
        if self.verbose:
            print(f"\n[Audit] Task: {task}\n")

        # Inject task into system prompt
        system = self._system_prompt.replace("{task}", task)

        model_id = self._model_cfg.ollama_id if self._model_cfg else "qwen3.5:9b"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

        rounds = 0
        while rounds < self.MAX_TOOL_ROUNDS:
            rounds += 1

            # Call LLM
            response_text = self.llm.chat(
                messages=messages,
                model=model_id,
                temperature=0.3,
                stream=False,
            )

            if self.verbose:
                print(f"\n[Round {rounds}] Model response:\n{response_text[:500]}...\n")

            # Parse tool calls
            tool_calls = self.tools.parse_tool_calls(response_text)

            if not tool_calls:
                # No more tool calls — agent is done
                if self.verbose:
                    print("[Audit] Agent finished (no more tool calls).")
                return response_text

            # Execute tool calls
            tool_results = []
            for call in tool_calls:
                result = self.tools.execute(call)
                if self.verbose:
                    status = "✓" if result.success else "✗"
                    print(f"  {status} {call.tool_name}({list(call.arguments.keys())}) "
                          f"→ {result.output[:100] if result.success else result.error}")
                tool_results.append((call, result))

            # Add assistant turn + tool results to messages
            messages.append({"role": "assistant", "content": response_text})

            tool_result_text = "\n".join(
                f"[{call.tool_name}] {'OK: ' + result.output[:200] if result.success else 'ERROR: ' + result.error}"
                for call, result in tool_results
            )
            messages.append({"role": "user", "content": f"Tool results:\n{tool_result_text}"})

        if self.verbose:
            print(f"[Audit] WARNING: reached MAX_TOOL_ROUNDS ({self.MAX_TOOL_ROUNDS})")
        return "Audit reached maximum rounds without completing."


# =============================================================================
# Entry point
# =============================================================================

DEFAULT_TASK = """
Run a full audit of the WAMA codebase covering:
1. HuggingFace model integration rule compliance (CLAUDE.md)
2. UI compliance — duplication button in queue-based apps
3. Static files sync (wama/*/static/ vs staticfiles/)
4. Dead code detection (TODO/FIXME, unused functions)
5. Quick dependency check (requirements.txt vs imports)

Write a consolidated JSON report to outputs/audit_{date}.json
where {date} is today's date in YYYY-MM-DD format.
""".strip()


def main():
    parser = argparse.ArgumentParser(description="wama-dev-ai Audit Runner")
    parser.add_argument(
        "--task", "-t",
        default=DEFAULT_TASK,
        help="Audit task description (default: full audit)",
    )
    parser.add_argument(
        "--model", "-m",
        default="architect",
        choices=["dev", "debug", "architect", "fast", "ultra_fast"],
        help="Model role to use (default: architect)",
    )
    parser.add_argument(
        "--non-interactive", "-n",
        action="store_true",
        help="Non-interactive mode (for cron/scheduled runs)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        )
    else:
        logging.basicConfig(level=logging.WARNING)

    verbose = not args.non_interactive

    print(f"[wama-dev-ai] Audit mode — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"[wama-dev-ai] Outputs: {OUTPUT_DIR}")

    agent = AuditAgent(model_role=args.model, verbose=verbose)
    result = agent.run(args.task)

    if not verbose:
        # In non-interactive mode, print a brief summary
        print(f"[wama-dev-ai] Audit complete. Check {OUTPUT_DIR} for reports.")

    # List reports written during this session
    reports = sorted(OUTPUT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if reports:
        print(f"\n[wama-dev-ai] Reports available:")
        for r in reports[:5]:
            print(f"  - {r.name} ({r.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
