"""La grille des TEMPS d'un audio — où tombe chaque temps joué, et quelles hauteurs y sonnent.

Née le 2026-10-16 de la page d'édition de la partition du composer (remarque de Fabien : « c'est
le temps de la partition qui doit guider » — l'anacrouse ne tombait pas où on l'entend). Mesuré
sur #754 : la partition écrit `Q:1/4=88`, l'audio est joué à 89,1 temps par minute et commence
à 0,8 s — un tempo écrit arrondi décale tout le morceau. Une partition ne se cale donc pas sur
l'audio par son tempo : elle se cale TEMPS PAR TEMPS sur ceux que l'audio joue.

Ce module ne connaît aucune partition. Il rend, pour un fichier audio :
  • `beats`  : l'instant (s) de chaque temps joué (`librosa.beat.beat_track`) — la grille sur
               laquelle la notation d'un MIDI place ses notes (`midi_score.played_beat_steps`) ;
  • `first_onset`, `last_onset` : la première et la dernière ATTAQUE (s) de ce qui sonne (à moins
               de 30 dB du plus fort), None sans attaque — où la page cale une partition qui ne
               porte pas ses repères (`WamaScore.anchorPairs`, 2026-11-15) ;
  • `duration`.
⚠ Jusqu'au 2026-11-15, il rendait aussi la `chroma` de chaque temps, que la page comparait aux
hauteurs écrites pour DEVINER le calage (`WamaScore.align`) : 6 à 16 s d'erreur mesurées sur les
pistes séparées de Fabien. Le calage se lit désormais aux repères de la partition (`score_timing`).

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
        key = f'wama_audio_rhythm:v2:{path}:{int(os.path.getmtime(path))}'
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
    first, last = attacks(samples, rate)
    return {'beats': [round(float(t), 3) for t in times],
            'first_onset': first, 'last_onset': last,
            'duration': round(len(samples) / float(rate), 3)}


def beat_ranks(beat_times):
    """`(rangs, instants)` des temps joués : le RANG de chaque temps compté de proche en proche —
    un intervalle d'environ un temps avance d'un rang, un temps MANQUÉ par le suivi de deux ; un
    temps doublé (à moins d'un demi-intervalle du précédent) est écarté.

    ⚠ Ni l'index (un temps manqué décalerait tous les suivants), ni `(t − t₀) / intervalle médian`
    (corrigé le 2026-11-15) : la grille tombe sur des trames de 23 ms, un intervalle vaut 28 OU 29
    trames, et la médiane (29) n'est pas l'intervalle réel (28,67) — divisé sur 300 temps, le rang
    dérive de trois. Mesuré sur « Plus d'eau » (#1632) : 105 intervalles de 28 trames, 211 de 29."""
    import numpy as np
    beats = np.asarray(beat_times, dtype=float)
    if len(beats) < 2:
        return np.zeros(len(beats), dtype=int), beats
    step = float(np.median(np.diff(beats)))
    ranks, times = [0], [float(beats[0])]
    for t in beats[1:]:
        gap = (float(t) - times[-1]) / step
        if gap < 0.5:
            continue
        ranks.append(ranks[-1] + max(1, int(round(gap))))
        times.append(float(t))
    return np.asarray(ranks, dtype=int), np.asarray(times, dtype=float)


def beat_period(beat_times) -> float:
    """L'intervalle (s) entre deux temps : la pente de la droite ajustée sur leurs RANGS
    (`beat_ranks`) — pas leur médiane, que la trame arrondit (89,15 bpm pour un morceau à 90,1 ; la
    partition complète écrivait `Q:89`, un MIDI au tempo écrit finissait 2,5 s en retard)."""
    import numpy as np
    ranks, times = beat_ranks(beat_times)
    if len(times) < 2 or ranks[-1] == ranks[0]:
        return 0.5
    slope = float(np.polyfit(ranks, times, 1)[0])
    return slope if slope > 0 else float(np.median(np.diff(times)))


#: Une attaque compte quand le son est à moins de ce nombre de dB de son plus fort : le résidu
#: d'une intro silencieuse (une piste séparée) n'en est pas une — mesuré sur la voix de #1636, la
#: première attaque retenue tombe à 24,5 s, où la voix entre.
ATTACK_FLOOR_DB = -30.0


def attacks(samples, rate: int):
    """`(première, dernière)` attaque (s) de ce qui SONNE dans `samples` — les débuts de notes
    (`librosa.onset`) là où le niveau est à moins d'`ATTACK_FLOOR_DB` du plus fort ; `(None, None)`
    sans aucune."""
    import librosa
    import numpy as np
    rms = librosa.feature.rms(y=samples, hop_length=HOP)[0]
    if not len(rms) or float(rms.max()) <= 0:
        return None, None
    loud = librosa.amplitude_to_db(rms, ref=float(rms.max())) > ATTACK_FLOOR_DB
    onsets = librosa.onset.onset_detect(y=samples, sr=rate, hop_length=HOP, units='frames')
    kept = [int(f) for f in onsets if f < len(loud) and loud[f]]
    if not kept:
        return None, None
    to_s = lambda f: round(float(librosa.frames_to_time(f, sr=rate, hop_length=HOP)), 3)  # noqa: E731
    return to_s(kept[0]), to_s(kept[-1])
