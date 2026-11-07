"""
Contrat de la tâche `quality-metric` — un INSTRUMENT de mesure appris : la note d'une image
produite face à sa référence.

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`. Une métrique apprise (LPIPS)
ne produit rien : elle mesure ce qu'un autre modèle a produit (le banc d'agrandissement,
`model_manager.services.bench._bench_upscale`, `WAMA_QUALITE §M3`). Écrit le 2026-11-07 : le banc
chargeait LPIPS lui-même (`lpips_metric`, un dict de module par appareil), sur le GPU, hors de la
porte de lancement, de l'enveloppe du gouverneur et du déchargement commun.

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie, dépendances, enveloppe load/unload du
gouverneur, `ENGINE` / `SUPPORTED_MODELS` pour la résolution depuis le catalogue. Ce qui est PROPRE
au domaine ici : le verbe `score` et le SENS de l'échelle (`direction`), dans le vocabulaire des
mesures rangées (`ResultEvaluation.DIRECTION_CHOICES`).
"""
from abc import abstractmethod

from .base import BaseModelBackend


class QualityMetricBackend(BaseModelBackend):
    """`score(image, reference) → float` — un modèle `quality-metric` du catalogue.

    Un nouveau moteur = une sous-classe qui déclare `ENGINE`, `SUPPORTED_MODELS`,
    `REQUIRED_PACKAGES`, `direction`, et implémente `load()/unload()/score()`. L'état de chargement
    vient d'ici : un backend pose `self._loaded` dans `load()`/`unload()`."""

    #: Le SENS de l'échelle : `lower` (plus bas est mieux, une distance) ou `higher` — celui que
    #: range la mesure (`ResultEvaluation.direction`). Déclaré par chaque métrique, jamais deviné.
    direction: str = ''

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs) -> float:
        """Point d'entrée générique (contrat commun) → délègue à `score()`."""
        return self.score(**kwargs)

    @abstractmethod
    def score(self, image, reference) -> float:
        """La note de `image` face à `reference` (ndarray BGR uint8, H×W×3, MÊMES dimensions),
        dans le sens que déclare `direction`."""
