"""
Backend SAM Audio — un audio → la piste de chaque source NOMMÉE (tâche `audio-source-separation`,
séparation PAR REQUÊTE texte).

SAM Audio (Meta, 2025-12, « Segment Anything Audio ») : un modèle de flux (flow matching, un DiT)
sur les latents du codec DAC-VAE, conditionné par un TEXTE (« piano », « drums »…) ; il rend la
piste demandée et le reste. Code et poids sous SAM License (`manifests/libraries/sam_audio.json`,
même famille que SAM3) ; dépôts du Hub à accès contrôlé.

Retenu le 2026-11-13 (décision de Fabien, `PROSPECTION_PIPELINE`, « Au-delà de 6 pistes ») : la voie
ouverte au-delà des six pistes fixes de Demucs — on demande l'instrument voulu.

Ce que ce backend décide, et pourquoi :
  • il ne TÉLÉCHARGE RIEN : `config.json` et `checkpoint.pt` de chaque taille sont DÉCLARÉS ici
    (`SAM_AUDIO_FILES`, Hub à un commit — taille et empreinte mesurées le 2026-11-13), posés par le
    pilote `files` ; le code vient de la route `library` vendorisée (`sam_audio`, qui REQUIERT
    `dacvae` et `perception_models`), importé par `import_vendored` ;
  • la configuration publiée construirait trois pièces qui téléchargent ou exigent des librairies
    absentes, inutiles à une requête texte : le reclasseur visuel (ImageBind), l'ensemble de
    reclasseurs texte (CLAP + un « juge » tiré de `facebook/sam-audio-judge`) et le prédicteur
    d'intervalles (`facebook/pe-a-frame-large`). Elles sont mises à `None` au chargement
    (`DISABLED`) ; le chargement des poids les ignore déjà (`SAMAudio.load_state_dict`) ;
  • l'encodeur de texte `t5-base` est une sous-dépendance : le cache PARTAGÉ (où il est déjà) ;
  • l'audio est décodé par la brique commune (`audio_decode`), mono à la fréquence du codec
    (48 kHz), et passé en tenseur — jamais par `torchaudio.load` ;
  • la progression compte les passages du DiT (`_counting_forward`) : la résolution de l'équation
    (`odeint`) ne l'annonce pas.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from .source_separation_base import SourceSeparationBackend

logger = logging.getLogger(__name__)

#: Le commit FIGÉ de chaque dépôt servi (mesuré le 2026-11-13).
HF_REVISIONS = {'facebook/sam-audio-small': '20b65f56888142eebe7c37448c6f6b3b32600e9b'}


def folder_name(repo: str) -> str:
    """Le sous-dossier d'une taille (`facebook/sam-audio-small` → `sam-audio-small`)."""
    return repo.rsplit('/', 1)[-1]


def _hub_file(repo: str, name: str, size: int, sha256: str) -> dict:
    return {'path': f'{folder_name(repo)}/{name}', 'size': size, 'sha256': sha256,
            'origin': {'source': 'huggingface', 'repo': repo, 'revision': HF_REVISIONS[repo],
                       'file': name}}


#: Les tailles servies, par leur dépôt du Hub (l'identifiant que la clé de catalogue porte), et
#: leurs fichiers. Clé LITTÉRALE : l'inventaire la lit par AST.
SUPPORTED_MODELS = {
    'facebook/sam-audio-small': {'model_key': 'huggingface:facebook/sam-audio-small'},
}
SAM_AUDIO_FILES = {
    'facebook/sam-audio-small': [
        _hub_file('facebook/sam-audio-small', 'config.json', 2251,
                  '50a67c841676043afdd3af6484ef6a1b47e300e36ee24eb3e07c31da8216f47b'),
        _hub_file('facebook/sam-audio-small', 'checkpoint.pt', 5100547943,
                  '8c44fda9821fd9f2ec8977304e3c0f55290d9eacb6bbf25b4b8fb1f69c2a8c06'),
    ],
}
#: Les sources proposées PAR DÉFAUT (une requête de plus = une passe de plus) — clés du vocabulaire
#: commun des instruments (`midi_score.INSTRUMENT_LABELS`), qui sont aussi la forme que le modèle
#: attend : des groupes nominaux anglais en minuscules.
DEFAULT_STEMS = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'string ensemble',
                 'brass section', 'synth lead']
