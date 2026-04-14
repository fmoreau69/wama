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
    OLLAMA_HOST,
    select_model_for_role, get_memory_status,
    WAMA_BASE_URL, WAMA_USERNAME, WAMA_PASSWORD,
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
# VRAM Pre-flight
# =============================================================================

def _free_ollama_models(ollama_host: str = OLLAMA_HOST, verbose: bool = True) -> bool:
    """
    Unload all models currently resident in Ollama (frees VRAM and RAM).
    Uses Ollama's /api/ps endpoint to list loaded models, then sends
    keep_alive=0 to each one to trigger immediate unloading.
    """
    try:
        import requests

        resp = requests.get(f"{ollama_host}/api/ps", timeout=5)
        if resp.status_code != 200:
            if verbose:
                print(f"[Ollama] /api/ps returned {resp.status_code} — skipping unload")
            return False

        models = resp.json().get("models", [])
        if not models:
            if verbose:
                print("[Ollama] No models currently loaded")
            return True

        for m in models:
            name = m.get("name", "")
            size_mb = m.get("size", 0) / (1024 ** 2)
            vram_mb = m.get("size_vram", 0) / (1024 ** 2)
            requests.post(
                f"{ollama_host}/api/generate",
                json={"model": name, "keep_alive": 0, "prompt": ""},
                timeout=15,
            )
            if verbose:
                print(f"[Ollama] Unloaded: {name} "
                      f"(RAM {size_mb:.0f} MB / VRAM {vram_mb:.0f} MB)")

        return True

    except Exception as e:
        if verbose:
            print(f"[Ollama] Error unloading models: {e} — skipping")
        return False


def _free_wama_vram(base_url: str, username: str, password: str, verbose: bool = True) -> bool:
    """
    Call WAMA's model-manager clear-gpu API to free GPU VRAM before model selection.
    Uses Django session auth (username + password from env vars).
    Returns True if VRAM was successfully cleared.
    """
    try:
        import re
        import requests

        session = requests.Session()
        login_url = f"{base_url}/accounts/login/"

        # Step 1: GET login page → extract CSRF token
        resp = session.get(login_url, timeout=5)
        csrf = session.cookies.get('csrftoken', '')
        if not csrf:
            m = re.search(r'csrfmiddlewaretoken[^>]+value=["\'](\w+)["\']', resp.text)
            if m:
                csrf = m.group(1)
        if not csrf:
            if verbose:
                print("[VRAM] Cannot extract CSRF token — skipping")
            return False

        # Step 2: POST login
        resp = session.post(
            login_url,
            data={'username': username, 'password': password, 'csrfmiddlewaretoken': csrf},
            headers={'Referer': login_url},
            timeout=10,
            allow_redirects=True,
        )
        if '/accounts/login' in resp.url:
            if verbose:
                print("[VRAM] Login failed (bad credentials?) — skipping")
            return False

        # Step 3: POST clear-gpu
        csrf = session.cookies.get('csrftoken', csrf)
        resp = session.post(
            f"{base_url}/model-manager/api/clear-gpu/",
            headers={'X-CSRFToken': csrf, 'Referer': f"{base_url}/model-manager/"},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if verbose:
                mem = data.get('memory', {})
                free_gb = mem.get('free_gb', '?')
                print(f"[VRAM] GPU memory cleared — {free_gb} GiB free")
            return True
        else:
            if verbose:
                print(f"[VRAM] API returned {resp.status_code} — skipping")
            return False

    except requests.exceptions.ConnectionError:
        if verbose:
            print("[VRAM] WAMA inaccessible (serveur arrêté ?) — skipping GPU clear")
        return False
    except Exception as e:
        if verbose:
            print(f"[VRAM] Error: {e} — skipping")
        return False


def _get_free_vram_gb() -> float:
    """Return free GPU VRAM in GiB via nvidia-smi. Returns 0 if no GPU."""
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().split('\n')[0]) / 1024
    except Exception:
        pass
    return 0.0


# Thinking models generate long <think>...</think> blocks for complex tasks.
# They must have /no_think injected and a larger num_ctx to avoid EOF crashes.
_THINKING_MODEL_PATTERNS = ('qwen3', 'qwq', 'deepseek-r1', 'marco-o1')


def _is_thinking_model(model_id: str) -> bool:
    return any(p in model_id.lower() for p in _THINKING_MODEL_PATTERNS)


