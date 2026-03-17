"""
WAMA Media Library — Provider registry
Mappage slug → classe provider.
"""

from typing import Dict, Type

from .base import BaseProvider
from .wikimedia import WikimediaProvider
from .pixabay import PixabayProvider
from .freesound import FreesoundProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {
    WikimediaProvider.slug: WikimediaProvider,
    PixabayProvider.slug:   PixabayProvider,
    FreesoundProvider.slug: FreesoundProvider,
}


def get_provider(slug: str, api_key: str = '') -> BaseProvider | None:
    """Retourne une instance du provider ou None si slug inconnu."""
    cls = _REGISTRY.get(slug)
    return cls(api_key=api_key) if cls else None


def all_slugs() -> list:
    return list(_REGISTRY.keys())
