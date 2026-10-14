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
import types
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Bypass proxy for localhost BEFORE any other imports
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.resolve()
MEMORY_PATH = SCRIPT_DIR / "memory.json"
sys.path.insert(0, str(SCRIPT_DIR))
# La RACINE du dépôt sur le chemin d'import : `os.chdir` ne l'y met pas (Python n'ajoute que
# le dossier du script). Sans elle, `wama.common.*` n'est pas importable depuis ici.
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(PROJECT_DIR)


# =============================================================================
# Persistent memory helpers
# =============================================================================

def _load_memory() -> dict:
    """Load persistent memory from wama-dev-ai/memory.json."""
    try:
        if MEMORY_PATH.exists():
            return json.loads(MEMORY_PATH.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_memory(data: dict) -> None:
    """Save persistent memory to wama-dev-ai/memory.json."""
    data['last_updated'] = datetime.now().strftime('%Y-%m-%d')
    MEMORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _format_memory_for_prompt(memory: dict) -> str:
    """Format memory dict as a concise text block for injection into system prompt."""
    if not memory:
        return ""
    lines = ["## Mémoire persistante wama-dev-ai\n"]
    if memory.get("known_issues"):
        lines.append("### Bugs bloquants connus")
        for k, v in memory["known_issues"].items():
            status = v.get("status", "?")
            symptom = v.get("symptom", "")
            lines.append(f"- **{k}** [{status}]: {symptom}")
        lines.append("")
    if memory.get("rules"):
        lines.append("### Règles importantes")
        for k, v in memory["rules"].items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    if memory.get("recent_implementations"):
        lines.append("### Implémentations récentes")
        for date, items in sorted(memory["recent_implementations"].items(), reverse=True)[:2]:
            lines.append(f"- {date}: " + "; ".join(items[:3]))
        lines.append("")
    if memory.get("persistent_notes"):
        lines.append("### Notes persistantes")
        for k, v in memory["persistent_notes"].items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    return "\n".join(lines)

# DJANGO, COMME LES SIX RÔLES (2026-10-13). L'audit s'en passait — le choix était consigné ici
# le 2026-09-07 : « un import cassé dans une app ne peut pas l'empêcher de tourner ». Il en
# payait le prix ailleurs : sans le gouverneur (réglages, registre Redis, catalogue), il ne
# pouvait que DÉCHARGER TOUT Ollama au début et à la fin de chaque run — le modèle de
# l'assistant compris, en pleine conversation —, et demander par l'API web, avec un mot de
# passe en clair dans `.env`, un vidage qui ne touchait que le process web. Un import cassé
# dans une app casse WAMA entier ; l'audit le dit désormais au lieu de tourner à côté.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402

django.setup()

from config import (  # noqa: E402
    BASE_DIR, OUTPUT_DIR, PROMPTS_DIR,
    select_model_for_role, get_memory_status,
)
# Adresse d'Ollama : la brique COMMUNE, comme les 5 rôles (2026-09-07).
#
# Ce fichier lisait `config.OLLAMA_HOST` BRUT, donc `http://127.0.0.1:11434` — qui depuis
# WSL2 désigne la VM Linux et PAS l'hôte Windows où tourne Ollama. Il ne fonctionnait que
# par accident d'environnement (un shell ou un cron qui exporte `OLLAMA_HOST`) : c'est
# exactement le piège n°1 que la brique commune documente et corrige.
from wama.common.utils.ollama_host import ollama_base  # noqa: E402
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

        def _write_memory(key: str, value, subkey: str = None) -> str:
            """Persist a fact to wama-dev-ai/memory.json.
            Use key='persistent_notes' + subkey='my_note' to add a free-form note.
            Use key='known_issues' + subkey='issue_name' + value={'status':..., 'symptom':...}.
            """
            data = _load_memory()
            if subkey:
                if key not in data or not isinstance(data[key], dict):
                    data[key] = {}
                data[key][subkey] = value
            else:
                data[key] = value
            _save_memory(data)
            return f"Memory updated: {key}{'.' + subkey if subkey else ''} = {str(value)[:120]}"

        self.register(Tool(
            name="write_memory",
            description=(
                "Persist a fact or finding to wama-dev-ai/memory.json for future sessions. "
                "Use for important bugs, architectural insights, or rules discovered during audit. "
                "key: top-level key (e.g. 'known_issues', 'persistent_notes'). "
                "subkey: optional nested key (e.g. issue name or note title). "
                "value: the content to store (string, dict, or list)."
            ),
            parameters={
                "key": {
                    "type": "string",
                    "description": "Top-level memory key: 'known_issues' | 'persistent_notes' | 'recent_implementations'",
                },
                "value": {
                    "type": "string",
                    "description": "Value to store (string description or JSON-encoded object)",
                },
                "subkey": {
                    "type": "string",
                    "description": "(optional) Nested key under the top-level key",
                },
            },
            function=_write_memory,
            requires_confirmation=False,
        ))


# =============================================================================
# VRAM — le gouverneur, pas un déchargement d'office (2026-10-13)
# =============================================================================
# Ce bloc portait `_free_ollama_models` — décharger TOUS les modèles d'Ollama, au début ET à la
# fin de chaque run, le modèle de l'assistant compris — et `_free_wama_vram`, un vidage par
# l'API web (`/model-manager/api/clear-gpu/`, mot de passe lu dans `.env`) qui ne vidait que le
# process WEB, pas les workers qui tiennent la carte. La règle du gouverneur (B1, Fabien, 16 et
# 20/09) dit l'inverse : on ATTEND ; libérer la carte n'intervient que sur ACCORD EXPLICITE, par
# le canal commun. C'est `role_utils.local_llm_guard` qui l'applique, comme pour les six rôles ;
# l'accord est l'option `--free-vram`.

def _release_own_model(model_id: str, verbose: bool = True) -> bool:
    """Décharge le SEUL modèle de ce run, par la brique commune (`MemoryManager.unload_model` :
    `keep_alive: 0` sur ce modèle, et retrait de sa ligne de résidence au gouverneur)."""
    from wama.model_manager.services.memory_manager import MemoryManager
    from wama.common.utils.model_keys import catalog_key
    ok = MemoryManager.unload_model(catalog_key(model_id, 'ollama'))
    if verbose:
        print(f"[Audit] {model_id} {'déchargé' if ok else 'NON déchargé (voir le journal)'}")
    return ok


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
#
# ⚠ ON DEMANDE À OLLAMA, ON NE DEVINE PLUS (2026-08-20, recadrage Fabien).
# L'ancien test était `any(p in model_id for p in ('qwen3', 'qwq', 'deepseek-r1', 'marco-o1'))`.
# Le motif 'qwen3' attrapait TOUTE la famille — qwen3.5, qwen3.6, qwen3.8, qwen3-coder — sans
# rien savoir d'aucune, et un modèle découvert dynamiquement (`auto:<tag>`) n'était classé que
# par la forme de son nom. Or `/api/show` expose la vérité : `capabilities` contient "thinking"
# quand le modèle sait raisonner. Injecter `/no_think` à un modèle qui ne connaît pas la
# directive lui envoie du texte parasite qu'il traite comme du contenu utilisateur ; l'omettre
# sur un vrai modèle de raisonnement produit des blocs <think> à rallonge et des EOF.
#
# Les motifs ne subsistent QUE comme repli si Ollama est injoignable — et ils sont resserrés :
# 'qwen3' est retiré, la famille étant désormais résolue par capacité.
_THINKING_FALLBACK_PATTERNS = ('qwq', 'deepseek-r1', 'marco-o1', 'thinking')

#: Cache par identifiant de modèle — `/api/show` est un appel réseau, appelé à chaque run.
_THINKING_CACHE: dict = {}


def _is_thinking_model(model_id: str, ollama_host: str = None) -> bool:
    """
    Le modèle sait-il produire un bloc <think> ? Réponse d'Ollama, pas du nom du modèle.

    Repli sur les motifs si Ollama ne répond pas (hôte éteint, modèle absent) : mieux vaut une
    heuristique étroite qu'une exception au milieu d'un audit.
    """
    key = (model_id or "").lower()
    if key in _THINKING_CACHE:
        return _THINKING_CACHE[key]

    result = None
    try:
        import requests
        resp = requests.post(
            f"{ollama_host or ollama_base()}/api/show",
            json={"model": model_id},
            timeout=10,
        )
        if resp.ok:
            caps = resp.json().get("capabilities") or []
            result = "thinking" in [str(c).lower() for c in caps]
    except Exception:
        result = None   # Ollama muet → repli

    if result is None:
        result = any(p in key for p in _THINKING_FALLBACK_PATTERNS)

    _THINKING_CACHE[key] = result
    return result


#: Familles qui comprennent la directive texte `/no_think`. C'est une convention **Qwen**, pas un
#: standard : mesuré le 2026-08-20, `gemma4:e4b` DÉCLARE la capacité `thinking` mais n'a jamais
#: connu `/no_think` — la lui envoyer ajouterait du texte parasite traité comme contenu utilisateur.
_NO_THINK_FAMILIES = ('qwen',)


def _honors_no_think(model_id: str) -> bool:
    """
    Le modèle comprend-il `/no_think` ? Question DISTINCTE de « sait-il penser ».

    ⚠ DETTE ASSUMÉE : la bonne réponse durable n'est pas une liste de familles mais le paramètre
    d'API `think: false` (Ollama ≥ 0.9), qui coupe le raisonnement quelle que soit la famille et
    sans toucher au prompt. Le basculement suppose de modifier la construction des requêtes dans
    `core/llm.py` — hors périmètre ici, où l'on ne veut RIEN changer à la stabilité éprouvée du
    rôle `audit`. À faire dès qu'on retouche `llm.py`.
    """
    return any(f in (model_id or "").lower() for f in _NO_THINK_FAMILIES)


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

    # 20 était trop bas pour une cartographie : le 2026-08-20 une passe a consommé ses 20 tours
    # en navigation et recherches cassées, sans lire un fichier. Une passe réelle lit des dizaines
    # de fichiers ; le garde-fou doit borner une boucle folle, pas un travail normal.
    MAX_TOOL_ROUNDS = 80   # Safety: stop after N tool call rounds

    # Stable last-resort model: non-thinking, light, leaves VRAM headroom on a shared
    # 24 GB host (qwen3-coder:30b is too heavy for agentic use; qwen3.5:9b EOFs on this
    # Ollama build). Empirically the only one that completes audits reliably here.
    _FALLBACK_MODEL = "gemma4:e4b"

    def __init__(self, model_role: str = "architect", verbose: bool = True,
                 force_model: str = None, prompt: str = "audit"):
        self.llm = LLMClient()
        self.tools = AuditToolRegistry(llm=self.llm)
        self.verbose = verbose

        if force_model:
            # Operator pinned an exact model → skip the RAM-gated selector entirely.
            self._model_key = "forced"
            self._model_cfg = types.SimpleNamespace(ollama_id=force_model, name=force_model)
            if verbose:
                print(f"[Audit] Model: FORCED {force_model}")
        else:
            # Adaptive model selection
            try:
                mem = get_memory_status()
                if verbose:
                    print(f"[Audit] Memory: {mem['available_gb']:.1f} GiB available")
                self._model_key, self._model_cfg = select_model_for_role(model_role, verbose=verbose)
                if verbose:
                    print(f"[Audit] Model: {self._model_cfg.name} ({self._model_cfg.ollama_id})")
            except RuntimeError as e:
                # Nothing fits the VRAM gate. Forcing a big hardcoded model (the old
                # behavior) just EOFs. Degrade to the stable lightweight fallback instead.
                print(f"[Audit] WARNING: {e}")
                print(f"[Audit] Degrading to stable fallback: {self._FALLBACK_MODEL}")
                self._model_key = "fallback"
                self._model_cfg = types.SimpleNamespace(
                    ollama_id=self._FALLBACK_MODEL, name=self._FALLBACK_MODEL)

        # Load the system prompt. Sélectionnable (`--prompt`) : le prompt PORTE la méthode, et
        # une cartographie de corpus externe n'obéit pas aux mêmes règles qu'un audit de code
        # WAMA (pas de suggested_actions, preuves obligatoires, couverture déclarée). Le codage
        # en dur de "audit.txt" rendait `prompts/cartography.txt` inatteignable.
        # Accesseur UNIQUE depuis le 2026-09-09 (`role_utils.consigne_role`) : ce dossier avait
        # quatre lecteurs. `consigne_role` LÈVE si la consigne manque, en listant les connues —
        # ce qui transforme une faute de frappe sur `--prompt` en message clair, là où le
        # `if .exists()` la faisait retomber en silence sur le prompt intégré.
        audit_prompt_path = PROMPTS_DIR / f"{prompt}.txt"
        if audit_prompt_path.exists():
            if verbose:
                print(f"[Audit] Prompt: {audit_prompt_path.name}")
            from role_utils import consigne_role
            self._system_prompt = consigne_role(prompt)
            # ⚠ GARDE — un prompt sans `{tools}` produit un ÉCHEC SILENCIEUX : le modèle ne reçoit
            # ni la liste des outils ni la syntaxe d'appel, ne peut donc appeler personne, répond
            # vide, l'agent ne parse aucun appel et conclut « terminé » avec un rapport de 0 octet
            # et un code de sortie 0. Constaté le 2026-08-20 sur `cartography.txt` : une passe
            # perdue sans le moindre signal. Mieux vaut refuser de démarrer.
            missing = [ph for ph in ("{tools}", "{task}") if ph not in self._system_prompt]
            if missing:
                raise ValueError(
                    f"prompt '{audit_prompt_path.name}' inutilisable : {', '.join(missing)} "
                    f"absent(s). `{{tools}}` reçoit la liste des outils et la syntaxe d'appel, "
                    f"`{{task}}` la tâche. Sans eux l'agent tourne à vide sans erreur visible."
                )
        else:
            self._system_prompt = (
                "You are wama-dev-ai in AUDIT MODE. "
                "Analyse the WAMA codebase read-only. "
                "Available tools:\n{tools}\n"
                "Call tools using: <tool_call>{\"name\": \"TOOL\", \"arguments\": {}}</tool_call>\n"
                "Write reports using write_report tool only. Task: {task}"
            )

        # Load and inject persistent memory
        self._memory = _load_memory()
        if self._memory:
            memory_block = _format_memory_for_prompt(self._memory)
            if memory_block:
                self._system_prompt = memory_block + "\n---\n\n" + self._system_prompt
                if verbose:
                    issue_count = len(self._memory.get("known_issues", {}))
                    note_count = len(self._memory.get("persistent_notes", {}))
                    print(f"[Audit] Memory loaded: {issue_count} known issues, {note_count} notes")

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
            print(f"[Audit] Auto-saved response -> {filename}")

    def run(self, task: str) -> str:
        """
        Run the audit agent for a given task, then RELEASE the model.

        Le modèle est chargé avec `keep_alive=-1` (résidence indéfinie) pour qu'aucune étape
        d'outil longue ne provoque un déchargement — donc aucun rechargement, donc pas le crash
        transitoire EOF que ce build d'Ollama produit au premier appel après un (re)chargement.
        La durée d'un run n'étant pas prévisible, c'est le run LUI-MÊME qui libère, ici, en
        `finally` : fin normale, exception ou Ctrl-C laissent la VRAM propre pour la suite.
        ⚠ Il ne libère que SON modèle (2026-10-13) : jusque-là, ce `finally` déchargeait TOUS
        les modèles d'Ollama, ceux des autres compris.
        ⚠ La résidence indéfinie déroge au `keep_alive='0'` du mode dépannage, À DESSEIN : ce
        mode veut éviter l'empilement, et un rechargement à chaque tour d'outil serait pire
        (crash EOF au premier appel après chargement, cf. `_run_loop`).
        """
        try:
            return self._run_loop(task)
        finally:
            try:
                _release_own_model(self.model_id, verbose=self.verbose)
            except Exception as exc:      # libérer ne doit JAMAIS masquer le résultat du run
                if self.verbose:
                    print(f"[Audit] Déchargement final impossible : {exc}")

    @property
    def model_id(self) -> str:
        """Le modèle Ollama de ce run (choisi, forcé, ou repli stable)."""
        return self._model_cfg.ollama_id if self._model_cfg else self._FALLBACK_MODEL

    def _run_loop(self, task: str) -> str:
        """Boucle agentique proprement dite (cf. `run`, qui en garantit la libération)."""
        self._report_saved = False  # track whether write_report was called
        if self.verbose:
            print(f"\n[Audit] Task: {task}\n")

        # Inject tools list and task into system prompt
        tools_desc = self.tools.get_tools_description()
        system = (self._system_prompt
                  .replace("{tools}", tools_desc)
                  .replace("{task}", task))

        model_id = self.model_id

        # Compute num_ctx from actual free VRAM (not system RAM).
        # Thinking models need larger context for their <think> blocks.
        free_vram = _get_free_vram_gb()
        num_ctx = _compute_num_ctx(free_vram)
        # Deux questions DISTINCTES : le modèle pense-t-il (capacité, demandée à Ollama), et
        # comprend-il la directive `/no_think` (convention Qwen). On n'injecte que si les deux
        # sont vraies — sinon on envoie du texte parasite (cf. `_honors_no_think`).
        thinking = _is_thinking_model(model_id)
        inject_no_think = thinking and _honors_no_think(model_id)
        if self.verbose:
            detail = ""
            if thinking:
                detail = " -> /no_think" if inject_no_think else " (pense, mais n'honore pas /no_think)"
            print(f"[Audit] VRAM free: {free_vram:.1f} GiB -> num_ctx={num_ctx}"
                  f"{' [thinking]' + detail if thinking else ' [non-thinking]'}")

        # For thinking models, /no_think disables the <think> block so the model
        # responds directly — saves thousands of tokens and avoids context overflow.
        first_user = ("/no_think\n" if inject_no_think else "") + task

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
            # This Ollama build crashes transiently (EOF 500) on the first inference
            # after a (re)load — retry with backoff so one transient crash doesn't kill
            # the whole run (the model is usually warm/stable by the 2nd-3rd attempt).
            raw = None
            for attempt in range(4):
                try:
                    raw = self.llm._client.chat(
                        model=model_id,
                        messages=messages,
                        options={"temperature": 0.3, "num_ctx": num_ctx},
                        # keep_alive=-1 : résidence INDÉFINIE pendant le run. Le défaut Ollama
                        # (5 min) déchargeait le modèle dès qu'une étape d'outil dépassait ce
                        # délai — et le commentaire ci-dessus dit que le PREMIER appel après un
                        # (re)chargement crashe transitoirement (EOF 500) sur ce build. On
                        # supprime donc la cause au lieu de la rattraper par retry.
                        # ⚠ La contrepartie est un modèle qui squatte la VRAM : le déchargement
                        # est fait par `run()` en `finally` — c'est LE RUN qui sait quand il a
                        # fini, aucune durée n'est devinée ici.
                        keep_alive=-1,
                    )
                    break
                except Exception as e:
                    msg = str(e)
                    if attempt == 3:
                        raise
                    if self.verbose:
                        print(f"[Audit] chat attempt {attempt + 1} failed ({msg[:60]}) — retrying")
                    import time
                    time.sleep(3 * (attempt + 1))
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
                    status = "[ok]" if result.success else "[x]"
                    print(f"  {status} {call.tool_name}({list(call.arguments.keys())}) "
                          f"-> {result.output[:100] if result.success else result.error}")
                tool_results.append((call, result))

            # Add assistant turn + tool results to messages
            messages.append({"role": "assistant", "content": response_text})

            # Feed tool output back to the model. read_file/search_content return full
            # file contents (often KBs) — a tiny cap blinds the agent and makes it loop
            # re-reading the same file. Cap generously (per result) so code is actually visible.
            _TOOL_OUT_CAP = 6000
            tool_result_text = "\n".join(
                f"[{call.tool_name}] {'OK: ' + result.output[:_TOOL_OUT_CAP] if result.success else 'ERROR: ' + result.error}"
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
1. HuggingFace model integration rule compliance (AGENTS.md)
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
        "--force-model", "-F",
        default=None,
        help="Bypass the RAM-gated selector and use this exact Ollama model id "
             "(e.g. 'gemma4:e4b').",
    )
    parser.add_argument(
        "--non-interactive", "-n",
        action="store_true",
        help="Non-interactive mode (for cron/scheduled runs)",
    )
    parser.add_argument(
        "--free-vram",
        action="store_true",
        help="ACCORD EXPLICITE de libérer la carte si le modèle n'y tient pas : demande aux "
             "services résidents de se décharger (canal du gouverneur ; un service qui sert "
             "n'est pas interrompu). Sans lui, l'audit attend, et ne décharge personne.",
    )
    parser.add_argument(
        "--wait-max",
        type=float,
        default=300.0,
        help="Attente maximale de VRAM libre en mode dépannage GPU, en secondes (défaut 300)",
    )
    parser.add_argument(
        "--prompt", "-p",
        default="audit",
        help="Nom du prompt système dans prompts/ (sans .txt). Ex : 'cartography' pour "
             "cartographier un corpus externe (bind, pynd). Défaut : 'audit'.",
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

    agent = AuditAgent(model_role=args.model, verbose=verbose, force_model=args.force_model,
                       prompt=args.prompt)
    # La garde GPU COMMUNE des rôles (2026-10-13) — elle remplace le déchargement de TOUT Ollama
    # et le vidage par l'API web : on attend en mode dépannage, on ne libère que sur accord.
    from role_utils import local_llm_guard
    local_llm_guard('ollama', agent.model_id, wait_max=args.wait_max,
                    release_reason='audit wama-dev-ai' if args.free_vram else '',
                    log=lambda m: print(f'[Audit] {m}'))
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
