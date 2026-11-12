"""
Backend Demucs v4 — un audio → une piste par source (tâche `audio-source-separation`).

Demucs v4 « Hybrid Transformer » (Meta, Rouard, Massa & Défossez 2023, arXiv 2211.08553) : un
U-Net temps + spectre à transformeur croisé. Code MIT (`demucs` 4.0.1, déjà dans le venv par
audiocraft, déclaré par son manifeste de librairie) ; les poids sont publiés par ses auteurs sur
leur serveur, sans dépôt officiel sur le Hub (`external_sources['demucs']`).

Retenu le 2026-11-12 (décision de Fabien, `PROSPECTION_PIPELINE`, veille « Pistes séparées ») :
déjà installé, aucune librairie à ajouter, aucune dérive ; BS-RoFormer SW, meilleur en six pistes,
viendra au même contrat quand la licence de ses poids sera éclaircie.

Ce que ce backend décide, et pourquoi :
  • il ne TÉLÉCHARGE RIEN : les points de contrôle sont DÉCLARÉS ici (`DEMUCS_FILES`, taille et
    empreinte mesurées le 2026-11-12 — l'empreinte est aussi dans leur nom, convention torch.hub),
    lus par la découverte du catalogue et posés par le pilote `files`. La librairie les tirerait
    de son serveur vers `torch.hub` (`$HOME`) au premier usage : on lui passe le DOSSIER local
    (`LocalRepo`), et les « sacs » de modèles (`htdemucs_ft` = quatre modèles spécialisés, un par
    piste) sont lus dans les `.yaml` que la librairie embarque — aucun accès réseau ;
  • l'audio est décodé par la brique commune (`audio_decode`), pas par `torchaudio.load`
    (cassé en WSL, `reference_torchcodec_broken`) ; les pistes s'écrivent par `soundfile` ;
  • la progression vient d'un exécuteur à nous (`_CountingPool`), que `apply_model` reçoit à la
    place du sien : la librairie ne l'annonce que par une barre `tqdm` dans la console.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from .source_separation_base import SourceSeparationBackend

logger = logging.getLogger(__name__)

#: Le dossier du serveur de Meta où vivent les modèles v4 (`demucs/remote/files.txt`, `root:`).
REMOTE_FOLDER = 'hybrid_transformer'


def _checkpoint(name: str, size: int, sha256: str) -> dict:
    """Un point de contrôle déclaré, posé à PLAT dans le dossier (`LocalRepo` ne lit pas les
    sous-dossiers) et tiré du serveur des auteurs."""
    return {'path': name, 'size': size, 'sha256': sha256,
            'origin': {'source': 'demucs', 'file': f'{REMOTE_FOLDER}/{name}'}}


#: Les modèles servis, leurs pistes (l'ordre de la librairie) et leurs fichiers — mesurés le
#: 2026-11-12 sur les fichiers du serveur (`content-length` et sha256, préfixe égal au nom).
#: Clé LITTÉRALE : l'inventaire la lit par AST. Nom, description et VRAM sont au REGISTRE.
SUPPORTED_MODELS = {
    'htdemucs_6s': {'model_key': 'demucs:htdemucs_6s'},
    'htdemucs_ft': {'model_key': 'demucs:htdemucs_ft'},
}
STEMS = {
    'htdemucs_6s': ['drums', 'bass', 'other', 'vocals', 'guitar', 'piano'],
    'htdemucs_ft': ['drums', 'bass', 'other', 'vocals'],
}
DEMUCS_FILES = {
    'htdemucs_6s': [
        _checkpoint('5c90dfd2-34c22ccb.th', 54996327,
                    '34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd'),
    ],
    'htdemucs_ft': [
        _checkpoint('f7e0c4bc-ba3fe64a.th', 84141271,
                    'ba3fe64ae8ef66ac9a4857222ce48efbdc5eb3ad375cb79dd13debee5aaa4066'),
        _checkpoint('d12395a8-e57c48e6.th', 84141271,
                    'e57c48e6b0e38af4f7118d7bd08c49f0a0c0edf7d09143bdd902ea0d237303e6'),
        _checkpoint('92cfc3b6-ef3bcb9c.th', 84141271,
                    'ef3bcb9c8b40d14ae5d51b6db2587339cc12c6b77c0be151ce6d69002e087bf2'),
        _checkpoint('04573f0d-f3cf25b2.th', 84141271,
                    'f3cf25b222c4eed7cd49dd8b2c9597d50c18bd154090f7b919cfa5f93cf22c49'),
    ],
}
#: Le nombre de décalages aléatoires moyennés (`shifts` de la librairie) : 1, son défaut — chaque
#: décalage de plus refait tout le passage pour « jusqu'à 0,2 dB » (sa documentation).
SHIFTS = 1


def model_folder() -> Path:
    """Le dossier des modèles (`settings.MODEL_PATHS['music']['demucs']`), où le pilote `files`
    pose les points de contrôle des deux lignes."""
    from django.conf import settings
    return Path(settings.MODEL_PATHS['music']['demucs'])


def installed(name: str) -> bool:
    """Les fichiers déclarés du modèle `name` sont-ils présents (taille comprise) ?"""
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), DEMUCS_FILES[name])


def checkpoint_globals() -> list:
    """Ce que les points de contrôle de Demucs désérialisent hors tenseurs — et RIEN d'autre.

    Torch ≥ 2.6 charge par défaut en `weights_only=True`, et un `.th` de Demucs est un paquet
    picklé (`{'klass': HTDemucs, 'kwargs': …}`) : refusé. Plutôt que `weights_only=False` (qui
    exécuterait n'importe quel pickle), on autorise les seuls objets que les cinq fichiers
    déclarés nomment — relevés le 2026-11-12 par `torch.serialization.
    get_unsafe_globals_in_checkpoint` : `demucs.htdemucs.HTDemucs`, `fractions.Fraction` (la
    durée de tranche, 39/5 s), et pour le sac affiné `numpy.core.multiarray.scalar` et
    `numpy.dtype`. L'empreinte de chaque fichier est déjà vérifiée par la route et par la
    librairie (`check_checksum`)."""
    from fractions import Fraction

    import numpy as np
    from demucs.htdemucs import HTDemucs
    core = getattr(np, '_core', None) or np.core          # numpy 2 range `core` sous `_core`
    dtypes = [type(np.dtype(t)) for t in (np.float16, np.float32, np.float64,
                                          np.int32, np.int64, np.bool_)]
    return [HTDemucs, Fraction, (core.multiarray.scalar, 'numpy.core.multiarray.scalar'),
            np.dtype, *dtypes]


class _CountingPool:
    """L'exécuteur passé à `apply_model` : il exécute chaque tranche À LA DEMANDE, comme celui de
    la librairie (`DummyPoolExecutor`), et compte les tranches rendues pour la progression."""

    class _Result:
        def __init__(self, pool, func, args, kwargs):
            self.pool, self.func, self.args, self.kwargs = pool, func, args, kwargs

        def result(self):
            out = self.func(*self.args, **self.kwargs)
            self.pool.tick()
            return out

    def __init__(self, total: int, progress_callback=None):
        self.total, self.done, self.progress_callback = max(int(total), 1), 0, progress_callback

    def submit(self, func, *args, **kwargs):
        return _CountingPool._Result(self, func, args, kwargs)

    def tick(self):
        self.done += 1
        if self.progress_callback:
            self.progress_callback(min(99, 5 + int(90 * self.done / self.total)))


def chunk_count(length: int, samplerate: int, segment: float, overlap: float = 0.25) -> int:
    """Le nombre de tranches que `apply_model` découpe dans `length` échantillons (sa règle :
    `range(0, length, stride)`, `stride = (1 - overlap) × segment`)."""
    stride = max(1, int((1 - overlap) * int(samplerate * float(segment))))
    return len(range(0, int(length), stride))


class DemucsBackend(SourceSeparationBackend):
    """Demucs v4 : un audio de morceau → ses pistes (4 ou 6 selon le modèle)."""

    ENGINE = "demucs"
    name = "demucs"
    display_name = "Demucs"
    recommended_vram_gb = 1.0          # pic mesuré 0,61 Go (2026-11-12), cf. la ligne du catalogue
    description = "Séparation de sources (Demucs v4 hybrid transformer, Meta)."
    REQUIRED_PACKAGES = ["demucs"]
    PIP_PACKAGES = ["demucs"]

    def __init__(self):
        super().__init__()
        self._model = None
        self._device = 'cpu'

    def load(self, model: Optional[str] = None) -> bool:
        name = model or 'htdemucs_6s'
        if self._model is not None and self._current_model == name:
            return True
        if name not in DEMUCS_FILES:
            raise ValueError(f"Demucs : modèle inconnu « {name} » ({', '.join(DEMUCS_FILES)})")
        if not installed(name):
            raise RuntimeError(f"Demucs : {name} absent de {model_folder()} — installer "
                               f"« {SUPPORTED_MODELS[name]['model_key']} » depuis le model manager")
        self.unload()
        import torch
        from demucs.pretrained import REMOTE_ROOT
        from demucs.repo import AnyModelRepo, BagOnlyRepo, LocalRepo
        # Poids : le dossier LOCAL (empreinte vérifiée par la librairie au chargement) ; sacs : les
        # `.yaml` EMBARQUÉS par la librairie, qui ne nomment que des signatures.
        weights = LocalRepo(model_folder())
        with torch.serialization.safe_globals(checkpoint_globals()):
            self._model = AnyModelRepo(weights, BagOnlyRepo(REMOTE_ROOT, weights)).get_model(name)
        self._model.eval()
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._loaded = True
        self._current_model = name
        logger.info("[Demucs] %s chargé (%s)", name, self._device)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._loaded = False
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[Demucs] déchargé")

    def separate_sources(
        self,
        model_id: str,
        audio_path: str,
        output_dir: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, str]:
        import numpy as np
        import soundfile as sf
        import torch
        from demucs.apply import BagOfModels, apply_model
        from demucs.audio import convert_audio
        from wama.common.utils.audio_decode import decode_audio

        self.load(model_id)
        if progress_callback:
            progress_callback(0)
        samples, rate = decode_audio(audio_path, target_sr=self._model.samplerate, mono=False)
        wav = torch.from_numpy(np.atleast_2d(np.asarray(samples, dtype=np.float32)))
        if wav.numel() == 0:
            raise RuntimeError(f"Demucs : aucun signal lu dans {os.path.basename(audio_path)}")
        wav = convert_audio(wav, rate, self._model.samplerate, self._model.audio_channels)
        # La normalisation de la ligne de commande de la librairie (`demucs.separate.main`) : le
        # mélange centré-réduit sur sa moyenne mono, rétabli à la sortie.
        ref = wav.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        models = self._model.models if isinstance(self._model, BagOfModels) else [self._model]
        pool = _CountingPool(
            len(models) * SHIFTS * chunk_count(wav.shape[-1], self._model.samplerate,
                                               models[0].segment),
            progress_callback)
        with torch.inference_mode():
            sources = apply_model(self._model, ((wav - mean) / std)[None], shifts=SHIFTS,
                                  split=True, overlap=0.25, device=self._device, pool=pool)[0]
        sources = sources * std + mean

        stem = Path(audio_path).stem
        written = {}
        for name, track in zip(self._model.sources, sources):
            path = os.path.join(output_dir, f'{stem}_{name}.wav')
            data = track.detach().cpu().numpy().T                     # (temps, canaux)
            sf.write(path, np.clip(data, -1.0, 1.0), self._model.samplerate, subtype='PCM_16')
            written[name] = path
        if progress_callback:
            progress_callback(100)
        logger.info("[Demucs] %s : %d pistes (%s)", os.path.basename(audio_path), len(written),
                    ', '.join(written))
        return written
