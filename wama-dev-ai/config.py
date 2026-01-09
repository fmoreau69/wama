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
    "dev": ModelConfig(
        name="Qwen Coder 32B",
        ollama_id="qwen2.5-coder:32b",
        description="Expert Python/Django developer for writing code",
        context_length=32768,
        temperature=0.7,
        role="dev"
    ),
    "debug": ModelConfig(
        name="DeepSeek Coder V2 16B",
        ollama_id="deepseek-coder-v2:16b",
        description="Code reviewer and debugger",
        context_length=16384,
        temperature=0.3,
        role="debug"
    ),
    "architect": ModelConfig(
        name="Llama 3.1 70B",
        ollama_id="llama3.1:70b",
        description="System architect for design and planning (CPU offload)",
        context_length=32768,
        temperature=0.5,
        role="architect"
    ),
    "vision": ModelConfig(
        name="Llava 34B",
        ollama_id="llava:34b",
        description="Vision model for image analysis",
        context_length=8192,
        temperature=0.7,
        role="vision"
    ),
    "vision_fast": ModelConfig(
        name="Llama 3.2 Vision 11B",
        ollama_id="llama3.2-vision:11b",
        description="Fast vision model for image analysis",
        context_length=8192,
        temperature=0.7,
        role="vision"
    ),
    "embed": ModelConfig(
        name="Nomic Embed Text",
        ollama_id="nomic-embed-text",
        description="Fast text embeddings for semantic search",
        context_length=8192,
        temperature=0.0,
        role="embed"
    ),
    "fast": ModelConfig(
        name="DeepSeek Coder V2 16B",
        ollama_id="deepseek-coder-v2:16b",
        description="Fast model for quick tasks",
        context_length=16384,
        temperature=0.7,
        role="dev"
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
    "AI-outputs", "wama-dev-ai/outputs",
    "media", "static", "staticfiles",
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
    "quick": WorkflowConfig(
        name="Quick Fix",
        description="Fast single-model fix",
        models=["fast"],
    ),
    "standard": WorkflowConfig(
        name="Standard",
        description="Dev + Debug workflow",
        models=["dev", "debug"],
    ),
    "full": WorkflowConfig(
        name="Full Review",
        description="Dev + Debug + Architect",
        models=["dev", "debug", "architect"],
    ),
    "vision": WorkflowConfig(
        name="Vision",
        description="Full workflow with image analysis",
        models=["dev", "debug", "architect", "vision"],
    ),
}
