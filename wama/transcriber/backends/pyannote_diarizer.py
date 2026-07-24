"""
pyannote.audio Speaker Diarizer for Transcriber

Post-processes Whisper segments to assign a speaker_id to each segment by
computing the maximum time-overlap between each Whisper segment and the
pyannote diarization turns.

Requires:
    pip install pyannote.audio>=3.3.1

The pyannote/speaker-diarization-3.1 model is gated on HuggingFace.
Provide an access token via settings.HUGGINGFACE_TOKEN or the hf_token arg.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Module-level pipeline cache — reloaded only when the process restarts
_pipeline = None


def is_available() -> bool:
    """Return True if pyannote.audio is installed."""
    try:
        import pyannote.audio  # noqa: F401
        return True
    except ImportError:
        return False


def _load_pipeline(hf_token: Optional[str] = None):
    """Load (or return cached) pyannote speaker-diarization pipeline."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    import os
    import torch

    # ── CRITICAL: set HF_HUB_CACHE BEFORE importing pyannote/huggingface_hub ──
    # This routes all sub-downloads (weights, configs) to speech/diarization/
    # instead of the global AI-models/cache/huggingface/ fallback.
    try:
        from pathlib import Path
        from django.conf import settings as _s
        _dia_dir = _s.MODEL_PATHS.get('speech', {}).get(
            'diarization',
            _s.AI_MODELS_DIR / "models" / "speech" / "diarization"
        )
        Path(_dia_dir).mkdir(parents=True, exist_ok=True)
        _cache = str(_dia_dir)
        os.environ['HF_HUB_CACHE'] = _cache
        os.environ['HUGGINGFACE_HUB_CACHE'] = _cache
        logger.info(f"[pyannote] Cache → {_cache}")
    except Exception:
        pass

    from pyannote.audio import Pipeline

    # Resolve HuggingFace token from argument or Django settings
    token = hf_token
    if not token:
        try:
            from django.conf import settings
            token = getattr(settings, 'HUGGINGFACE_TOKEN', None)
        except Exception:
            pass

    logger.info("[pyannote] Loading speaker-diarization-3.1 pipeline…")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=token,
    )

    if torch.cuda.is_available():
        pipeline = pipeline.to(torch.device("cuda"))
        logger.info("[pyannote] Pipeline moved to CUDA")

    _pipeline = pipeline
    logger.info("[pyannote] Pipeline loaded ✓")
    return _pipeline


def unload_pipeline() -> bool:
    """
    Libère le pipeline pyannote de la VRAM (cache module-level).

    Utilisé par le reclaim mémoire centralisé (model_manager) et par le worker
    Transcriber en fin de diarisation. Idempotent : renvoie False si rien à faire.
    """
    global _pipeline
    if _pipeline is None:
        return False
    try:
        import torch
        try:
            _pipeline.to(torch.device("cpu"))
        except Exception:
            pass
        del _pipeline
        _pipeline = None
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("[pyannote] Pipeline unloaded ✓")
        return True
    except Exception as e:
        logger.warning(f"[pyannote] unload_pipeline failed: {e}")
        _pipeline = None
        return False


def _preload_audio(audio_path: str) -> dict:
    """
    Load audio into the {'waveform': tensor, 'sample_rate': int} dict expected by
    pyannote, bypassing its torchcodec/FFmpeg decoder (cassé dans ce venv).

    Délègue au helper commun `common/utils/audio_decode.decode_for_pyannote`
    (chaîne robuste soundfile → faster-whisper/PyAV → ffmpeg, gère m4a/mp3/aac).
    En cas d'échec total, on renvoie le chemin brut (dernier recours pyannote).
    """
    try:
        from wama.common.utils.audio_decode import decode_for_pyannote
        return decode_for_pyannote(audio_path, target_sr=16000)
    except Exception as e:
        logger.warning(f"[pyannote] decode failed ({e}), passing raw path")
        return audio_path  # type: ignore[return-value]


# ── Diarisation par tranches (audios longs) ──────────────────────────────────
# Seuils conservateurs : on ne chunk QUE les audios vraiment longs, et seulement
# quand l'audio est préchargé en mémoire (dict waveform) — sinon whole-file.
_CHUNK_THRESHOLD_S = 40 * 60   # au-delà de 40 min → tranches
_CHUNK_SIZE_S = 20 * 60        # tranche de 20 min
_CHUNK_OVERLAP_S = 60          # recouvrement 60 s (sert au stitching des locuteurs)
_STITCH_MIN_OVERLAP_S = 3.0    # recouvrement mini pour rattacher 2 labels entre tranches


