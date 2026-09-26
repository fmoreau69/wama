"""Quel moteur de recherche, pour qui — et avec quelle clé.

Deux étages, comme partout ailleurs dans WAMA (décision de Fabien, 2026-09-26) :
  • un DÉFAUT D'INSTANCE — réglage `WAMA_SEARCH_ENGINE` ;
  • une PRÉFÉRENCE de chacun, au profil (`UserProfile.search_engine`), qui le surcharge.
Un utilisateur qui n'a rien choisi, ou qui a choisi un moteur dont il n'a pas la clé, retombe
sur le premier moteur UTILISABLE — jamais sur une erreur de configuration.

⚠ L'inventaire n'est pas écrit ici : les moteurs sont les sources `kind='recherche'` du
registre commun. Ajouter un moteur = une entrée au registre + une classe d'adaptateur ; ni la
page de profil, ni l'assistant, ni cette fonction n'ont à l'apprendre.
"""
from __future__ import annotations

from .base import BaseSearchEngine, SearchEngineUnavailable, SearchHit  # noqa: F401 (ré-export)
from .duckduckgo import DuckDuckGoEngine
from .exa import ExaEngine
from .searxng import SearxngEngine
from .staan import StaanEngine

_ENGINES: dict[str, type[BaseSearchEngine]] = {
    ExaEngine.slug: ExaEngine,
    StaanEngine.slug: StaanEngine,
    SearxngEngine.slug: SearxngEngine,
    DuckDuckGoEngine.slug: DuckDuckGoEngine,
}


def engine_slugs() -> list[str]:
    """Les moteurs implémentés, dans l'ordre de préférence par défaut."""
    return list(_ENGINES)


def declared_engines() -> list:
    """Les sources `recherche` du registre QUI ONT un adaptateur ici.

    Une source déclarée sans adaptateur ne serait pas offerte au choix : on ne propose pas un
    moteur qu'on ne sait pas interroger.
    """
    from wama.common import external_sources
    ordre = engine_slugs()
    sources = [s for s in external_sources.SOURCES
               if s.kind == 'recherche' and s.key in _ENGINES]
    return sorted(sources, key=lambda s: ordre.index(s.key))


def needs_key(slug: str) -> bool:
    from wama.common import external_sources
    source = external_sources.get(slug)
    return bool(source.user_key or source.api_key_env)


def key_for(user, slug: str) -> str:
    """La clé de CET utilisateur pour ce moteur — règle commune (`accounts.api_keys`) : un
    utilisateur n'utilise QUE sa propre clé ; celle de l'instance ne sert qu'aux usages sans
    utilisateur (tâches planifiées, ligne de commande)."""
    from wama.accounts.api_keys import key_for as _key_for
    return _key_for(user, slug)


def _is_declared_instance(source) -> bool:
    """Un service AUTO-HÉBERGÉ n'existe que s'il a été DÉCLARÉ.

    SearXNG porte une adresse par défaut (`127.0.0.1:8888`) qui ne désigne rien tant que
    personne n'a monté l'instance. Sans cette règle, il serait « sans clé, donc utilisable »
    et deviendrait le moteur par défaut de toute installation neuve — qui échouerait sur une
    connexion refusée, là où le repli devrait simplement passer au moteur suivant.
    """
    from wama.common import external_sources
    return external_sources.base_url(source.key).rstrip('/') != source.base.rstrip('/')


def usable_slugs(user) -> list[str]:
    """Les moteurs que CET utilisateur peut employer : sa clé posée, ou aucune clé requise —
    et, pour un service local, une instance réellement déclarée."""
    from wama.common.external_sources import LOCAL

    usable = []
    for source in declared_engines():
        if needs_key(source.key):
            if key_for(user, source.key):
                usable.append(source.key)
        elif source.scope != LOCAL or _is_declared_instance(source):
            usable.append(source.key)
    return usable


def preferred_slug(user) -> str:
    """Le moteur de cet utilisateur : sa préférence, sinon le défaut d'instance, sinon le
    premier utilisable. '' si aucun moteur n'est utilisable (l'appelant le dit en clair)."""
    from django.conf import settings

    usable = usable_slugs(user)
    wanted = (getattr(getattr(user, 'profile', None), 'search_engine', '') or '').strip()
    if wanted and wanted in usable:
        return wanted
    instance_default = (getattr(settings, 'WAMA_SEARCH_ENGINE', '') or '').strip()
    if instance_default and instance_default in usable:
        return instance_default
    return usable[0] if usable else ''


def get_engine(slug: str, api_key: str = '') -> BaseSearchEngine | None:
    cls = _ENGINES.get(slug)
    return cls(api_key=api_key) if cls else None


def engine_for(user) -> BaseSearchEngine:
    """Le moteur à employer pour cet utilisateur, prêt à interroger.

    Lève `SearchEngineUnavailable` avec un motif LISIBLE quand aucun moteur n'est utilisable —
    c'est le cas le plus fréquent d'une installation neuve (aucune clé posée), et il mérite
    mieux qu'une liste vide : l'utilisateur doit savoir qu'il faut aller au profil.
    """
    slug = preferred_slug(user)
    if not slug:
        noms = ', '.join(s.label for s in declared_engines() if needs_key(s.key))
        raise SearchEngineUnavailable(
            "aucun moteur de recherche n'est utilisable : posez la clé d'un moteur sur votre "
            f"page de profil ({noms}), ou déclarez une instance SearXNG")
    return get_engine(slug, key_for(user, slug))
