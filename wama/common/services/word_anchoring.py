"""
Ancrage d'un texte SANS TEMPS sur des mots HORODATÉS — l'étage A de l'alignement forcé.

Le besoin (Fabien, 2026-09-23) : reprendre une transcription faite ailleurs (un export Sonal, un
texte) et la synchroniser à l'audio sans la retranscrire. Quand l'audio a déjà une sortie ASR
horodatée au mot (Whisper : 100 % des segments portent leurs `words`, mesuré le 2026-09-23), le
plus sûr n'est pas un modèle de plus : c'est de retrouver chaque mot du texte parmi les mots
entendus par l'ASR, et de lui en prendre l'heure.

COMMENT, et ce que chaque mot reçoit (`timing`) :
  • `exact`        — le mot est le même des deux côtés : il prend l'heure de l'ASR ;
  • `estimated`    — le texte a corrigé des mots que l'ASR a entendus AUTREMENT : ils se
                     partagent la durée réelle des mots remplacés (borne sûre, répartition estimée) ;
  • `interpolated` — le mot n'a rien en face (l'ASR ne l'a pas entendu) : il est placé entre ses
                     voisins ancrés. C'est là que l'étage B (aligneur acoustique) affinera.
L'appariement est la plus longue sous-suite commune des MOTS (RapidFuzz `Indel`), avec le
découpage commun à toutes les mesures de qualité (`text_metrics.comparable_words` — casse,
ponctuation, apostrophe).

CE QUE CE MODULE NE FAIT PAS : écouter. Il ne connaît que deux textes et des heures ; il ne sait
ni quel modèle a produit les mots horodatés, ni d'où vient le texte. C'est pourquoi il est commun :
tout texte à resynchroniser sur une sortie horodatée (sous-titres, correction) s'y ancre pareil.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

#: Les trois qualités d'un temps, de la plus sûre à la moins sûre (ordre = gravité croissante).
TIMINGS = ('exact', 'estimated', 'interpolated')


def timed_tokens(words: List[dict]) -> List[Tuple[str, float, float]]:
    """Mots horodatés (`{word, start, end}`, forme Whisper) → jetons comparables horodatés.
    Un mot qui se découpe en plusieurs jetons (« aujourd'hui ») leur donne à tous son intervalle."""
    from wama.common.services.text_metrics import comparable_words
    out = []
    for w in words or []:
        start, end = w.get('start'), w.get('end')
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        for token in comparable_words(w.get('word') or ''):
            out.append((token, float(start), float(max(start, end))))
    return out


def anchor_turns(turns: List[dict], words: List[dict]) -> Optional[Tuple[List[dict], dict]]:
    """Donne des temps aux tours de parole `turns` (`{text, …}`) à partir des mots horodatés `words`.

    Rend `(tours, rapport)` — chaque tour reçoit `start_time`, `end_time` et `words`
    (`{word, start, end, probability: None, timing}`, forme Whisper : `''.join(words)` redonne
    le texte) ; les autres clés du tour sont conservées. Le rapport compte les jetons par qualité
    de temps. None s'il n'y a aucun mot horodaté (rien sur quoi s'ancrer).
    """
    from rapidfuzz.distance import Indel
    from wama.common.services.text_metrics import comparable_words

    reference = timed_tokens(words)
    if not reference:
        return None

    display = []                  # par tour : ses mots d'affichage (le texte tel qu'écrit)
    target = []                   # (jeton, tour, mot d'affichage)
    for t, turn in enumerate(turns):
        shown = (turn.get('text') or '').split()
        display.append(shown)
        for w, word in enumerate(shown):
            for token in comparable_words(word):
                target.append((token, t, w))

    times: List[Optional[Tuple[float, float]]] = [None] * len(target)
    kinds: List[str] = ['interpolated'] * len(target)

    # ⚠ PLUS LONGUE SOUS-SUITE COMMUNE d'abord (`Indel` : insertions et suppressions seules), pas
    # une distance de Levenshtein : celle-ci départage les ex-aequo en SUBSTITUANT — sur « le chien
    # euh dort » contre « le chien dort sur… », elle appariait « euh » à « dort » et « dort » à
    # « sur », décalant tout ce qui suit (mesuré par `tests_word_anchoring`). Un ancrage doit
    # d'abord retrouver le plus de mots IDENTIQUES ; ce qui reste entre deux ancres s'estime.
    def settle_gap(text_from, text_to, ref_from, ref_to):
        count = text_to - text_from
        if count <= 0 or ref_to <= ref_from:
            return                           # rien en face : interpolé plus bas
        start, end = reference[ref_from][1], reference[ref_to - 1][2]
        for k in range(count):
            times[text_from + k] = (start + (end - start) * k / count,
                                    start + (end - start) * (k + 1) / count)
            kinds[text_from + k] = 'estimated'

    text_gap = ref_gap = 0
    for op in Indel.opcodes([x[0] for x in target], [r[0] for r in reference]):
        if op.tag != 'equal':
            continue
        settle_gap(text_gap, op.src_start, ref_gap, op.dest_start)
        for k in range(op.src_end - op.src_start):
            _, start, end = reference[op.dest_start + k]
            times[op.src_start + k] = (start, end)
            kinds[op.src_start + k] = 'exact'
        text_gap, ref_gap = op.src_end, op.dest_end
    settle_gap(text_gap, len(target), ref_gap, len(reference))

    _interpolate(times, first=reference[0][1], last=reference[-1][2])

    anchored = []
    for t, turn in enumerate(turns):
        per_word = {}
        for i, (_, tt, w) in enumerate(target):
            if tt == t:
                per_word.setdefault(w, []).append(i)
        words_out, previous_end = [], None
        for w, word in enumerate(display[t]):
            indexes = per_word.get(w)
            if indexes:
                start = min(times[i][0] for i in indexes)
                end = max(times[i][1] for i in indexes)
                timing = max((kinds[i] for i in indexes), key=TIMINGS.index)
            else:                          # ponctuation seule : collée au mot précédent
                start = end = previous_end if previous_end is not None else 0.0
                timing = 'interpolated'
            words_out.append({'word': ' ' + word, 'start': round(start, 3), 'end': round(end, 3),
                              'probability': None, 'timing': timing})
            previous_end = end
        entry = dict(turn)
        if words_out:
            entry.update(start_time=words_out[0]['start'], end_time=words_out[-1]['end'],
                         words=words_out)
        anchored.append(entry)

    report = {'tokens': len(target), **{k: kinds.count(k) for k in TIMINGS},
              'reference_tokens': len(reference)}
    report['exact_ratio'] = round(report['exact'] / report['tokens'], 4) if target else None
    return anchored, report


def _interpolate(times, first: float, last: float) -> None:
    """Place les jetons sans temps entre leurs voisins ancrés, puis rend la suite MONOTONE (un mot
    ne commence jamais avant la fin du précédent : l'ordre du texte est l'ordre de la parole)."""
    n, i = len(times), 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else first
        right = times[j][0] if j < n else last
        right = max(right, left)
        count = j - i
        for k in range(count):
            times[i + k] = (left + (right - left) * k / count, left + (right - left) * (k + 1) / count)
        i = j
    floor = 0.0
    for k in range(n):
        start, end = times[k]
        start = max(start, floor)
        end = max(end, start)
        times[k] = (start, end)
        floor = start