#: Les pièces de la configuration publiée qu'une requête texte n'emploie pas (cf. en-tête).
DISABLED = {'visual_ranker': None, 'text_ranker': None, 'span_predictor': None}
#: Le nombre de passages du DiT pour une requête : la méthode « midpoint » à pas de 2/32 sur
#: [0, 1] (`sam_audio.model.model.DFLT_ODE_OPT`) — 16 pas, deux évaluations chacun.
FORWARD_PASSES = 32
#: Le modèle traite son audio d'UN TENANT : mesuré le 2026-11-13 (RTX 4090, taille small), 30 s
#: tiennent (pic 14,3 Go dont 5,6 de poids), 60 s non (le décodage du codec veut 7,2 Go de plus).
#: Un morceau se sépare donc par TRANCHES (le patron de Demucs), qui se recouvrent et se raccordent
#: par un fondu enchaîné — chaque tranche part de son propre bruit : le recouvrement efface la
#: couture.
CHUNK_SECONDS = 20.0
OVERLAP_SECONDS = 1.0


def chunk_bounds(length: int, rate: int, chunk: float = CHUNK_SECONDS,
                 overlap: float = OVERLAP_SECONDS) -> list:
    """`[(début, fin)]` en échantillons : des tranches de `chunk` secondes qui se recouvrent de
    `overlap` ; une seule tranche pour un audio qui tient dans une."""
    size, step = int(chunk * rate), int((chunk - overlap) * rate)
    if length <= size:
        return [(0, length)]
    bounds, start = [], 0
    while start < length:
        end = min(start + size, length)
        bounds.append((start, end))
        if end >= length:
            break
        start += step
    return bounds


def stitch(pieces: list, bounds: list, length: int, rate: int,
           overlap: float = OVERLAP_SECONDS):
    """Raccorde les pistes des tranches (`pieces[i]` couvre `bounds[i]`) en un signal de `length`
    échantillons : dans chaque recouvrement, fondu linéaire de la tranche qui finit vers celle qui
    commence."""
    import numpy as np
    out = np.zeros(length, dtype=np.float32)
    weight = np.zeros(length, dtype=np.float32)
    fade = max(1, int(overlap * rate))
    for index, (piece, (start, end)) in enumerate(zip(pieces, bounds)):
        piece = np.asarray(piece, dtype=np.float32)[: end - start]
        ramp = np.ones(len(piece), dtype=np.float32)
        n = min(fade, len(piece))
        if index > 0:                                    # entre en fondu sur la tranche d'avant
            ramp[:n] = np.linspace(0.0, 1.0, n, dtype=np.float32)
        if index < len(bounds) - 1:                      # sort en fondu sous la suivante
            ramp[-n:] = np.minimum(ramp[-n:], np.linspace(1.0, 0.0, n, dtype=np.float32))
        out[start:start + len(piece)] += piece * ramp
        weight[start:start + len(piece)] += ramp
    return out / np.maximum(weight, 1e-6)


def model_folder() -> Path:
    """Le dossier des modèles (`settings.MODEL_PATHS['music']['sam_audio']`), un sous-dossier par
    taille, où le pilote `files` pose les fichiers déclarés."""
    from django.conf import settings
    return Path(settings.MODEL_PATHS['music']['sam_audio'])


def installed(name: str) -> bool:
    """Les fichiers déclarés de la taille `name` sont-ils présents (taille comprise) ?"""
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), SAM_AUDIO_FILES[name])


def stem_file_name(stem: str) -> str:
    """Le nom de fichier d'une source (« string ensemble » → « string-ensemble »)."""
    return '-'.join((stem or '').split()) or 'source'


