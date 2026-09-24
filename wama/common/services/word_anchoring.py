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

ÉTAGE B (`refine_turns`) : les passages `estimated`/`interpolated` sont confiés à un aligneur
ACOUSTIQUE — mais ce module ne le charge pas davantage : il reçoit une fonction
`align_window(début, fin, mots)` et la capacité de l'aligneur (`max_seconds`), et décide seul des
FENÊTRES : chaque passage incertain est encadré par ses deux voisins sûrs, qui l'y tiennent
(« gardes ») ; un passage plus long que la capacité se coupe ENTRE deux mots.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

#: Les qualités d'un temps, de la plus sûre à la moins sûre (ordre = gravité croissante).
#: `aligned` = posé par un aligneur ACOUSTIQUE (étage B, `refine_turns`) : il a écouté le mot,
#: mais sur une fenêtre bornée par ses voisins — moins sûr qu'un mot entendu tel quel par l'ASR.
TIMINGS = ('exact', 'aligned', 'estimated', 'interpolated')
#: Les temps que l'étage B reprend : ceux qu'aucun modèle n'a entendus.
UNSURE_TIMINGS = ('estimated', 'interpolated')


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


#: Marge (s) ajoutée au bord d'une fenêtre que ne tient aucun mot sûr (début ou fin du texte, garde
#: elle-même estimée) : l'audio d'un mot mal estimé peut déborder de son estimation.
WINDOW_PAD = 0.5


def refine_turns(turns: List[dict], align_window, max_seconds: float, *,
                 audio_end: Optional[float] = None) -> Tuple[List[dict], dict]:
    """ÉTAGE B : reprend à l'oreille les mots `estimated`/`interpolated` de tours ANCRÉS.

    `align_window(début, fin, mots) -> [AlignedWord | None]` est le geste de l'aligneur (décodage
    de la fenêtre compris, heures RELATIVES à `début`) ; `max_seconds` sa capacité. Chaque passage
    incertain est aligné avec ses deux voisins pour gardes — un voisin sûr borne la fenêtre à son
    propre mot, et le passage ne peut pas déborder sur lui. Un passage plus long que la capacité
    se coupe entre deux mots, aux heures estimées ; chaque morceau garde alors le mot voisin, même
    estimé, et une marge.

    Rend `(tours, rapport)` : tours COPIÉS, mots repris marqués `aligned` avec leur confiance
    acoustique en `probability`. Une fenêtre qui échoue ou dépasse la capacité GARDE ses
    estimations — l'étage B n'aggrave jamais l'étage A. Rapport : `unsure` (mots à reprendre),
    `aligned`, `windows`, `failed`, `too_long`.
    """
    import copy
    import logging

    out = copy.deepcopy(turns)
    flat = [w for turn in out for w in (turn.get('words') or [])]
    report = {'unsure': 0, 'aligned': 0, 'windows': 0, 'failed': 0, 'too_long': 0}

    runs, i = [], 0
    while i < len(flat):
        if flat[i].get('timing') not in UNSURE_TIMINGS:
            i += 1
            continue
        j = i
        while j < len(flat) and flat[j].get('timing') in UNSURE_TIMINGS:
            j += 1
        runs.append((i, j))
        i = j
    report['unsure'] = sum(j - i for i, j in runs)

    orphans = set()                 # mots d'une fenêtre alignée que l'aligneur n'a pas su épeler
    for i, j in runs:
        for a, b in _split_run(flat, i, j, max_seconds):
            outcome, unspelled = _align_chunk(flat, a, b, align_window, max_seconds, audio_end)
            if outcome == 'aligned':
                report['windows'] += 1
                report['aligned'] += (b - a) - len(unspelled)
                orphans.update(unspelled)
            else:
                report[outcome] += 1
                if outcome == 'failed':
                    logging.getLogger(__name__).info(
                        "[word_anchoring] fenêtre non alignée (%d mots) : estimations gardées", b - a)

    if orphans:
        # Un mot sans lettre prononçable (chiffre, sigle ponctué) se replace entre ses voisins
        # désormais alignés — ses anciennes heures étaient celles d'avant l'alignement.
        times = [None if k in orphans else (w['start'], w['end']) for k, w in enumerate(flat)]
        _interpolate(times, first=flat[0]['start'], last=flat[-1]['end'])
        for k in orphans:
            flat[k]['start'], flat[k]['end'] = round(times[k][0], 3), round(times[k][1], 3)
            flat[k]['timing'] = 'interpolated'

    floor = 0.0                     # l'ordre du texte reste l'ordre de la parole
    for w in flat:
        w['start'] = max(w['start'], floor)
        w['end'] = max(w['end'], w['start'])
        floor = w['start']
    for turn in out:
        words = turn.get('words') or []
        if words:
            turn['start_time'], turn['end_time'] = words[0]['start'], words[-1]['end']
    return out, report


