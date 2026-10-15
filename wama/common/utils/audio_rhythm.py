"""La grille des TEMPS d'un audio — où tombe chaque temps joué, et quelles hauteurs y sonnent.

Née le 2026-10-16 de la page d'édition de la partition du composer (remarque de Fabien : « c'est
le temps de la partition qui doit guider » — l'anacrouse ne tombait pas où on l'entend). Mesuré
sur #754 : la partition écrit `Q:1/4=88`, l'audio est joué à 89,1 temps par minute et commence
à 0,8 s — un tempo écrit arrondi décale tout le morceau. Une partition ne se cale donc pas sur
l'audio par son tempo : elle se cale TEMPS PAR TEMPS sur ceux que l'audio joue.

Ce module ne connaît aucune partition. Il rend, pour un fichier audio :
  • `beats`  : l'instant (s) de chaque temps joué (`librosa.beat.beat_track`) ;
  • `chroma` : pour chaque temps, l'énergie des 12 classes de hauteur (do … si) entre ce temps
               et le suivant, sur 0-255 — de quoi reconnaître QUELLES notes y sonnent ;
  • `duration`.
L'alignement d'une partition sur cette grille (choisir à quel temps joué correspond le premier
temps écrit) se fait là où la partition est lue — la brique `score_view`, par `WamaScore.align`.

Décodage par la brique commune (`audio_decode`, robuste en WSL), calcul mis en cache par
(fichier, date) comme les pics d'onde (`preview_utils._add_server_peaks`) : ~3 s pour 3 min.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

SAMPLE_RATE = 22050
HOP = 512
CACHE_SECONDS = 7 * 86400


def beat_grid(path: str):
    """`{beats, chroma, duration}` de l'audio `path` (voir l'en-tête) ; None s'il est illisible."""
    try:
        key = f'wama_audio_rhythm:v1:{path}:{int(os.path.getmtime(path))}'
    except OSError:
        return None
    from django.core.cache import cache
    grid = cache.get(key)
    if grid is not None:
        return grid
    try:
        grid = compute_beat_grid(path)
    except Exception as error:      # un audio qu'on ne sait pas lire n'a pas de grille, rien de plus
        logger.warning('[audio_rhythm] %s : %s', path, error)
        return None
    cache.set(key, grid, CACHE_SECONDS)
    return grid


def compute_beat_grid(path: str) -> dict:
    import librosa
    import numpy as np

    from .audio_decode import decode_audio_at
    samples, rate = decode_audio_at(path, SAMPLE_RATE)
    _tempo, frames = librosa.beat.beat_track(y=samples, sr=rate, hop_length=HOP, units='frames')
    times = librosa.frames_to_time(frames, sr=rate, hop_length=HOP)
    chroma = librosa.feature.chroma_stft(y=samples, sr=rate, hop_length=HOP)
    # `sync` découpe aux temps ET ajoute le début et la fin : le segment i+1 est [temps i, temps i+1).
    per_beat = librosa.util.sync(chroma, frames, aggregate=np.median)[:, 1:1 + len(frames)]
    peak = per_beat.max(axis=0)
    peak[peak <= 0] = 1.0
    scaled = np.rint(per_beat / peak * 255).astype(int).T
    return {'beats': [round(float(t), 3) for t in times],
            'chroma': scaled.tolist(),
            'duration': round(len(samples) / float(rate), 3)}
