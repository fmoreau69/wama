"""
Manager de backends COMMUN — extrait du pattern Transcriber/Imager.

Registre générique réutilisable : enregistre des classes `BaseModelBackend`, instancie en
singleton (keep_loaded), expose disponibilité/infos, décharge. Sélection auto par priorité.

⚠️ ADDITIF : aucune app n'est forcée de l'adopter. Une app crée son manager et enregistre ses
backends ; ça remplace le boilerplate des managers par-app (transcriber/imager) quand on voudra,
sans toucher aux apps non migrées (ex. Anonymizer, dont Cam Analyzer réutilise les modèles).

La sélection VRAM-aware au niveau CATALOGUE reste à `model_manager.services.model_selector.select_model`
(granularité variante de modèle) ; ici on gère le cycle de vie des backends (granularité moteur).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from .base import BaseModelBackend

logger = logging.getLogger(__name__)


# ── Inventaire des MOTEURS d'exécution — grisage AUTOMATIQUE (décision Fabien 02/09) ────
#
# Le pending « griser les moteurs sans backend » (31/08) est tranché : PAS de grisage à la
# main — un système qui VÉRIFIE. Chaque producteur enregistre l'inventaire des moteurs
# qu'il sait exécuter (`apps.py:ready()` — le registre ne connaît JAMAIS ses producteurs,
# règle CLAUDE.md) ; `backend_missing()` rend un verdict à la demande. Comme l'inventaire
# est RELU à chaque appel, un backend qui apparaît RÉ-AUTORISE tout seul — rien à dégriser.
#
# Verdict PERMISSIF par construction (même doctrine que `matches_inputs`) : on ne condamne
# que le POSITIVEMENT inlançable — un moteur déclaré qu'aucun inventaire ne sert. Un modèle
# sans moteur déclaré, ou porteur d'un `backend_ref` d'app, n'a pas de verdict : l'exclure
# sur une absence d'information viderait des lots entiers (imager/composer déclaratifs).
#
# Consommateurs : `select_model` (un tirage AUTO inlançable est toujours faux → exclu) et
# `get_registry_models` (le select AFFICHE, grisé AVEC la raison — lister n'est pas
# pouvoir choisir, jamais d'exclusion de liste : INPUT_MODEL_MATCHING §2).
_ENGINE_INVENTORIES: List = []


def register_engine_inventory(fn) -> None:
    """Enregistre un inventaire : callable () -> itérable de noms de moteurs exécutables."""
    _ENGINE_INVENTORIES.append(fn)


def known_engines() -> set:
    """Union des inventaires enregistrés — relue à CHAQUE appel (ré-autorisation auto)."""
    moteurs = set()
    for fn in _ENGINE_INVENTORIES:
        try:
            moteurs.update(fn())
        except Exception as e:   # un inventaire cassé ne condamne pas les autres
            logger.debug("[engines] inventaire %r illisible : %s", fn, e)
    return moteurs


def backend_missing(model) -> Optional[str]:
    """Raison si `model` est POSITIVEMENT sans backend, sinon None.

    `model` : AIModel (ou tout porteur de `composition`/`backend_ref`).
    """
    if getattr(model, 'backend_ref', ''):
        return None                          # l'app qui déclare un backend l'assume
    composition = getattr(model, 'composition', None) or {}
    engine = (composition.get('runtime') or {}).get('engine') or ''
    if not engine or engine in known_engines():
        return None
    return f"moteur « {engine} » sans backend installé"


class BackendManager:
    """Registre + cycle de vie de backends `BaseModelBackend` (singletons keep_loaded)."""

    def __init__(self, name: str = "backend", priority: Optional[List[str]] = None):
        self.name = name
        self.priority = list(priority or [])
        self._backends: Dict[str, Type[BaseModelBackend]] = {}
        self._instances: Dict[str, BaseModelBackend] = {}

    # ── Enregistrement ───────────────────────────────────────────────────────
    def register(self, key: str, backend_cls: Type[BaseModelBackend]) -> None:
        self._backends[key] = backend_cls

    def register_many(self, mapping: Dict[str, Type[BaseModelBackend]]) -> None:
        for k, c in mapping.items():
            self.register(k, c)

    def keys(self) -> List[str]:
        return list(self._backends)

    # ── Disponibilité / infos ────────────────────────────────────────────────
    def available(self) -> Dict[str, bool]:
        """{clé: is_available()} — quels backends peuvent réellement tourner."""
        out = {}
        for k, c in self._backends.items():
            try:
                out[k] = bool(c.is_available())
            except Exception as e:  # is_available d'un backend ne doit jamais casser le manager
                logger.debug("[%s] is_available(%s) a levé: %s", self.name, k, e)
                out[k] = False
        return out

    def info(self) -> Dict[str, dict]:
        out = {}
        for k, c in self._backends.items():
            try:
                avail = bool(c.is_available())
                missing = c.missing_packages()
            except Exception:
                avail, missing = False, []
            out[k] = {
                'available': avail,
                'missing_packages': missing,
                'description': getattr(c, 'description', ''),
                'recommended_vram_gb': getattr(c, 'recommended_vram_gb', None),
                'loaded': k in self._instances,
            }
        return out

    # ── Récupération / sélection ─────────────────────────────────────────────
    def _auto_select(self) -> Optional[str]:
        avail = self.available()
        for k in self.priority:               # priorité explicite d'abord
            if avail.get(k):
                return k
        for k, ok in avail.items():            # sinon premier dispo
            if ok:
                return k
        return None

    def get_backend(self, key: Optional[str] = None) -> Optional[BaseModelBackend]:
        """
        Retourne l'INSTANCE (singleton keep_loaded) du backend `key`. Si key=None, auto-sélection
        par priorité parmi les disponibles. None si rien ne correspond / n'est disponible.
        """
        if key is None:
            key = self._auto_select()
        if key is None:
            return None
        cls = self._backends.get(key)
        if cls is None:
            logger.warning("[%s] backend inconnu: %s", self.name, key)
            return None
        if key not in self._instances:
            self._instances[key] = cls()
        return self._instances[key]

    # ── Cycle de vie ─────────────────────────────────────────────────────────
    def unload(self, key: str) -> None:
        inst = self._instances.pop(key, None)
        if inst is not None:
            try:
                inst.unload()
            except Exception as e:
                logger.warning("[%s] unload(%s) a levé: %s", self.name, key, e)

    def unload_all(self) -> None:
        for k in list(self._instances):
            self.unload(k)
