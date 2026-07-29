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

import functools
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger(__name__)


_WRAPPED = "_wama_governor_wrapped"

# En dessous, la mesure est jugée non concluante (chargement paresseux) et l'on
# retombe sur `recommended_vram_gb`.
_MEASURE_FLOOR_GB = 0.1


def _wrap_load(func):
    """Déclare l'empreinte VRAM au gouverneur après un chargement réussi."""
    if getattr(func, _WRAPPED, False):
        return func

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        before = _vram_snapshot()
        result = func(self, *args, **kwargs)
        try:
            if result is not False:
                gb = _measured_vram_gb(before) if before is not None else None
                # Une mesure NULLE n'est pas une preuve d'absence d'empreinte :
                # chargement paresseux, poids déplacés vers le GPU plus tard, ou
                # mémoire prise hors de l'allocateur PyTorch. On retombe alors sur
                # la valeur déclarée — qui vaut None pour un backend purement CPU,
                # auquel cas on ne réserve rien, ce qui est correct.
                if gb is None or gb < _MEASURE_FLOOR_GB:
                    gb = self.recommended_vram_gb
                if gb:
                    from wama.common.services.resource_governor import reserve_vram
                    reserve_vram(_governor_owner(self), float(gb))
        except Exception:
            logger.debug("Déclaration VRAM au gouverneur ignorée", exc_info=True)
        return result

    setattr(wrapper, _WRAPPED, True)
    return wrapper


def _wrap_unload(func):
    """Libère la réservation VRAM au gouverneur après un déchargement."""
    if getattr(func, _WRAPPED, False):
        return func

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        try:
            from wama.common.services.resource_governor import release_vram
            release_vram(_governor_owner(self))
        except Exception:
            logger.debug("Libération VRAM au gouverneur ignorée", exc_info=True)
        return result

    setattr(wrapper, _WRAPPED, True)
    return wrapper


def _governor_owner(instance) -> str:
    """Identité de ce backend, dans CE process, pour le registre VRAM partagé."""
    return f"{type(instance).__module__}.{type(instance).__name__}:{os.getpid()}"


def _measured_vram_gb(before_bytes) -> Optional[float]:
    """Empreinte VRAM réellement prise depuis `before_bytes`, ou None hors CUDA."""
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return max(0.0, (torch.cuda.memory_allocated() - before_bytes) / (1024 ** 3))
    except Exception:
        return None


def _vram_snapshot() -> Optional[int]:
    try:
        import torch

        return torch.cuda.memory_allocated() if torch.cuda.is_available() else None
    except Exception:
        return None


class BaseModelBackend(ABC):
    """
    Backend de modèle local (chargement/déchargement + traitement).

    DÉCLARATION AUTOMATIQUE AU GOUVERNEUR DE RESSOURCES
    ===================================================
    Tout sous-classe voit ses `load()` / `unload()` enveloppés automatiquement
    (`__init_subclass__`) pour déclarer/libérer son empreinte VRAM dans le
    registre PARTAGÉ (`common/services/resource_governor.py`).

    Pourquoi ici et pas dans chaque app : c'est le seul point par lequel passent
    tous les backends, présents ET à venir. Un backend futur hérite de la
    déclaration sans que personne n'y pense — c'est ce qui évite de « perdre un
    mécanisme en route ».

    L'empreinte déclarée est **MESURÉE** (delta `torch.cuda.memory_allocated()`
    autour du chargement), et retombe sur `recommended_vram_gb` seulement si la
    mesure est impossible. La mesure prime volontairement sur le déclaratif :
    le 29/07/2026, le preset de `qwen-image` annonçait 16 Go pour une empreinte
    réelle de 38,1 Go — c'est cet écart qui a fait paniquer le noyau WSL2.

    Le câblage ne peut JAMAIS faire échouer un chargement : toute erreur du
    gouverneur est avalée (le backend garde son comportement d'origine).
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # N'envelopper QUE les méthodes définies par cette classe-ci : sans ce
        # garde, une sous-classe de sous-classe (imager : Base → ImagerBase →
        # backend concret) ré-envelopperait une méthode déjà enveloppée et
        # compterait l'empreinte deux fois.
        if "load" in cls.__dict__:
            cls.load = _wrap_load(cls.__dict__["load"])
        if "unload" in cls.__dict__:
            cls.unload = _wrap_unload(cls.__dict__["unload"])

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
