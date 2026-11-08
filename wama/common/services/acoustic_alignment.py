"""
Étage B de l'alignement forcé, CHARGÉ — l'aligneur du CATALOGUE réécoute les mots dont l'heure
n'est pas sûre (2026-11-03 : sorti du worker du transcriber pour servir aussi l'avatar 3D).

`word_anchoring.refine_turns` décide des FENÊTRES sans charger aucun modèle. Ce module fait le
reste, une fois pour tous ses appelants : choisir l'aligneur au catalogue (tâche `alignment`,
langue de l'audio, départagé par `select_model`), l'installer par la route s'il manque
(`ctx.ensure_model` : la tâche attend), le charger, lui donner les fenêtres d'audio, le décharger.

Il porte aussi le DOUTE que l'ASR ne dit pas. Whisper date chaque mot, mais rattache une pause au
mot voisin : sur la card #1532, « faisant » était daté de 3,78 à 4,78 s alors que la voix se tait
de 3,9 à 4,5 s — un avatar qui étale ce mot sur sa durée articule pendant le silence.
`doubt_words_over_silence` marque `estimated` un mot dont l'intervalle contient un silence d'au
moins `UNSURE_GAP_SECONDS` (trames d'énergie de la brique `speech_activity`) : l'étage B le
réécoute, tenu par ses voisins sûrs. Un mot douté à tort ne coûte qu'une fenêtre d'alignement —
l'étage B ne dégrade jamais l'étage A (`refine_turns`).
"""
from __future__ import annotations

from typing import List, Optional

#: Un silence au moins aussi long DANS un mot daté le rend douteux. Deux trames de 100 ms : une
#: occlusion de consonne (« apprendre ») en fait une au plus, une pause de la voix davantage
#: (#1532 : six trames dans « faisant », aucun autre mot plus d'une).
UNSURE_GAP_SECONDS = 0.2


def aligner_model(language: str):
    """L'aligneur du CATALOGUE pour `language` : un modèle de tâche `alignment` dont les langues
    couvrent celle de l'audio, départagé par la brique commune (`select_model` : VRAM, déjà chargé).
    Aucun nom de modèle ici — un aligneur d'une autre langue se déclare dans `model_config`."""
    from wama.common.utils.lang_routing import model_languages
    from wama.model_manager.models import AIModel
    from wama.model_manager.services import select_model

    if not language:
        return None
    keys = [m.model_key for m in AIModel.objects.filter(source='transcriber')
            if (m.capabilities or {}).get('task') == 'alignment'
            and ({'*', language} & set(model_languages(m.capabilities)))]
    # ⚠ `candidates=[]` ne filtre RIEN : sans candidat, on s'arrête ici.
    # `downloaded_only=False` : un aligneur absent est tiré quand même — la route l'installe au
    # moment du process, qui attend (`ctx.ensure_model`).
    return select_model(source='transcriber', candidates=keys, downloaded_only=False) if keys else None


def alignment_said(report: dict, model_name: str) -> str:
    """La phrase de la console après l'étage B — la même pour tous les appelants."""
    said = (f"Alignement acoustique ({model_name}) : {report['aligned']} mot(s) recalé(s) sur "
            f"{report['unsure']} estimé(s), en {report['windows']} fenêtre(s)")
    kept = report['failed'] + report['too_long']
    if kept:
        said += f" — {kept} passage(s) gardent leur estimation"
    return said


def doubt_words_over_silence(turns: List[dict], audio_path: str,
                             min_gap: float = UNSURE_GAP_SECONDS) -> int:
    """Marque `estimated` (sur place) chaque mot `exact` de `turns` dont l'intervalle contient un
    silence d'au moins `min_gap` secondes ; rend le nombre de mots doutés. L'audio est décodé en
    ENTIER : pour un audio court (une réplique, un avatar), pas pour un entretien de deux heures."""
    import numpy as np
    from wama.common.utils.audio_decode import decode_audio_at
    from wama.common.utils.speech_activity import FRAME_SECONDS, active_frames

    wave, sr = decode_audio_at(audio_path, 16000)
    active = active_frames(wave, sr)
    if not len(active) or not active.any():
        return 0                          # trop court, ou aucune voix : rien à mettre en doute
    needed = max(1, int(round(min_gap / FRAME_SECONDS)))
    doubted = 0
    for turn in turns:
        for word in turn.get('words') or []:
            if word.get('timing', 'exact') != 'exact':
                continue
            a = int(float(word['start']) / FRAME_SECONDS)
            b = int(np.ceil(float(word['end']) / FRAME_SECONDS))
            run = longest = 0
            for voiced in active[a:b]:
                run = 0 if voiced else run + 1
                longest = max(longest, run)
            if longest >= needed:
                word['timing'] = 'estimated'
                doubted += 1
    return doubted


