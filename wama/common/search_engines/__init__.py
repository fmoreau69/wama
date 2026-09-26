"""Moteurs de recherche web — un adaptateur par moteur, l'inventaire au registre des sources.

Point d'entrée : `engine_for(user)` rend le moteur de cet utilisateur (sa préférence de profil
sur le défaut d'instance), `SearchHit` est ce qu'un moteur rend, `SearchEngineUnavailable` ce
qu'il lève quand il a répondu autre chose que des résultats.
"""
from .base import BaseSearchEngine, SearchEngineUnavailable, SearchHit
from .registry import (declared_engines, engine_for, engine_slugs, get_engine, key_for,
                       needs_key, preferred_slug, usable_slugs)

__all__ = ['BaseSearchEngine', 'SearchEngineUnavailable', 'SearchHit', 'declared_engines',
           'engine_for', 'engine_slugs', 'get_engine', 'key_for', 'needs_key',
           'preferred_slug', 'usable_slugs']
