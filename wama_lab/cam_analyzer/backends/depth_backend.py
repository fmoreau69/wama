"""Depth Pro — profondeur monoculaire métrique, au contrat commun.

Il n'ENVELOPPE aucune logique nouvelle : `backends/depth_engine` porte déjà le cache de
modèle, le repli CPU et le routage des poids (`cache_dir=`, jamais de mutation
d'environnement). Ce backend l'expose au contrat `load`/`unload`/`process`/`is_loaded`, ce
qui apporte trois choses que l'app n'avait pas :

  • le **lien modèle↔backend se referme** : `huggingface:depthpro` déclare le moteur
    `transformers`, partagé par 4 backends — seul `SUPPORTED_MODELS` peut trancher, et
    personne ne le déclarait. `check_backend_links` le signalait en ✗ ;
  • le **gouverneur de ressources** voit la VRAM : `__init_subclass__` enveloppe
    `load`/`unload` à n'importe quelle profondeur d'héritage ;
  • le **grisage devient mesuré** (`REQUIRED_PACKAGES` → `missing_packages()`).

⚠ `device` est un paramètre de CHARGEMENT ici (le module gère lui-même le repli CPU quand
CUDA manque) : on le passe à `load`, on ne le décide pas à la construction.
"""
import logging
from typing import Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


class DepthProBackend(BaseModelBackend):
    """Estimation de profondeur métrique (Apple Depth Pro), au contrat commun."""

    #: Moteur PILOTÉ — `transformers` charge réellement le modèle
    #: (`AutoModelForDepthEstimation.from_pretrained`). Même graphie que le catalogue.
    ENGINE = 'transformers'
    #: Le lien FIN : `transformers` est partagé par 4 backends de 4 apps, le moteur seul ne
    #: tranche pas. La clé est le `model_id` du catalogue (`huggingface:depthpro`).
    SUPPORTED_MODELS = {'depthpro': {}}
    REQUIRED_PACKAGES = ['transformers', 'torch']
    #: Déclaré au catalogue par `_discover_depth_models` — même valeur, une seule vérité.
    recommended_vram_gb = 8.0
    description = "Profondeur monoculaire métrique + focale estimée (Apple Depth Pro)"

    def __init__(self):
        self._charge = False

    @property
    def is_loaded(self) -> bool:
        return self._charge

    def load(self, model: Optional[str] = None, *, device: str = 'cuda') -> bool:
        """`model` est ignoré : le dépôt est déclaré par le module (`DEPTH_MODEL_ID`)."""
        if self._charge:
            return True
        from .depth_engine import load
        load(device=device)
        self._charge = True
        return True

    def unload(self) -> None:
        from .depth_engine import unload
        unload()
        self._charge = False

    def process(self, frame_bgr=None, device: str = 'cuda', **kwargs):
        """Carte de profondeur d'une image BGR — délègue au verbe métier historique."""
        if frame_bgr is None:
            raise ValueError("DepthProBackend.process attend une image (`frame_bgr`)")
        from .depth_engine import estimate_depth
        if not self._charge:
            self.load(device=device)
        return estimate_depth(frame_bgr, device=device)