def _annotation_to_turns(diarization) -> List[tuple]:
    """Extrait [(start, end, speaker)] d'une sortie pyannote (compat 3.x ↔ 4.x)."""
    annotation = diarization
    if not hasattr(annotation, 'itertracks'):
        annotation = (getattr(diarization, 'speaker_diarization', None)
                      or getattr(diarization, 'diarization', None)
                      or annotation)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def _run_pipeline_turns(pipeline, audio_input, diarize_kwargs) -> List[tuple]:
    """Un appel pipeline → liste de tours (start, end, speaker)."""
    return _annotation_to_turns(pipeline(audio_input, **diarize_kwargs))


def _stitch_labels(prev_turns: List[tuple], local_turns: List[tuple],
                   zone: tuple) -> dict:
    """
    Aligne les labels LOCAUX d'une tranche sur les labels GLOBAUX de la tranche
    précédente, via le recouvrement temporel dans `zone` (start, end).

    Renvoie {label_local: label_global} pour les locuteurs présents dans la zone.
    """
    z0, z1 = zone
    # overlap[llabel][glabel] = durée de recouvrement dans la zone
    overlap: dict = {}
    for ls, le, ll in local_turns:
        a0, a1 = max(ls, z0), min(le, z1)
        if a1 <= a0:
            continue
        for ps, pe, gl in prev_turns:
            b0, b1 = max(ps, z0), min(pe, z1)
            ov = min(a1, b1) - max(a0, b0)
            if ov > 0:
                overlap.setdefault(ll, {}).setdefault(gl, 0.0)
                overlap[ll][gl] += ov
    mapping = {}
    for ll, gmap in overlap.items():
        gl, best = max(gmap.items(), key=lambda kv: kv[1])
        if best >= _STITCH_MIN_OVERLAP_S:
            mapping[ll] = gl
    return mapping


def _diarize_chunked_from_disk(pipeline, audio_path, total_s, diarize_kwargs) -> List[tuple]:
    """
    Diarisation par tranches, chaque fenêtre étant décodée À LA DEMANDE depuis le
    disque (`common.audio_decode.decode_window`) → RAM bornée à ~une tranche, JAMAIS
    tout l'audio en mémoire (c'est le décodage complet d'un 2h+ qui gèle l'hôte WSL).

    Stitch les labels par recouvrement pour garder une identité de locuteur cohérente
    d'une tranche à l'autre. Best-effort : une tranche qui échoue est ignorée (les
    autres sont conservées) ; si tout échoue → liste vide (diarize() renvoie alors les
    segments sans locuteur, sans planter).
    """
    import torch
    from wama.common.utils.audio_decode import decode_window

    sr = 16000
    step = _CHUNK_SIZE_S - _CHUNK_OVERLAP_S
    starts, s = [], 0.0
    while s < total_s:
        starts.append(s)
        s += step
    logger.info(
        f"[pyannote] Audio long ({total_s/60:.0f} min) → diarisation en {len(starts)} "
        f"tranches de {_CHUNK_SIZE_S//60} min (recouvrement {_CHUNK_OVERLAP_S}s), "
        f"décodage à la demande depuis le disque"
    )

    global_turns: List[tuple] = []
    prev_turns: List[tuple] = []
    next_gid = 0

    for ci, cstart in enumerate(starts):
        cend = min(cstart + _CHUNK_SIZE_S, total_s)
        try:
            arr, _sr = decode_window(audio_path, target_sr=sr, start_s=cstart,
                                     duration_s=(cend - cstart), mono=False)
            wf = torch.from_numpy(arr).float()
            if wf.ndim == 1:
                wf = wf.unsqueeze(0)
            local = _run_pipeline_turns(pipeline, {'waveform': wf, 'sample_rate': sr}, diarize_kwargs)
            del wf, arr
        except Exception as e:
            logger.warning(f"[pyannote] tranche {ci} (@{cstart/60:.0f} min) échouée: {e} — ignorée")
            continue

        # Recale en temps global.
        local = [(ls + cstart, le + cstart, ll) for ls, le, ll in local]

        if not prev_turns:  # 1re tranche (ou toutes les précédentes ont échoué)
            labels = sorted({ll for _, _, ll in local})
            mapping = {ll: f"SPEAKER_{i:02d}" for i, ll in enumerate(labels)}
            next_gid = max(next_gid, len(mapping))
        else:
            zone = (cstart, min(cstart + _CHUNK_OVERLAP_S, cend))
            mapping = _stitch_labels(prev_turns, local, zone)
            for _, _, ll in local:  # locuteurs locaux non rattachés → nouveaux ids
                if ll not in mapping:
                    mapping[ll] = f"SPEAKER_{next_gid:02d}"
                    next_gid += 1

        mapped = [(ls, le, mapping[ll]) for ls, le, ll in local]
        # N'ajoute pas deux fois la zone de recouvrement (déjà couverte par la tranche
        # précédente), sauf pour la 1re tranche effective.
        cut = cstart + _CHUNK_OVERLAP_S if prev_turns else 0.0
        for ls, le, gl in mapped:
            if le > cut:
                global_turns.append((max(ls, cut), le, gl))
        prev_turns = mapped

    logger.info(f"[pyannote] Stitching terminé → {next_gid} locuteur(s) global(aux), "
                f"{len(global_turns)} tours")
    return global_turns


