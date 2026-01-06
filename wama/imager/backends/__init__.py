"""
WAMA Imager - Backend System

Provides multiple image generation backends with automatic fallback.
Currently supported:
- Diffusers (recommended for Python 3.12+)
- ImaginAiry (legacy, for older Python versions)
"""

from .manager import (
    get_backend,
    get_available_backends,
    get_models_choices_fast,
    get_models_with_info_fast,
    get_backend_info_fast,
    BackendManager,
)

__all__ = [
    'get_backend',
    'get_available_backends',
    'get_models_choices_fast',
    'get_models_with_info_fast',
    'get_backend_info_fast',
    'BackendManager',
]
