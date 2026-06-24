"""
Contrat de backend de modèle COMMUN à WAMA — extrait de l'app de référence (Transcriber).

But : un fonctionnement générique et **non bloquant pour de nouveaux modèles**. Un nouveau backend =
une sous-classe qui déclare ses dépendances et implémente le cycle de vie ; **aucune modif du cœur**.

⚠️ CONTRAT SEUL (1ʳᵉ étape d'extraction) : aucune app n'est encore migrée dessus. Migration
incrémentale : imager (forme déjà alignée) → enhancer → reader/anonymizer/composer/synthesizer →
describer en dernier. Voir BACKEND_CARTOGRAPHY.md.

Le COMMUN est le **cycle de vie** (is_available / load / is_loaded / unload), pas le verbe métier :
les apps exposent `transcribe()/generate()/enhance()/...` en déléguant à `process(**kwargs)`.

Jonction prospection/installation : `missing_packages()` indique les libs à installer pour qu'un
modèle puisse tourner → consommé par le model_installer (proposer/poser les paquets) et par les tests
nocturnes (`is_available()==False` → scénario skippé, pas en échec).
"""
from __future__ import annotations

import importlib.util
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger(__name__)


class BaseModelBackend(ABC):
    """Backend de modèle local (chargement/déchargement + traitement)."""

    # ── Déclaratif (métadonnée-driven) ───────────────────────────────────────
    # Modules d'import requis pour faire tourner ce backend (ex. ['df', 'torch']).
    REQUIRED_PACKAGES: List[str] = []
    # Paquets pip à installer si un import manque (souvent = REQUIRED_PACKAGES, mais le nom pip
    # peut différer du nom d'import : ex. import 'cv2' ↔ pip 'opencv-python'). Override au besoin.
    PIP_PACKAGES: Optional[List[str]] = None
    recommended_vram_gb: Optional[float] = None
    description: str = ""

    # ── Disponibilité / dépendances (hook prospection) ───────────────────────
    @classmethod
    def missing_packages(cls) -> List[str]:
        """Modules requis dont l'import est introuvable (sans les importer réellement)."""
        missing = []
        for mod in cls.REQUIRED_PACKAGES:
            try:
                if importlib.util.find_spec(mod) is None:
                    missing.append(mod)
            except (ImportError, ValueError, ModuleNotFoundError):
                missing.append(mod)
        return missing

    @classmethod
    def is_available(cls) -> bool:
        """
        True si le backend peut RÉELLEMENT tourner. Défaut : aucun paquet pip manquant (find_spec).

        ⚠️ OVERRIDE par un vrai try-import quand il y a des dépendances NATIVES : `find_spec('df')`
        trouve le paquet alors qu'`import df` peut échouer (lib native `libdf` absente). Le défaut
        find_spec répond à « faut-il pip install ? » (→ missing_packages), pas à « ça importe ? ».
        Exemple d'override correct : `DeepFilterNetBackend.is_available()` fait `try: import df`.
        """
        return not cls.missing_packages()

    @classmethod
    def pip_install_spec(cls) -> List[str]:
        """Paquets pip à installer pour rendre le backend disponible (pour le model_installer)."""
        if cls.PIP_PACKAGES is not None:
            return cls.PIP_PACKAGES
        return list(cls.REQUIRED_PACKAGES)

    # ── Cycle de vie (à implémenter) ─────────────────────────────────────────
    @abstractmethod
    def load(self, model: Optional[str] = None) -> bool:
        """Charge le modèle en mémoire. Retourne True si chargé. Idempotent si déjà chargé."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """True si le modèle est actuellement chargé en mémoire."""

    @abstractmethod
    def unload(self) -> None:
        """Décharge le modèle et libère la VRAM/RAM. No-op si déjà déchargé."""

    @abstractmethod
    def process(self, **kwargs):
        """Point d'entrée métier générique. Les apps exposent un alias (transcribe/generate/…)."""

    # ── Confort ──────────────────────────────────────────────────────────────
    def info(self) -> dict:
        return {
            "backend": type(self).__name__,
            "available": self.is_available(),
            "missing_packages": self.missing_packages(),
            "loaded": self.is_loaded,
            "recommended_vram_gb": self.recommended_vram_gb,
            "description": self.description,
        }