def diarize(
    audio_path: str,
    segments: list,
    num_speakers: Optional[int] = None,
    hf_token: Optional[str] = None,
) -> list:
    """
    Run speaker diarization and assign speaker_id to each segment.

    Args:
        audio_path:   Path to the audio file.
        segments:     List of TranscriptionSegment (speaker_id='') from Whisper.
        num_speakers: Optional number of speakers hint.
        hf_token:     HuggingFace access token for the gated pyannote model.

    Returns:
        Same list with speaker_id populated.
        Falls back gracefully (empty speaker_id) on any failure.
    """
    if not segments:
        return segments

    try:
        pipeline = _load_pipeline(hf_token)

        diarize_kwargs: dict = {}
        if num_speakers:
            diarize_kwargs["num_speakers"] = num_speakers

        # Durée via ffprobe (sans décoder) ; repli sur la fin du dernier segment ASR.
        from wama.common.utils.audio_decode import probe_duration_seconds
        total_s = probe_duration_seconds(audio_path)
        if not total_s and segments:
            total_s = max((getattr(s, 'end_time', 0.0) or 0.0) for s in segments)

        if total_s and total_s > _CHUNK_THRESHOLD_S:
            # Audios longs : diariser par tranches décodées À LA DEMANDE depuis le disque
            # (RAM bornée à ~une fenêtre). NE JAMAIS charger tout l'audio en mémoire — le
            # décodage complet d'un 2h+ gèle l'hôte WSL (crash 2026-07-24 : le worker meurt
            # dans _preload_audio, AVANT même la ligne « Diarizing »).
            dia_turns: List[tuple] = _diarize_chunked_from_disk(
                pipeline, audio_path, total_s, diarize_kwargs)
        else:
            # Court : un seul décodage en mémoire (léger) + un appel pipeline.
            audio_input = _preload_audio(audio_path)
            logger.info(f"[pyannote] Diarizing: {audio_path}")
            dia_turns = _run_pipeline_turns(pipeline, audio_input, diarize_kwargs)
        logger.info(f"[pyannote] {len(dia_turns)} diarization turns found")

        # Assign speaker to each Whisper segment by maximum time overlap
        unassigned = 0
        for seg in segments:
            best_speaker = ""
            best_overlap = 0.0
            for d_start, d_end, speaker in dia_turns:
                overlap = min(seg.end_time, d_end) - max(seg.start_time, d_start)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = speaker
            # Aucun recouvrement (mot isolé dans un trou entre deux tours) → on rattache au
            # locuteur du tour le PLUS PROCHE, plutôt que de laisser un segment sans locuteur
            # (sinon il apparaît « non identifié » et fausse le compte des intervenants).
            if not best_speaker:
                mid = (seg.start_time + seg.end_time) / 2.0
                nearest, ndist = "", float('inf')
                for d_start, d_end, speaker in dia_turns:
                    dist = (d_start - mid) if mid < d_start else (mid - d_end if mid > d_end else 0.0)
                    if dist < ndist:
                        ndist, nearest = dist, speaker
                best_speaker = nearest
                unassigned += 1
            seg.speaker_id = best_speaker

        logger.info(f"[pyannote] Speaker IDs assigned ✓ ({unassigned} segment(s) rattaché(s) au plus proche)")
        return segments

    except Exception as e:
        logger.error(f"[pyannote] Diarization failed — returning original segments: {e}")
        return segments
