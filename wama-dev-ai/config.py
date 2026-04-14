"""
WAMA Dev AI - Configuration

Centralized configuration for models, paths, and settings.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os

# ============================================================================
# Paths Configuration
# ============================================================================

BASE_DIR = Path(__file__).parent.parent  # WAMA root
WAMA_DEV_AI_DIR = Path(__file__).parent
PROMPTS_DIR = WAMA_DEV_AI_DIR / "prompts"
OUTPUT_DIR = WAMA_DEV_AI_DIR / "outputs"
CACHE_DIR = WAMA_DEV_AI_DIR / ".cache"
EMBEDDINGS_DIR = CACHE_DIR / "embeddings"

# Create directories
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)
EMBEDDINGS_DIR.mkdir(exist_ok=True)


# ============================================================================
# Ollama Configuration
# ============================================================================

# Load .env from project root (non-versioned, contains credentials)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed — rely on environment variables

# Bypass proxy for localhost
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'

OLLAMA_HOST = "http://127.0.0.1:11434"

# ============================================================================
# WAMA API Configuration (for VRAM clearing and Phase 2 health checks)
# Loaded from .env at project root or from environment variables.
# ============================================================================

WAMA_BASE_URL = os.environ.get('WAMA_BASE_URL', 'http://localhost')
WAMA_USERNAME  = os.environ.get('WAMA_USERNAME', '')
WAMA_PASSWORD  = os.environ.get('WAMA_PASSWORD', '')


# ============================================================================
# Model Configuration
# ============================================================================

@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    name: str
    ollama_id: str
    description: str
    context_length: int = 8192
    temperature: float = 0.7
    role: str = "general"  # dev, debug, architect, vision, embed
    ram_required_gb: float = 8.0  # Minimum RAM required in GiB
    priority: int = 50  # Higher = preferred when memory allows (0-100)


# Available models for each role
# Configured for RTX 4090 (24GB VRAM)
# RAM requirements are approximate and include OS overhead
MODELS = {
    # -------------------------------------------------------------------------
    # Prompt & Language Models
    # -------------------------------------------------------------------------
    "prompt_enricher": ModelConfig(
        name="Gemma 4 E4B",
        ollama_id="gemma4:e4b",
        description="Default prompt enrichment, structuring and normalization",
        context_length=128000,
        temperature=0.3,
        role="prompt",
        ram_required_gb=10.0,
        priority=50,
    ),

    "prompt_enricher_premium": ModelConfig(
        name="Gemma 4 26B",
        ollama_id="gemma4:26b",
        description="Advanced prompt enrichment for complex or creative prompts (MoE, 3.8B actifs)",
        context_length=256000,
        temperature=0.25,
        role="prompt",
        ram_required_gb=18.0,
        priority=80,
    ),

    "translator": ModelConfig(
        name="TranslateGemma 12B",
        ollama_id="translategemma:12b",
        description="High-quality multilingual translation and prompt localization",
        context_length=128000,
        temperature=0.2,
        role="translate",
        ram_required_gb=16.0,
        priority=50,
    ),

    "orchestrator": ModelConfig(
        name="GPT-OSS 20B",
        ollama_id="gpt-oss:20b",
        description="Task routing, intent analysis, orchestration and decision-making",
        context_length=8192,
        temperature=0.4,
        role="orchestrator",
        ram_required_gb=24.0,
        priority=50,
    ),

    # -------------------------------------------------------------------------
    # Development Models
    # -------------------------------------------------------------------------
    "dev": ModelConfig(
        name="Qwen3.5 35B-A3B",
        ollama_id="qwen3.5:35b-a3b",
        description="Primary developer model for Python/Django/FastAPI code generation",
        context_length=262144,
        temperature=0.6,
        role="dev",
        ram_required_gb=22.0,
        priority=100,
    ),

    "coder": ModelConfig(
        name="Qwen3.5 35B-A3B (Coder)",
        ollama_id="qwen3.5:35b-a3b",
        description="Coding model for complex implementations (MoE, 3B active params)",
        context_length=262144,
        temperature=0.4,
        role="dev",
        ram_required_gb=22.0,
        priority=95,
    ),

    "debug": ModelConfig(
        name="Qwen3-Coder 30B",
        ollama_id="qwen3-coder:30b",
        description="Code reviewer, debugger and patch generator — MoE 30B/3.3B actifs, 256K ctx",
        context_length=262144,
        temperature=0.2,
        role="debug",
        ram_required_gb=19.0,
        priority=50,
    ),

    "architect": ModelConfig(
        name="Qwen3.5 35B-A3B (Architect)",
        ollama_id="qwen3.5:35b-a3b",
        description="System architect and reasoning model (unified think/nothink)",
        context_length=262144,
        temperature=0.5,
        role="architect",
        ram_required_gb=22.0,
        priority=100,
    ),

    # -------------------------------------------------------------------------
    # Fast Models (for quick tasks)
    # -------------------------------------------------------------------------
    "fast": ModelConfig(
        name="Qwen3.5 9B",
        ollama_id="qwen3.5:9b",
        description="Fast model for quick tasks and small refactors (native vision)",
        context_length=262144,
        temperature=0.7,
        role="dev",
        ram_required_gb=9.0,
        priority=70,
    ),

    "ultra_fast": ModelConfig(
        name="Qwen3.5 4B",
        ollama_id="qwen3.5:4b",
        description="Ultra-fast model for trivial tasks and simple edits",
        context_length=262144,
        temperature=0.7,
        role="dev",
        ram_required_gb=4.0,
        priority=40,
    ),

    # -------------------------------------------------------------------------
    # Vision Models
    # -------------------------------------------------------------------------
    "vision": ModelConfig(
        name="LLaVA 34B",
        ollama_id="llava:34b",
        description="High-quality vision model for detailed image analysis",
        context_length=8192,
        temperature=0.7,
        role="vision",
        ram_required_gb=40.0,
        priority=100,
    ),

    "vision_fast": ModelConfig(
        name="Llama 3.2 Vision 11B",
        ollama_id="llama3.2-vision:11b",
        description="Fast vision model for UI screenshots and quick analysis",
        context_length=8192,
        temperature=0.7,
        role="vision",
        ram_required_gb=16.0,
        priority=70,
    ),

    "vision_lite": ModelConfig(
        name="Qwen3.5 9B (Vision)",
        ollama_id="qwen3.5:9b",
        description="Unified vision+text model, native multimodal (early fusion)",
        context_length=262144,
        temperature=0.7,
        role="vision",
        ram_required_gb=9.0,
        priority=40,
    ),

    # -------------------------------------------------------------------------
    # Audit / non-thinking models (safe for complex tool-use prompts)
    # -------------------------------------------------------------------------
    "gemma4_e4b": ModelConfig(
        name="Gemma 4 E4B",
        ollama_id="gemma4:e4b",
        description="Non-thinking 4B model — reliable for complex tool-use prompts (audit)",
        context_length=128000,
        temperature=0.3,
        role="dev",
        ram_required_gb=10.0,
        priority=35,
    ),

    # -------------------------------------------------------------------------
    # Embeddings
    # -------------------------------------------------------------------------
    "embed": ModelConfig(
        name="Nomic Embed Text",
        ollama_id="nomic-embed-text:latest",
        description="Text embeddings for semantic search and RAG",
        context_length=8192,
        temperature=0.0,
        role="embed",
        ram_required_gb=2.0,
        priority=50,
    ),
}


# ============================================================================
# File Discovery Configuration
# ============================================================================

# Directories to exclude from scanning
EXCLUDE_DIRS = {
    "venv", "venv_win", "venv_linux", ".venv",
    "node_modules", "site-packages",
    ".git", ".idea", ".vscode",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    "wama-dev-ai/outputs",
    "media", "staticfiles",  # Keep "static" - source static files are there!
    "dist", "build", "eggs", ".eggs",
    "AI-models",  # Large model files
}

# File extensions to include
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml",
    ".md", ".rst", ".txt",
    ".sql", ".sh", ".bat",
}

# Important files to always consider
IMPORTANT_FILES = {
    "settings.py", "urls.py", "models.py", "views.py",
    "forms.py", "admin.py", "tasks.py", "serializers.py",
    "package.json", "requirements.txt", "pyproject.toml",
    "Dockerfile", "docker-compose.yml",
    "README.md", "CHANGELOG.md",
}


# ============================================================================
# Console Styling
# ============================================================================

THEME = {
    "info": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "dim": "dim",
    "highlight": "bold magenta",
    "code": "bright_white on grey23",
    "added": "green",
    "removed": "red",
    "unchanged": "dim white",
    "file_path": "blue underline",
    "model": "bold cyan",
    "prompt": "bold yellow",
}


# ============================================================================
# Workflow Configuration
# ============================================================================

@dataclass
class WorkflowConfig:
    """Configuration for a workflow step."""
    name: str
    description: str
    models: List[str]
    enabled: bool = True


WORKFLOWS = {
    # -------------------------------------------------------------------------
    # Prompt Enrichment
    # -------------------------------------------------------------------------
    "prompt_enrich": WorkflowConfig(
        name="Prompt Enrichment",
        description="Manual prompt + automatic enrichment before execution",
        models=["prompt_enricher"],
    ),
    "prompt_full": WorkflowConfig(
        name="Prompt Enrichment + Reasoning",
        description="Enriched prompt followed by reasoning and execution",
        models=["prompt_enricher", "architect"],
    ),
    "prompt_full_premium": WorkflowConfig(
        name="Prompt Enrichment Premium",
        description="Enriched prompt (complex) followed by reasoning and execution",
        models=["prompt_enricher_premium", "architect"],
    ),
    "rag_prompt": WorkflowConfig(
        name="RAG + Prompt",
        description="Embedding + prompt enrichment + reasoning",
        models=["embed", "prompt_enricher", "architect"],
    ),

    # -------------------------------------------------------------------------
    # Development Workflows
    # -------------------------------------------------------------------------
    "quick": WorkflowConfig(
        name="Quick Fix",
        description="Ultra-fast single-model fix for trivial tasks",
        models=["ultra_fast"],
    ),
    "standard": WorkflowConfig(
        name="Standard",
        description="Dev + Debug workflow for typical tasks",
        models=["dev", "debug"],
    ),
    "full": WorkflowConfig(
        name="Full Review",
        description="Dev + Debug + Architect for complex features",
        models=["dev", "debug", "architect"],
    ),
    "code": WorkflowConfig(
        name="Code Focus",
        description="Specialized coding model + debug review",
        models=["coder", "debug"],
    ),

    # -------------------------------------------------------------------------
    # UI/Frontend Workflows
    # -------------------------------------------------------------------------
    "ui": WorkflowConfig(
        name="UI Design",
        description="Vision analysis + fast coding for UI/frontend work",
        models=["vision_lite", "coder"],
    ),
    "ui_full": WorkflowConfig(
        name="UI Design (Full)",
        description="Detailed vision analysis + full review for complex UI",
        models=["vision_fast", "coder", "debug"],
    ),

    # -------------------------------------------------------------------------
    # Analysis Workflows
    # -------------------------------------------------------------------------
    "vision": WorkflowConfig(
        name="Vision Analysis",
        description="Full workflow with detailed image analysis",
        models=["vision", "dev", "debug"],
    ),
    "vision_prompt": WorkflowConfig(
        name="Vision + Prompt Enrichment",
        description="Image analysis followed by structured prompt enrichment",
        models=["vision_lite", "prompt_enricher", "dev"],
    ),
    "analyze": WorkflowConfig(
        name="Analyze Only",
        description="Architect reasoning without code changes",
        models=["architect"],
    ),
}


# ============================================================================
# Adaptive Model Selection
# ============================================================================

import psutil
from typing import Tuple

# Memory safety margin (keep this much RAM free for OS and other processes).
# 2 GiB is sufficient for audit/dev tasks — Ollama manages its own memory.
# Was 4.0 GiB which was too conservative and blocked ultra_fast (4 GiB) at ~8 GiB available.
MEMORY_SAFETY_MARGIN_GB = 2.0

# Fallback chains: ordered list of model keys to try for each role
# When a model doesn't fit in memory, try the next one in the chain
MODEL_FALLBACK_CHAINS = {
    "dev": ["dev", "coder", "fast", "ultra_fast"],
    "debug": ["debug", "fast", "ultra_fast"],
    "architect": ["architect", "orchestrator", "fast", "ultra_fast"],
    # audit role: prefers non-thinking models (qwen3.5 crashes on complex prompts)
    # debug (qwen3-coder:30b) est le meilleur choix — 256K ctx, moins d'hallucinations
    "audit": ["debug", "gemma4_e4b", "fast", "ultra_fast"],
    "vision": ["vision", "vision_fast", "vision_lite"],
    "prompt": ["prompt_enricher_premium", "prompt_enricher"],
    "translate": ["translator", "prompt_enricher"],
    "orchestrator": ["orchestrator", "fast", "ultra_fast"],
    "embed": ["embed"],
}


def get_available_memory_gb() -> float:
    """
    Get available system memory in GiB.

    Returns:
        Available memory in GiB (accounting for safety margin)
    """
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024 ** 3)
    return available_gb


def get_total_memory_gb() -> float:
    """Get total system memory in GiB."""
    mem = psutil.virtual_memory()
    return mem.total / (1024 ** 3)


def get_available_vram_gb() -> float:
    """
    Get free GPU VRAM in GiB via nvidia-smi.
    Returns 0.0 if no GPU is available or nvidia-smi fails.
    """
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


def select_model_for_role(
    role: str,
    preferred_model: str = None,
    verbose: bool = False
) -> Tuple[str, ModelConfig]:
    """
    Select the best available model for a given role based on available memory.

    Uses GPU VRAM when available (Ollama prefers GPU), falls back to system RAM.

    Args:
        role: The role to select a model for (dev, debug, architect, vision, etc.)
        preferred_model: Optional preferred model key to try first
        verbose: If True, print selection details

    Returns:
        Tuple of (model_key, ModelConfig) for the selected model

    Raises:
        RuntimeError: If no model fits in available memory
    """
    # Prefer VRAM for model selection: Ollama loads models on GPU when possible.
    # Fall back to system RAM if no GPU is detected.
    vram_free = get_available_vram_gb()
    ram_available = get_available_memory_gb()
    if vram_free > 1.0:
        available_mem = vram_free   # GPU path: use VRAM budget
        mem_label = "VRAM"
    else:
        available_mem = ram_available  # CPU path: use system RAM
        mem_label = "RAM"
    usable_mem = available_mem - MEMORY_SAFETY_MARGIN_GB

    if verbose:
        print(f"[Memory] Available: {ram_available:.1f} GiB RAM / "
              f"{vram_free:.1f} GiB VRAM → using {mem_label}, Usable: {usable_mem:.1f} GiB")

    # Build candidate list
    candidates = []

    # If preferred model is specified and fits, use it
    if preferred_model and preferred_model in MODELS:
        model = MODELS[preferred_model]
        if model.ram_required_gb <= usable_mem:
            if verbose:
                print(f"[Model] Using preferred: {preferred_model} ({model.ram_required_gb:.1f} GiB)")
            return preferred_model, model
        elif verbose:
            print(f"[Model] Preferred {preferred_model} needs {model.ram_required_gb:.1f} GiB (too large)")

    # Get fallback chain for the role
    fallback_chain = MODEL_FALLBACK_CHAINS.get(role, [])

    # Try models in fallback chain order
    for model_key in fallback_chain:
        if model_key not in MODELS:
            continue
        model = MODELS[model_key]
        if model.ram_required_gb <= usable_mem:
            if verbose:
                print(f"[Model] Selected: {model_key} ({model.ram_required_gb:.1f} GiB) for role '{role}'")
            return model_key, model
        elif verbose:
            print(f"[Model] Skipping {model_key}: needs {model.ram_required_gb:.1f} GiB")

    # Last resort: find ANY chat-capable model that fits (exclude embed models)
    fitting_models = [
        (key, cfg) for key, cfg in MODELS.items()
        if cfg.ram_required_gb <= usable_mem and cfg.role != "embed"
    ]

    if fitting_models:
        # Sort by priority (highest first)
        fitting_models.sort(key=lambda x: x[1].priority, reverse=True)
        selected_key, selected_model = fitting_models[0]
        if verbose:
            print(f"[Model] Fallback to: {selected_key} ({selected_model.ram_required_gb:.1f} GiB)")
        return selected_key, selected_model

    # No model fits
    raise RuntimeError(
        f"No model fits in available memory ({usable_mem:.1f} GiB usable). "
        f"Free up memory or use smaller models. "
        f"Smallest model requires {min(m.ram_required_gb for m in MODELS.values()):.1f} GiB."
    )


def select_best_dev_model(verbose: bool = False) -> Tuple[str, ModelConfig]:
    """
    Select the best development model based on available memory.

    This is a convenience function for the most common use case.

    Returns:
        Tuple of (model_key, ModelConfig)
    """
    return select_model_for_role("dev", verbose=verbose)


def get_memory_status() -> dict:
    """
    Get a summary of memory status and model availability.

    Returns:
        Dictionary with memory info and available models
    """
    available = get_available_memory_gb()
    total = get_total_memory_gb()
    vram_free = get_available_vram_gb()
    # Use VRAM budget if GPU is available (mirrors select_model_for_role logic)
    budget = (vram_free if vram_free > 1.0 else available) - MEMORY_SAFETY_MARGIN_GB
    usable = budget

    available_models = []
    unavailable_models = []

    for key, model in MODELS.items():
        info = {
            "key": key,
            "name": model.name,
            "role": model.role,
            "ram_required_gb": model.ram_required_gb,
            "priority": model.priority,
        }
        if model.ram_required_gb <= usable:
            available_models.append(info)
        else:
            unavailable_models.append(info)

    # Sort by priority
    available_models.sort(key=lambda x: x["priority"], reverse=True)
    unavailable_models.sort(key=lambda x: x["ram_required_gb"])

    return {
        "total_gb": round(total, 1),
        "available_gb": round(available, 1),
        "usable_gb": round(usable, 1),
        "safety_margin_gb": MEMORY_SAFETY_MARGIN_GB,
        "available_models": available_models,
        "unavailable_models": unavailable_models,
    }