def _compute_num_ctx(free_vram_gb: float) -> int:
    """
    Choose num_ctx based on available VRAM.
    Thinking models need enough space for the think block + response.
    KV cache grows linearly with num_ctx (Qwen3 9B: ~128 MB per 1024 tokens).
    """
    if free_vram_gb >= 12:
        return 16384   # ~1.9 GB KV — safe with 9B model (5 GB) on 15+ GB free VRAM
    elif free_vram_gb >= 7:
        return 8192    # ~0.95 GB KV
    else:
        return 4096    # ~0.47 GB KV — last resort (may still fail for thinking models)


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
                "Available tools:\n{tools}\n"
                "Call tools using: <tool_call>{\"name\": \"TOOL\", \"arguments\": {}}</tool_call>\n"
                "Write reports using write_report tool only. Task: {task}"
            )

    def _autosave_report(self, text: str) -> None:
        """
        Fallback: if the model produced a report inline (didn't call write_report),
        save the full last response as a .md file so no work is lost.
        """
        date_str = datetime.now().strftime('%Y-%m-%d_%H-%M')
        filename = f"audit_{date_str}_autosave.md"
        out_path = OUTPUT_DIR / filename
        out_path.write_text(text, encoding='utf-8')
        self._report_saved = True
        if self.verbose:
            print(f"[Audit] Auto-saved response → {filename}")

    def run(self, task: str) -> str:
        """
        Run the audit agent for a given task.
        Returns the final text response from the model.
        """
        self._report_saved = False  # track whether write_report was called
        if self.verbose:
            print(f"\n[Audit] Task: {task}\n")

        # Inject tools list and task into system prompt
        tools_desc = self.tools.get_tools_description()
        system = (self._system_prompt
                  .replace("{tools}", tools_desc)
                  .replace("{task}", task))

        model_id = self._model_cfg.ollama_id if self._model_cfg else "qwen3.5:9b"

        # Compute num_ctx from actual free VRAM (not system RAM).
        # Thinking models need larger context for their <think> blocks.
        free_vram = _get_free_vram_gb()
        num_ctx = _compute_num_ctx(free_vram)
        thinking = _is_thinking_model(model_id)
        if self.verbose:
            print(f"[Audit] VRAM free: {free_vram:.1f} GiB → num_ctx={num_ctx}"
                  f"{' (thinking model → /no_think)' if thinking else ''}")

        # For thinking models, /no_think disables the <think> block so the model
        # responds directly — saves thousands of tokens and avoids context overflow.
        first_user = ("/no_think\n" if thinking else "") + task

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": first_user},
        ]

        rounds = 0
        while rounds < self.MAX_TOOL_ROUNDS:
            rounds += 1

            # Call LLM directly via Ollama client (LLMClient.chat() manages its own
            # internal history — we bypass it to control multi-turn context ourselves).
            # num_ctx is computed from free VRAM to avoid EOF/OOM crashes.
            raw = self.llm._client.chat(
                model=model_id,
                messages=messages,
                options={"temperature": 0.3, "num_ctx": num_ctx},
            )
            response_text = raw["message"]["content"]
            # Strip hallucinated DeepSeek <｜tool▁outputs▁begin｜>...<｜tool▁outputs▁end｜> blocks
            # before parsing, so they don't pollute context or confuse the parser.
            response_text = ToolRegistry.strip_deepseek_tool_outputs(response_text)

            if self.verbose:
                print(f"\n[Round {rounds}] Model response:\n{response_text[:500]}...\n")

            # Parse tool calls
            tool_calls = self.tools.parse_tool_calls(response_text)

            if not tool_calls:
                # No more tool calls — agent is done.
                # If the response contains a report (JSON/markdown) but write_report
                # was never called, auto-save it so we don't lose the work.
                if not self._report_saved:
                    self._autosave_report(response_text)
                if self.verbose:
                    print("[Audit] Agent finished (no more tool calls).")
                return response_text

            # Execute tool calls
            tool_results = []
            for call in tool_calls:
                result = self.tools.execute(call)
                if call.tool_name == "write_report" and result.success:
                    self._report_saved = True
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
        if not self._report_saved:
            self._autosave_report(response_text)
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
        default="audit",
        choices=["audit", "dev", "debug", "architect", "fast", "ultra_fast"],
        help="Model role to use (default: audit → gemma4:e4b, non-thinking)",
    )
    parser.add_argument(
        "--non-interactive", "-n",
        action="store_true",
        help="Non-interactive mode (for cron/scheduled runs)",
    )
    parser.add_argument(
        "--no-free-vram",
        action="store_true",
        help="Skip automatic VRAM clearing before model selection",
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

    # Step 1: Unload all Ollama models from VRAM/RAM (Ollama keeps models resident
    # by default for 5 min — this often occupies 2-8 GB that blocks the audit model).
    if not args.no_free_vram:
        print(f"[wama-dev-ai] Déchargement des modèles Ollama ({OLLAMA_HOST})…")
        unloaded = _free_ollama_models(OLLAMA_HOST, verbose=True)
        if unloaded:
            import time
            time.sleep(1)

        # Show which processes are using VRAM (helps diagnose residual usage)
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-compute-apps=pid,process_name,used_memory",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print("[VRAM] Processus GPU actifs :")
                for line in result.stdout.strip().splitlines():
                    print(f"  {line}")
            else:
                print("[VRAM] Aucun processus GPU détecté par nvidia-smi")
        except Exception:
            pass  # nvidia-smi not available

    # Step 2: Free WAMA GPU cache (PyTorch) via WAMA API.
    # Password: from WAMA_PASSWORD env var, or prompted interactively if username is known.
    wama_password = WAMA_PASSWORD
    if not args.no_free_vram and WAMA_USERNAME and not wama_password and verbose:
        import getpass
        wama_password = getpass.getpass(
            f"[wama-dev-ai] Mot de passe WAMA pour '{WAMA_USERNAME}': "
        )

    if not args.no_free_vram and WAMA_USERNAME and wama_password:
        print(f"[wama-dev-ai] Libération VRAM via WAMA API ({WAMA_BASE_URL})…")
        freed = _free_wama_vram(WAMA_BASE_URL, WAMA_USERNAME, wama_password, verbose=True)
        if freed:
            import time
            time.sleep(2)  # Give the GPU a moment to settle

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
