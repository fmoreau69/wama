"""
Backend MuScriptor — un audio → un MIDI à une piste par instrument (tâche `audio-to-midi`).

MuScriptor (Kyutai + Mirelo, 2026, arXiv 2607.08168) : transformeur décodeur qui écrit les notes de
36 groupes d'instruments (voix et batterie comprises) par tranches de 5 s, puis cale le tout sur une
grille de temps trouvée par Beat This! (tempo, métrique, barres de mesure). Code MIT ; poids
CC BY-NC 4.0, dépôt HuggingFace à accès contrôlé (`PROSPECTION_PIPELINE`, veille du 2026-10-16).
Librairies par la route `library`, sans dépendances (`manifests/libraries/muscriptor.json`).

Ce que ce backend décide, et pourquoi :
  • les POIDS viennent du catalogue (`installed_snapshot`), jamais de `~/.cache/muscriptor` : on
    passe le fichier local à `load_model`, son `config.json` est à côté — aucun téléchargement ;
  • le point de contrôle de Beat This! n'a pas de dépôt officiel sur HuggingFace : il est tiré au
    PREMIER USAGE de sa source déclarée (`external_sources`, `beat_this`), empreinte épinglée, par
    le téléchargement commun de la route (`download_asset`), et rangé À CÔTÉ du modèle — le
    précédent du parent MERT de SheetSage2. La librairie, laissée à elle-même, le rangerait dans
    le `$HOME` par `torch.hub` ;
  • l'audio est décodé par la brique commune (`audio_decode`) : `beat_this` lit un fichier par
    `torchaudio.load`, cassé en WSL (`reference_torchcodec_broken`) — on lui passe le signal.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from .midi_extraction_base import MidiExtractionBackend

logger = logging.getLogger(__name__)

HF_ID = "MuScriptor/muscriptor-large"
MODEL_KEY = f"huggingface:{HF_ID}"
#: La fréquence que le modèle attend (`muscriptor.transcription_model._SAMPLE_RATE`).
SAMPLE_RATE = 16000

# Clé LITTÉRALE : l'inventaire la lit par AST. Nom, description et VRAM sont au REGISTRE.
SUPPORTED_MODELS = {
    "MuScriptor/muscriptor-large": {"model_key": "huggingface:MuScriptor/muscriptor-large"},
}

#: Le point de contrôle de Beat This! que MuScriptor emploie (`detect_grid`, « final0 »), DÉCLARÉ :
#: chemin sous le dossier du modèle, taille et empreinte relevées le 2026-10-16 sur le serveur des
#: auteurs (81 058 141 octets, conforme à son `content-length`).
BEAT_CHECKPOINT = {
    'path': 'beat_this/final0.ckpt',
    'size': 81058141,
    'sha256': '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331',
    'origin': {'source': 'beat_this', 'file': 'final0.ckpt'},
}


def model_folder() -> Path:
    """Le dossier de la famille du modèle dans `AI-models` (le parent du dépôt HF)."""
    from wama.common.utils.model_components import installed_snapshot
    return installed_snapshot(MODEL_KEY).parent.parent.parent


def beat_checkpoint(folder: Path) -> Path:
    """Le point de contrôle de Beat This!, tiré de sa source déclarée s'il manque (empreinte
    vérifiée au fil du flux, jamais de fichier partiel à sa place). Lève si le téléchargement
    échoue : sans grille de temps, la partition n'aurait ni mesures ni tempo."""
    target = folder / BEAT_CHECKPOINT['path']
    if target.exists():
        return target
    from wama.common.external_sources import proxies_for
    from wama.model_manager.services.model_installer import declared_file_url, download_asset
    target.parent.mkdir(parents=True, exist_ok=True)
    origin = BEAT_CHECKPOINT['origin']
    res = download_asset(declared_file_url(origin), str(target), sha256=BEAT_CHECKPOINT['sha256'],
                         min_bytes=BEAT_CHECKPOINT['size'] // 2,
                         proxies=proxies_for(origin['source']))
    if not res.get('ok'):
        raise RuntimeError(f"Beat This! : point de contrôle non obtenu — {res.get('error')}")
    return target