def _window(flat, a: int, b: int, audio_end: Optional[float] = None):
    """Fenêtre d'audio des mots [a, b) et de leurs gardes : `(début, fin, indices alignés)`."""
    left = a - 1 if a > 0 else None
    right = b if b < len(flat) else None
    start = flat[left]['start'] if left is not None else flat[a]['start'] - WINDOW_PAD
    if left is not None and flat[left].get('timing') in UNSURE_TIMINGS:
        start -= WINDOW_PAD
    end = flat[right]['end'] if right is not None else flat[b - 1]['end'] + WINDOW_PAD
    if right is not None and flat[right].get('timing') in UNSURE_TIMINGS:
        end += WINDOW_PAD
    if audio_end is not None:
        end = min(end, audio_end)
    indexes = ([left] if left is not None else []) + list(range(a, b)) \
        + ([right] if right is not None else [])
    return max(0.0, start), end, indexes


def _split_run(flat, i: int, j: int, max_seconds: float) -> List[Tuple[int, int]]:
    """Coupe le passage [i, j) ENTRE deux mots, aux heures estimées, en morceaux dont la fenêtre
    — gardes et marges comprises — tient dans la capacité de l'aligneur."""
    chunks, a = [], i
    while a < j:
        b = a + 1
        while b < j:
            start, end, _ = _window(flat, a, b + 1)
            if end - start > max_seconds:
                break
            b += 1
        chunks.append((a, b))
        a = b
    return chunks


def _align_chunk(flat, a: int, b: int, align_window, max_seconds: float,
                 audio_end: Optional[float]):
    """Aligne les mots [a, b) avec leurs voisins pour gardes. Rend `(issue, non épelés)`."""
    start, end, indexes = _window(flat, a, b, audio_end)
    if end - start > max_seconds:
        return 'too_long', []
    try:
        placed = align_window(start, end, [(flat[k].get('word') or '').strip() for k in indexes])
    except Exception:
        return 'failed', []
    if len(placed) != len(indexes):
        return 'failed', []

    unspelled = []
    for k, found in zip(indexes, placed):
        if not a <= k < b:
            continue                            # une garde garde ses heures
        if found is None:
            unspelled.append(k)
            continue
        flat[k].update(start=round(start + found.start, 3), end=round(start + found.end, 3),
                       probability=found.score, timing='aligned')
    return 'aligned', unspelled


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


# ── Bornes d'un texte horodaté : déplacer une jonction, couper un tour (2026-09-24) ──────────────
# Le geste de l'éditeur (Fabien, 2026-09-23) : UNE borne par jonction — la fin d'un tour EST le
# début du suivant —, deux actions seulement (déplacer une borne, couper un tour), et jamais un mot
# perdu ni coupé en deux. Commun, sans modèle : tout texte horodaté au mot (sous-titres, corpus de
# parole) se découpe pareil ; l'éditeur du transcriber n'en est que le premier consommateur.

#: Marge (s) autour d'un tour pour y chercher les mots de référence qui lui reviennent.
REFERENCE_MARGIN = 0.5


def spoken_text(words: List[dict]) -> str:
    """Le texte que portent des mots au format Whisper (`''.join` des mots, sans bord blanc)."""
    return ''.join((w.get('word') or '') for w in words or []).strip()


def _same_text(a: str, b: str) -> bool:
    return ' '.join((a or '').split()) == ' '.join((b or '').split())


def _timed(w) -> bool:
    return isinstance(w, dict) and isinstance(w.get('start'), (int, float)) \
        and isinstance(w.get('end'), (int, float))


