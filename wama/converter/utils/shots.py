"""Les PLANS d'une vidéo — le producteur de segments du Converter (`ROUTE §10.7.14 ⑲`).

L'analyse est celle de ffmpeg (filtre `scdet`, déjà là : aucune librairie de plus) : il note à
chaque image un score de changement de 0 à 100 et dit les images qui passent le seuil. Ce module en
tire des PLANS — des segments qui couvrent la vidéo du début à la fin, sans trou ni chevauchement —
sous les noms communs des marques (`start`, `end`, et `score` : la force de la coupe qui ouvre le
plan, absente pour le premier). Le fichier n'est jamais modifié ; où les plans se rangent et
comment ils se lisent est l'affaire du commun (`common/utils/media_marks`).
"""
from __future__ import annotations

import re
import subprocess
from typing import List, Optional, Tuple

#: Le seuil du filtre, de 0 à 100. Plus bas : plus de coupes (les fondus, les mouvements
#: brusques) ; plus haut : les seules coupes franches. MESURÉ le 2026-11-25 sur 33 coupes de
#: vérité connue (un témoin de 29 coupes franches entre deux caméras embarquées — une sur deux dans
#: la même caméra : même capot, autre lieu —, une vidéo de démonstration, deux fondus) : 32 au
#: seuil de 6, 27 à la valeur par défaut de ffmpeg (10), aucune fausse coupe sur ces vidéos.
#: ⚠ Une prise CONTINUE rend de fausses coupes à tout seuil fixe : ce sont des sauts d'exposition
#: de la caméra (toute l'image s'assombrit d'un coup), des pics isolés comme une coupe — une caméra
#: embarquée de 2 h 20 : 73 au seuil de 6, 15 au seuil de 10. Ce défaut sert les vidéos montées,
#: celles qu'on coupe par leurs plans ; le remède mesuré (confirmer chaque candidate en comparant
#: les formes) est consigné, pas construit : `ROUTE §10.7.14 ⑲`.
THRESHOLD = 6.0
#: En deçà, deux coupes sont un même changement (un flash, un fondu) : elles n'en font qu'une, la
#: plus forte des deux.
MIN_DURATION = 0.5
#: L'analyse se fait sur une image réduite (jamais agrandie) : un changement de plan se voit à
#: cette taille, et une vidéo 4K ne coûte pas seize fois une vidéo HD.
ANALYSIS_WIDTH = 320

_CUT = re.compile(r'lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)')


def cuts_of(output: str) -> List[Tuple[float, float]]:
    """Les coupes que ffmpeg a dites, `(instant, score)`, dans l'ordre du temps — pure."""
    return sorted((float(time), float(score)) for score, time in _CUT.findall(output or ''))


def shots_from_cuts(cuts, duration: float, min_duration: float = MIN_DURATION) -> List[dict]:
    """Les plans d'une vidéo de `duration` secondes, depuis ses coupes — pure. Une coupe qui ferait
    un plan plus court que `min_duration` (au début, entre deux coupes, à la fin) est écartée : le
    plan rejoint son voisin. De deux coupes plus proches que `min_duration` (un fondu se dit
    souvent en deux fois), la plus FORTE dit où le plan change. Sans coupe, la vidéo est UN
    plan."""
    kept: List[Tuple[float, float]] = []
    for time, score in sorted(cuts):
        if time >= duration:
            continue
        if time - (kept[-1][0] if kept else 0.0) >= min_duration:
            kept.append((time, score))
        elif kept and score > kept[-1][1]:
            kept[-1] = (time, score)
    if kept and duration - kept[-1][0] < min_duration:
        kept.pop()
    starts = [(0.0, None)] + kept
    ends = [time for time, _score in kept] + [duration]
    return [{'start': round(start, 3), 'end': round(end, 3),
             'score': None if score is None else round(score, 1)}
            for (start, score), end in zip(starts, ends)]


def detect_shots(path: str, threshold: float = THRESHOLD, min_duration: float = MIN_DURATION,
                 timeout: int = 3600) -> List[dict]:
    """Les plans de la vidéo `path` (chemin absolu). Lève `ValueError` sans flux vidéo lisible,
    `RuntimeError` si ffmpeg échoue."""
    from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg, get_ffmpeg_exe
    from wama.common.utils.media_probe import probe_video
    duration = float((probe_video(path) or {}).get('duration') or 0)
    if duration <= 0:
        raise ValueError("aucun flux vidéo lisible : pas de plans à détecter")
    ffmpeg = get_ffmpeg_exe()
    watched = f"scale='min({ANALYSIS_WIDTH},iw)':-2,scdet=threshold={float(threshold):g}"
    done = subprocess.run(
        [ffmpeg, '-hide_banner', '-nostats', '-v', 'info', '-i', adapt_path_for_ffmpeg(path, ffmpeg),
         '-map', '0:v:0', '-an', '-sn', '-vf', watched, '-f', 'null', '-'],
        capture_output=True, text=True, errors='replace', timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"ffmpeg n'a pas pu analyser la vidéo : {(done.stderr or '')[-300:]}")
    return shots_from_cuts(cuts_of(done.stderr), duration, float(min_duration))


def shots_job(video: str, threshold: Optional[float] = None, min_duration: Optional[float] = None,
              user_id=None) -> str:
    """La fonction `converter.shots` LANCÉE (un nœud du Studio) : analyse la vidéo reçue (chemin
    relatif à MEDIA_ROOT), range ses plans par la porte commune et rend une phrase. Des réglages
    donnés REMPLACENT la piste rangée ; sans réglage, une piste à jour est gardée."""
    import os

    from django.conf import settings

    from wama.common.utils import media_marks
    rel = str(video or '').replace('\\', '/')
    if os.path.isabs(rel):
        rel = os.path.relpath(rel, str(settings.MEDIA_ROOT)).replace('\\', '/')
    asked = {name: value for name, value in (('threshold', threshold),
                                             ('min_duration', min_duration)) if value is not None}
    if not media_marks.make_media_marks(rel, 'shots', asked or None):
        raise ValueError("les plans n'ont pas pu être détectés (vidéo absente ou illisible)")
    return media_marks.summary(rel, 'shots')
