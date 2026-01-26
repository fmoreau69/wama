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

# Bypass proxy for localhost
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'

OLLAMA_HOST = "http://127.0.0.1:11434"


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


# Available models for each role
# Configured for RTX 4090 (24GB VRAM)
MODELS = {
    # -------------------------------------------------------------------------
    # Prompt & Language Models
    # -------------------------------------------------------------------------
    "prompt_enricher": ModelConfig(
        name="Gemma 3 4B",
        ollama_id="gemma3:4b",
        description="Default prompt enrichment, structuring and normalization",
        context_length=128000,
        temperature=0.3,
        role="prompt",
    ),

    "prompt_enricher_premium": ModelConfig(
        name="Gemma 3 12B",
        ollama_id="gemma3:12b",
        description="Advanced prompt enrichment for complex or creative prompts",
        context_length=128000,
        temperature=0.25,
        role="prompt",
    ),

    "translator": ModelConfig(
        name="TranslateGemma 12B",
        ollama_id="translategemma:12b",
        description="High-quality multilingual translation and prompt localization",
        context_length=128000,
        temperature=0.2,
        role="translate",
    ),

    "orchestrator": ModelConfig(
        name="GPT-OSS 20B",
        ollama_id="gpt-oss:20b",
        description="Task routing, intent analysis, orchestration and decision-making",
        context_length=8192,
        temperature=0.4,
        role="architect",
    ),

    # -------------------------------------------------------------------------
    # Development Models
    # -------------------------------------------------------------------------
    "dev": ModelConfig(
        name="Qwen3 30B Instruct",
        ollama_id="qwen3:30b-instruct",
        description="Primary developer model for Python/Django/FastAPI code generation",
        context_length=256000,
        temperature=0.6,
        role="dev",
    ),

    "coder": ModelConfig(
        name="Qwen3 Coder 30B",
        ollama_id="qwen3-coder:30b",
        description="Specialized coding model for complex implementations",
        context_length=128000,
        temperature=0.4,
        role="dev",
    ),

    "debug": ModelConfig(
        name="DeepSeek Coder V2 16B",
        ollama_id="deepseek-coder-v2:16b",
        description="Code reviewer, debugger and patch generator",
        context_length=16384,
        temperature=0.2,
        role="debug",
    ),

    "architect": ModelConfig(
        name="Qwen3 30B Thinking",
        ollama_id="qwen3:30b-thinking",
        description="System architect and reasoning model",
        context_length=256000,
        temperature=0.5,
        role="architect",
    ),

    # -------------------------------------------------------------------------
    # Fast Models (for quick tasks)
    # -------------------------------------------------------------------------
    "fast": ModelConfig(
        name="Qwen3 14B",
        ollama_id="qwen3:14b-q8_0",
        description="Fast model for quick tasks and small refactors",
        context_length=40000,
        temperature=0.7,
        role="dev",
    ),

    "ultra_fast": ModelConfig(
        name="Qwen3 8B",
        ollama_id="qwen3:8b-q8_0",
        description="Ultra-fast model for trivial tasks and simple edits",
        context_length=32000,
        temperature=0.7,
        role="dev",
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
    ),

    "vision_fast": ModelConfig(
        name="Llama 3.2 Vision 11B",
        ollama_id="llama3.2-vision:11b",
        description="Fast vision model for UI screenshots and quick analysis",
        context_length=8192,
        temperature=0.7,
        role="vision",
    ),

    "vision_lite": ModelConfig(
        name="Qwen3 VL 8B",
        ollama_id="qwen3-vl:8b",
        description="Lightweight vision model for rapid UI prototyping",
        context_length=8192,
        temperature=0.7,
        role="vision",
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