def timed_words(segments, audio_path: str, language: str, *, audio_end: Optional[float] = None,
                ctx=None) -> dict:
    """Les MOTS HORODATÉS d'une ÉCOUTE d'`audio_path` (2026-11-08, les paroles du composer, décision
    de Fabien : « le Transcriber sait déjà le faire, il faut réutiliser »). Le 3ᵉ appelant de
    `refine` : chacun a SON étage A — le transcriber ancre un document repris (`anchor_turns`),
    l'avatar doute des mots qui avalent une pause (`doubt_words_over_silence`), ici les mots d'un
    tour que le modèle d'écoute n'a pas datés sont répartis dans son intervalle ; l'étage B et sa
    phrase (`alignment_said`) sont les mêmes pour les trois.

    `segments` : des tours (`.start`/`.end`/`.text`/`.words`, objets ou dicts). Un tour garde ses
    mots s'ils sont datés (Whisper) ; sinon ils sont répartis dans son intervalle
    (`word_anchoring.turn_words`, `interpolated` — Qwen3-ASR ne date que des tranches de 30 s) ;
    puis l'aligneur du catalogue réécoute les mots incertains (`refine`, installé par la route si
    `ctx`). Sans aligneur pour la langue, ou s'il échoue, les heures de l'étage A restent, et c'est
    DIT dans le rapport (`aligned`, `reason`). Rend `{'words': [{word, start, end, timing}],
    'aligner': clé ou '', 'report': {...}, 'reason': '', 'said': la phrase de la console}`."""
    from wama.common.services.word_anchoring import turn_words

    def read(segment, name):
        return segment.get(name) if isinstance(segment, dict) else getattr(segment, name, None)

    turns = []
    for segment in segments or ():
        start = read(segment, 'start') if read(segment, 'start') is not None else read(segment, 'start_time')
        end = read(segment, 'end') if read(segment, 'end') is not None else read(segment, 'end_time')
        turn = {'text': read(segment, 'text') or '', 'start_time': start, 'end_time': end,
                'words': list(read(segment, 'words') or [])}
        words = turn_words(turn)
        if words:
            for word in words:
                word.setdefault('timing', 'exact')
            turns.append({**turn, 'words': words})
    out = {'words': [], 'aligner': '', 'report': {}, 'reason': '', 'said': ''}
    if not turns:
        out['reason'] = 'aucun mot'
        return out
    try:
        refined = refine(turns, audio_path, language, audio_end=audio_end, ctx=ctx)
    except Exception as exc:                  # l'étage A reste : une estimation dite, jamais perdue
        from wama.common.utils.task_skeleton import ServiceNotReady
        if isinstance(exc, ServiceNotReady):
            raise
        refined, out['reason'] = None, f"aligneur en échec : {exc}"
    if refined is None:
        out['reason'] = out['reason'] or f"aucun aligneur pour la langue « {language or '?'} »"
        out['said'] = f"Alignement acoustique : {out['reason']} — les heures restent estimées."
    else:
        turns, out['report'], model = refined
        out['aligner'] = model.model_key
        out['said'] = alignment_said(out['report'], model.name)
    out['words'] = [{'word': (w.get('word') or '').strip(), 'start': w['start'], 'end': w['end'],
                     'timing': w.get('timing', 'exact')}
                    for turn in turns for w in turn['words'] if (w.get('word') or '').strip()]
    return out


def refine(turns: List[dict], audio_path: str, language: str, *, audio_end: Optional[float] = None,
           ctx=None):
    """ÉTAGE B par l'aligneur du catalogue : rend `(tours, rapport, modèle)`, ou None quand le
    catalogue n'a aucun aligneur pour `language` (les heures restent celles de l'étage A).

    `ctx` (contexte de tâche) : l'aligneur absent est installé par la route et la tâche ATTEND
    (`ServiceNotReady`). LÈVE si l'aligneur ne se charge pas — à l'appelant de dire si son
    process échoue (transcriber) ou garde l'étage A (avatar)."""
    from wama.common.backends.manager import backend_for_model
    from wama.common.services.word_anchoring import refine_turns
    from wama.common.utils.audio_decode import decode_window

    model = aligner_model(language)
    if model is None:
        return None
    if ctx is not None:                   # absent : la route l'installe, la tâche attend
        ctx.ensure_model(model.model_key)
    aligner_class = backend_for_model(model)
    if aligner_class is None:
        raise RuntimeError(f"aucun moteur installé ne sert {model.name}")
    aligner = aligner_class()
    if not aligner.load(model.hf_repo):
        raise RuntimeError(f"{model.name} indisponible")
    try:
        def align_window(start, end, words):
            wave, _ = decode_window(audio_path, aligner.sample_rate, start, end - start)
            return aligner.align(wave, words)
        turns, report = refine_turns(turns, align_window, aligner.max_audio_seconds,
                                     audio_end=audio_end)
    finally:
        aligner.unload()
    return turns, report, model
