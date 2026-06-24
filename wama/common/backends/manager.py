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