class SamAudioBackend(SourceSeparationBackend):
    """SAM Audio : un audio de morceau → la piste de chaque source demandée par son nom."""

    ENGINE = "sam_audio"
    VENDORED = True
    name = "sam_audio"
    display_name = "SAM Audio"
    description = "Séparation de sources par requête texte (SAM Audio, Meta)."
    REQUIRED_PACKAGES = ["torchdiffeq", "einops", "transformers"]

    def __init__(self):
        super().__init__()
        self._model = None
        self._processor = None
        self._device = 'cpu'

    def load(self, model: Optional[str] = None) -> bool:
        name = model or 'facebook/sam-audio-small'
        if self._model is not None and self._current_model == name:
            return True
        if name not in SAM_AUDIO_FILES:
            raise ValueError(f"SAM Audio : modèle inconnu « {name} » ({', '.join(SAM_AUDIO_FILES)})")
        if not installed(name):
            raise RuntimeError(f"SAM Audio : {name} absent de {model_folder()} — installer "
                               f"« {SUPPORTED_MODELS[name]['model_key']} » depuis le model manager")
        self.unload()
        import torch
        sam_audio = self.import_vendored('sam_audio')
        folder = str(model_folder() / folder_name(name))
        model_obj = sam_audio.SAMAudio.from_pretrained(folder, **DISABLED)
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._model = model_obj.to(self._device).eval()
        self._processor = sam_audio.SAMAudioProcessor.from_pretrained(folder)
        self._loaded = True
        self._current_model = name
        logger.info("[SAM Audio] %s chargé (%s)", name, self._device)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._processor = None
        self._loaded = False
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[SAM Audio] déchargé")

    def _counting_forward(self, progress_callback, done_before: int, total: int):
        """Un `forward` d'INSTANCE qui compte ses passages : la résolution de l'équation appelle
        `self.forward` (`SAMAudio.separate`, sa fonction de champ), que l'attribut d'instance
        masque le temps d'une requête."""
        original = type(self._model).forward
        model = self._model
        state = {'calls': 0}

        def forward(*args, **kwargs):
            state['calls'] += 1
            if progress_callback:
                step = done_before + min(state['calls'], FORWARD_PASSES)
                progress_callback(min(99, int(100 * step / max(total, 1))))
            return original(model, *args, **kwargs)
        return forward

    def separate_sources(
        self,
        model_id: str,
        audio_path: str,
        output_dir: str,
        progress_callback: Optional[Callable[[int], None]] = None,
        stems: Optional[Sequence[str]] = None,
    ) -> Dict[str, str]:
        import numpy as np
        import soundfile as sf
        import torch
        from wama.common.utils.audio_decode import decode_audio

        self.load(model_id)
        requested = [s for s in dict.fromkeys(str(x).strip().lower() for x in (stems or DEFAULT_STEMS))
                     if s]
        if not requested:
            raise ValueError("SAM Audio : aucune source demandée")
        if progress_callback:
            progress_callback(0)
        rate = int(self._processor.audio_sampling_rate)
        samples, _ = decode_audio(audio_path, target_sr=rate, mono=True)
        wav = torch.from_numpy(np.asarray(samples, dtype=np.float32)).reshape(1, -1)
        if wav.numel() == 0:
            raise RuntimeError(f"SAM Audio : aucun signal lu dans {os.path.basename(audio_path)}")

        stem_name = Path(audio_path).stem
        length = wav.shape[-1]
        bounds = chunk_bounds(length, rate)
        total = FORWARD_PASSES * len(requested) * len(bounds)
        written = {}
        done = 0
        for source in requested:
            pieces = []
            for start, end in bounds:
                batch = self._processor(audios=[wav[:, start:end]],
                                        descriptions=[source]).to(self._device)
                self._model.forward = self._counting_forward(progress_callback, done, total)
                try:
                    result = self._model.separate(batch, predict_spans=False,
                                                  reranking_candidates=1)
                finally:
                    del self._model.forward                  # la méthode de la classe, rétablie
                pieces.append(result.target[0].detach().float().cpu().numpy().reshape(-1))
                done += FORWARD_PASSES
                del batch, result
            track = stitch(pieces, bounds, length, rate)
            path = os.path.join(output_dir, f'{stem_name}_{stem_file_name(source)}.wav')
            sf.write(path, np.clip(track, -1.0, 1.0), rate, subtype='PCM_16')
            written[source] = path
        if progress_callback:
            progress_callback(100)
        logger.info("[SAM Audio] %s : %d pistes (%s)", os.path.basename(audio_path), len(written),
                    ', '.join(written))
        return written