#: Tolérance (en temps) d'un temps à la phase dominante, et la part des temps qu'elle doit garder.
PHASE_TOLERANCE = 0.15
MIN_PHASE_SHARE = 0.6


def robust_tempo(beats):
    """(bpm, écart RMS en s, part des temps gardés, temps gardés) des temps `beats`, ajustés APRÈS
    re-numérotation sur la grille de leur intervalle médian, sur leur PHASE DOMINANTE.

    POURQUOI (mesuré le 2026-10-16 sur cinq rendus YuE2) : `muscriptor.utils.beats.fit_tempo`
    ajuste le RANG de chaque temps contre son instant.
      • Un seul temps manqué (ou doublé) par le suivi décale tous les rangs suivants : #754 sortait
        à 181 ms d'écart autour de 88,5 bpm — re-numéroté, 21 ms (0,03 temps), tempo constant.
      • Un suivi qui bascule sur les CONTRETEMPS dans une section mêle des temps décalés d'un
        demi-temps : #755, #756, #343 restaient à ~0,28 temps d'écart — la signature d'un mélange de
        phases, pas d'un tempo qui dérive. On garde la phase majoritaire : retrait des temps à plus
        de `PHASE_TOLERANCE` temps, ajustement (deux tours).
      • La PREMIÈRE droite est robuste (Theil-Sen : pente médiane des paires, ordonnée médiane) :
        un ajustement aux moindres carrés penche vers un bloc de contretemps en fin de morceau,
        garde sa phase et rejette de bons temps (vu au test : 118,3 bpm pour 120)."""
    import numpy as np
    beats = np.asarray(beats, dtype=float)
    ibi = float(np.median(np.diff(beats)))
    ranks = np.rint((beats - beats[0]) / ibi).astype(int)
    keep = np.concatenate([[True], np.diff(ranks) > 0])
    ranks, times = ranks[keep], beats[keep]
    total = len(times)
    first, second = np.triu_indices(len(times), 1)
    slope = float(np.median((times[second] - times[first]) / (ranks[second] - ranks[first])))
    intercept = float(np.median(times - slope * ranks))
    for _ in range(2):
        off = (times - (intercept + slope * ranks)) / slope
        inside = np.abs(off) <= PHASE_TOLERANCE
        if inside.sum() < 2:
            break
        ranks, times = ranks[inside], times[inside]
        slope, intercept = np.polyfit(ranks, times, 1)
    residual = times - (intercept + slope * ranks)
    return 60.0 / float(slope), float(residual.std()), len(times) / max(total, 1), times


def beat_grid(wav, rate: int, checkpoint: str, device: str):
    """La grille de temps de MuScriptor (`BeatGrid`), avec un REPLI robuste : la règle de la
    librairie d'abord (`detect_grid`), et si elle refuse un tempo « non fixe », le même suivi
    re-numéroté (`robust_tempo`), jugé au MÊME seuil (`MAX_TEMPO_RESIDUAL`). Lève
    `BeatDetectionError` si les deux refusent — le morceau n'a alors vraiment pas de tempo fixe."""
    import numpy as np
    from muscriptor.utils.beats import (MAX_TEMPO_RESIDUAL, MIN_BEATS, BeatDetectionError,
                                        BeatGrid, detect_grid, infer_beats_per_bar)
    try:
        return detect_grid(wav, rate, checkpoint=checkpoint, device=device)
    except BeatDetectionError as error:
        if 'no fixed tempo' not in str(error):
            raise
        refused = error
    from beat_this.inference import Audio2Beats
    signal = wav.mean(dim=0).detach().cpu().numpy()
    beats, downbeats = Audio2Beats(checkpoint_path=checkpoint, device=device, dbn=False)(signal, rate)
    beats, downbeats = np.asarray(beats, dtype=float), np.asarray(downbeats, dtype=float)
    if len(beats) < MIN_BEATS:
        raise refused
    bpm, residual, share, kept = robust_tempo(beats)
    if residual > MAX_TEMPO_RESIDUAL * 60.0 / bpm or share < MIN_PHASE_SHARE:
        raise refused
    logger.info("[MuScriptor] grille re-numérotée : %.2f bpm (écart %.0f ms, %.0f %% des temps ; %s)",
                bpm, residual * 1000, share * 100, refused)
    # Les temps de la PHASE GARDÉE : la librairie y mesure le retard des attaques
    # (`BeatGrid.with_onset_delay`) — des contretemps le fausseraient d'un demi-temps.
    return BeatGrid(bpm=bpm, beats_per_bar=infer_beats_per_bar(kept, downbeats),
                    first_downbeat=float(downbeats[0]) if len(downbeats) else float(kept[0]),
                    beats=kept)


