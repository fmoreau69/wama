"""
WAMA Media Library — Provider registry
Mappage slug → classe provider.
"""

from typing import Dict, Type

from .base import BaseProvider
from .wikimedia import WikimediaProvider
from .pixabay import PixabayProvider
from .freesound import FreesoundProvider
from .pexels import PexelsProvider
from .openverse import OpenverseProvider
from .jamendo import JamendoProvider
from .avatars3d import Avatars3dProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {
    WikimediaProvider.slug:  WikimediaProvider,
    PixabayProvider.slug:    PixabayProvider,
    FreesoundProvider.slug:  FreesoundProvider,
    PexelsProvider.slug:     PexelsProvider,
    OpenverseProvider.slug:  OpenverseProvider,
    JamendoProvider.slug:    JamendoProvider,
    Avatars3dProvider.slug:  Avatars3dProvider,
}


def provider_row(slug: str):
    """La ligne `MediaProvider` d'un connecteur ENREGISTRÉ, créée si elle manque (2026-09-30).

    Les six premières lignes sont nées d'une migration de DONNÉES (0005, 0007) — un connecteur de
    plus aurait donc exigé une migration, alors que les migrations ne sont pas versionnées dans ce
    dépôt : le connecteur existait en code et restait invisible. La ligne se DÉRIVE désormais de
    la classe (nom, types, clé requise) et de la source déclarée (usage, page de la clé) ; une
    ligne existante n'est jamais réécrite (un admin a pu la désactiver). None si le slug n'est
    pas un connecteur enregistré."""
    cls = _REGISTRY.get(slug)
    if cls is None:
        return None
    from wama.common.external_sources import by_key
    from wama.media_library.models import MediaProvider
    source = by_key().get(slug)
    row, _ = MediaProvider.objects.get_or_create(slug=slug, defaults={
        'name': cls.name,
        'description': source.usage if source else '',
        'supported_types': list(cls.supported_types),
        'requires_api_key': cls.requires_api_key,
        'api_key_help_url': (source.api_key_help_url if source else '') or '',
        'api_key_label': (source.api_key_label if source else '') or 'Clé API',
    })
    return row


def ensure_provider_rows() -> None:
    """Toute classe enregistrée a sa ligne — appelé avant de LISTER les connecteurs."""
    for slug in _REGISTRY:
        provider_row(slug)


def get_provider(slug: str, api_key: str = '') -> BaseProvider | None:
    """Retourne une instance du provider ou None si slug inconnu."""
    cls = _REGISTRY.get(slug)
    return cls(api_key=api_key) if cls else None


def all_slugs() -> list:
    return list(_REGISTRY.keys())
