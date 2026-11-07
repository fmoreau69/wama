"""LPIPS (AlexNet) — le contrat `quality-metric` sur la librairie `lpips`.

L'instrument du banc d'agrandissement (`model_manager.services.bench._bench_upscale`, `WAMA_QUALITE
§M3`) : la distance perceptuelle entre une image agrandie et l'original net (plus bas = plus
proche). Jusqu'au 2026-11-07, le banc le chargeait lui-même (`lpips_metric`, un dict de module par
appareil), sur le GPU, hors de la porte de lancement, de l'enveloppe du gouverneur et du
déchargement commun. Ce backend est ce chargement, au contrat — le même corps.

Ses poids sont DÉCLARÉS à côté de l'instrument (`bench.LPIPS_FILES`, la dorsale AlexNet de
torchvision) et installés par la route ; le banc, une commande, les demande d'abord
(`model_readiness.install_and_wait`). Les couches linéaires viennent du paquet `lpips`.
"""
from __future__ import annotations

import gc
import logging
from typing import Optional

from .quality_metric_base import QualityMetricBackend

logger = logging.getLogger(__name__)


class LPIPSBackend(QualityMetricBackend):
    """Distance perceptuelle LPIPS (réseau AlexNet) entre deux images de mêmes dimensions."""

    #: Moteur piloté (contrat commun) : la librairie `lpips`.
    ENGINE = 'lpips'
    #: Modèles servis : clé = dernier segment de la clé de catalogue (`pytorch_download:lpips-alexnet`).
    #: ⚠ En LITTÉRAL : l'inventaire lit les clés par AST.
    SUPPORTED_MODELS = {
        'lpips-alexnet': {'model_key': 'pytorch_download:lpips-alexnet'},
    }
    REQUIRED_PACKAGES = ['lpips', 'torch']
    name = 'lpips'
    display_name = 'LPIPS (AlexNet)'
    description = "Distance perceptuelle entre une image et sa référence (plus bas = plus proche)."

    #: Une DISTANCE : plus bas est mieux.
    direction = 'lower'
    #: Repli du gouverneur quand la mesure n'est pas concluante (la ligne du catalogue : 0,5 Go).
    recommended_vram_gb = 0.5

    def __init__(self):
        super().__init__()
        self._metric = None
        self.device = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        import lpips
        import torch
        from wama.model_manager.services.bench import (
            LPIPS_KEY, LPIPS_WEIGHTS, lpips_folder,
        )
        weights = lpips_folder() / LPIPS_WEIGHTS
        # Absent, on le DIT : la route l'installe, jamais `torch.hub` dans le $HOME.
        if not weights.exists():
            raise RuntimeError(f"LPIPS : {weights} absent — installer « LPIPS (AlexNet) » depuis "
                               f"le model manager (`pull_model {LPIPS_KEY}`)")
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        state = torch.load(weights, map_location='cpu', weights_only=True)
        metric = lpips.LPIPS(net='alex', pnet_rand=True, verbose=False)
        # Le réseau de LPIPS range les couches de `alexnet.features` par TRANCHES (`slice1.0`…),
        # sous leur indice d'origine : `features.<i>.<p>` → `slice<k>.<i>.<p>`.
        mapped = {}
        for key in metric.net.state_dict():
            _slice, index, param = key.split('.', 2)
            mapped[key] = state[f'features.{index}.{param}']
        metric.net.load_state_dict(mapped)
        self._metric = metric.eval().to(self.device)
        self._loaded, self._current_model = True, LPIPS_KEY
        logger.info('[LPIPS] chargé (%s)', self.device)
        return True

    def unload(self) -> None:
        if self._metric is not None:
            self._metric = None
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        self._loaded, self._current_model = False, None

    def _tensor(self, bgr):
        """Image BGR uint8 → tenseur RGB [-1, 1] (N, C, H, W), la convention de LPIPS."""
        import torch
        rgb = bgr[:, :, ::-1].copy()
        return (torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float().div(127.5).sub(1.0)
                .to(self.device))

    def score(self, image, reference) -> float:
        if not self._loaded:
            raise RuntimeError("LPIPSBackend : modèle non chargé (`load()` d'abord)")
        import torch
        with torch.no_grad():
            return float(self._metric(self._tensor(image), self._tensor(reference)).item())