class MuScriptorBackend(MidiExtractionBackend):
    """MuScriptor : un audio de morceau → son MIDI multi-instrument."""

    ENGINE = "muscriptor"
    name = "muscriptor"
    display_name = "MuScriptor"
    recommended_vram_gb = 8.0
    description = "Audio → MIDI multi-instrument (MuScriptor large, Kyutai + Mirelo)."
    REQUIRED_PACKAGES = ["muscriptor", "beat_this", "rotary_embedding_torch"]
    # Noms pip (≠ noms d'import) ; sans dépendances, comme leurs manifestes de librairie
    # (`constraints.no_deps`) : les dépendances PyPI de muscriptor déplaceraient starlette.
    PIP_PACKAGES = ["muscriptor", "beat-this", "rotary-embedding-torch"]
    PIP_NO_DEPS = True

    def __init__(self):
        super().__init__()
        self._model = None
        self._folder = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._model is not None:
            return True
        import torch
        from muscriptor.transcription_model import TranscriptionModel
        from wama.common.utils.model_components import installed_snapshot

        snapshot = installed_snapshot(MODEL_KEY)
        weights = snapshot / 'model.safetensors'
        if not weights.exists():
            raise RuntimeError(f"MuScriptor : {weights} absent du snapshot installé")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # float32 + autocast fp16 sur CUDA : le choix par défaut de la librairie hors MPS.
        self._model = TranscriptionModel.load_model(weights_path=weights, device=device)
        self._folder = snapshot.parent.parent.parent
        self._loaded = True
        self._current_model = HF_ID
        logger.info("[MuScriptor] chargé (%s, %s)", snapshot.name[:12], device)
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
        logger.info("[MuScriptor] déchargé")

    def extract_midi(
        self,
        model_id: str,
        audio_path: str,
        output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bytes:
        if self._model is None:
            self.load()
        import torch
        from muscriptor.events import ProgressEvent
        from muscriptor.utils.beats import BeatDetectionError
        from wama.common.utils.audio_decode import decode_audio_at

        if progress_callback:
            progress_callback(0)
        samples, rate = decode_audio_at(audio_path, SAMPLE_RATE)
        wav = torch.from_numpy(samples).float().unsqueeze(0)          # [1, T], mono 16 kHz
        try:
            grid = beat_grid(wav, rate, str(beat_checkpoint(self._folder)), str(self._model._device))
        except BeatDetectionError as error:
            # Un morceau sans tempo stable s'écrit au tempo de remplacement, sans métrique —
            # la règle « best-effort » de la librairie, dite au journal.
            logger.warning("[MuScriptor] pas de grille de temps (%s) : tempo de remplacement", error)
            grid = None

        def events():
            for ev in self._model.transcribe((wav, rate)):
                if isinstance(ev, ProgressEvent) and progress_callback and ev.total:
                    progress_callback(int(95 * ev.completed / ev.total))
                yield ev

        with torch.inference_mode():
            midi = self._model.events_to_midi_bytes(events(), beat_grid=grid)
        if not midi:
            raise RuntimeError("MuScriptor n'a rien transcrit")
        if progress_callback:
            progress_callback(100)
        return midi