def turn_words(turn: dict, reference: Optional[List[dict]] = None) -> Optional[List[dict]]:
    """Les mots horodatés d'un tour, COHÉRENTS avec son texte — ou None si le tour n'a pas de temps.

    Dans l'ordre : ses propres mots s'ils redisent son texte ; sinon son texte (corrigé depuis)
    s'ANCRE sur les mots de `reference` (la sortie ASR) qui tombent dans son intervalle ; sinon ses
    mots sont répartis au prorata des caractères dans son intervalle (`interpolated` : dit, jamais
    caché). Les temps restent DANS l'intervalle du tour — ses bornes sont celles que l'utilisateur voit.
    """
    import copy

    text = turn.get('text') or ''
    start, end = turn.get('start_time'), turn.get('end_time')
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    end = max(end, start)
    own = [w for w in turn.get('words') or [] if isinstance(w, dict)]
    if own and all(_timed(w) for w in own) and _same_text(spoken_text(own), text):
        return copy.deepcopy(own)
    if not text.split():
        return []

    nearby = [w for w in reference or [] if _timed(w)
              and w['end'] >= start - REFERENCE_MARGIN and w['start'] <= end + REFERENCE_MARGIN]
    anchored = anchor_turns([{'text': text}], nearby) if nearby else None
    if anchored:
        words = anchored[0][0].get('words') or []
    else:
        shown = text.split()
        total = sum(len(w) for w in shown) or 1
        words, cursor = [], start
        for word in shown:
            span = (end - start) * len(word) / total
            words.append({'word': ' ' + word, 'start': cursor, 'end': cursor + span,
                          'probability': None, 'timing': 'interpolated'})
            cursor += span
    floor = start
    for w in words:                          # dans l'intervalle du tour, et dans l'ordre
        w['start'] = round(min(max(w['start'], floor), end), 3)
        w['end'] = round(min(max(w['end'], w['start']), end), 3)
        floor = w['start']
    return words


def _cut(words: List[dict], at: float) -> Optional[Tuple[int, float]]:
    """La coupe ENTRE deux mots la plus proche de `at` : `(index du 1er mot à droite, heure)`.

    L'heure est `at` lui-même quand il tombe dans le silence entre deux mots, sinon le bord de
    silence le plus proche — une borne ne tranche jamais un mot. On ne coupe pas devant une
    ponctuation seule (« ! » irait ouvrir le tour suivant). None s'il n'y a aucune coupe possible.
    """
    from wama.common.services.text_metrics import comparable_words

    best = None
    for k in range(1, len(words)):
        if not comparable_words(words[k].get('word') or ''):
            continue
        low = words[k - 1]['end']
        high = max(low, words[k]['start'])
        placed = min(max(at, low), high)
        distance = abs(placed - at)
        if best is None or distance < best[0]:
            best = (distance, k, placed)
    return (best[1], round(best[2], 3)) if best else None


def _rebuilt(turn: dict, words: List[dict], start: float, end: float) -> dict:
    out = dict(turn)
    out.update(words=words, text=spoken_text(words), start_time=round(start, 3),
               end_time=round(end, 3))
    return out


def move_boundary(left: dict, right: dict, at: float,
                  reference: Optional[List[dict]] = None) -> Optional[Tuple[dict, dict]]:
    """Déplace la jonction entre deux tours CONSÉCUTIFS vers `at` : les mots passent d'un côté à
    l'autre selon leur heure, la borne se pose entre deux mots, et chaque tour garde au moins un mot.

    Rend les deux tours réécrits (texte REFAIT depuis leurs mots : aucun mot perdu ni inventé ; les
    autres clés — locuteur, confiance… — conservées), ou None si la borne ne peut pas se poser là.
    """
    left_words, right_words = turn_words(left, reference), turn_words(right, reference)
    if left_words is None or right_words is None:
        return None
    words = left_words + right_words
    cut = _cut(words, at)
    if cut is None:
        return None
    k, placed = cut
    placed = min(max(placed, left['start_time']), right['end_time'])
    return (_rebuilt(left, words[:k], left['start_time'], placed),
            _rebuilt(right, words[k:], placed, right['end_time']))


def split_turn(turn: dict, at: float,
               reference: Optional[List[dict]] = None) -> Optional[Tuple[dict, dict]]:
    """Coupe un tour en deux à `at`, entre deux mots : les mots d'avant restent, ceux d'après
    forment le nouveau tour (mêmes clés, même locuteur). None si aucune coupe n'est possible —
    un tour d'un seul mot, par exemple."""
    words = turn_words(turn, reference)
    if not words:
        return None
    cut = _cut(words, at)
    if cut is None:
        return None
    k, placed = cut
    return (_rebuilt(turn, words[:k], turn['start_time'], placed),
            _rebuilt(turn, words[k:], placed, turn['end_time']))
