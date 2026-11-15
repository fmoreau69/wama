"""Les REPÈRES d'une partition : où tombe chacune de ses mesures dans l'audio dont elle est tirée.

Né le 2026-11-15 (demande de Fabien, mesuré sur ses cards de pistes séparées) : la page d'édition
DEVINAIT le calage d'une partition sur son audio (ressemblance des hauteurs, ±16 temps) et se
trompait de 6 à 16 s sur les huit partitions mesurées — alors que le moteur qui l'a écrite connaît
l'instant de chaque note. L'extraction NOTE donc ce qu'elle sait, et la page le LIT.

Le repère est un couple par barre de mesure : l'instant ÉCRIT (ms, au tempo de la partition, celui
que la gravure et le synthétiseur d'abcjs comptent depuis la 1re note) et l'instant de l'AUDIO (s)
où cette barre tombe. Entre deux repères, au prorata. Une correction de la partition garde la durée
de ses mesures (`WamaScore.retime`) : les repères restent justes.

Ils voyagent DANS le texte ABC, sur une ligne de commentaire de l'en-tête — abcjs l'ignore, une
partition exportée la garde sans dommage, et elle suit la partition partout où elle va (piste seule,
version gardée, export). Une partition fournie n'en a pas : la page la cale alors sur les attaques
de l'audio (`audio_rhythm`, première et dernière).

    with_sync(abc, pairs) -> str      la partition avec ses repères (remplace ceux qu'elle avait)
    sync_of(abc) -> [(ms, s)] | None  ses repères
    written_bar_ms(bar_quarters, tempi) -> [ms]   l'instant écrit de chaque barre (tempo par mesure)
    written_measures(abc) -> [noires]           la longueur écrite de chaque mesure
    bar_lines_from_beats(beats, written)        leurs barres sur une grille de temps DATÉS
    sync_from_beats(abc, beats) -> [(ms, s)]    les repères qui s'en déduisent (SheetSage2)

Lus côté page par `WamaScore.syncOf` (même ligne, même forme).
"""
from __future__ import annotations

import re

#: La ligne des repères : `% wama-sync: <ms>:<s> <ms>:<s> …` (un couple par barre, mesure 1 d'abord).
SYNC_PREFIX = '% wama-sync:'
_PAIR = re.compile(r'(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?)')


def with_sync(abc: str, pairs) -> str:
    """`abc` avec la ligne de ses repères, posée juste avant `K:` (l'en-tête) — celle qu'il avait
    est remplacée. Sans couple (moins de deux), la partition est rendue sans repères."""
    lines = [line for line in str(abc or '').split('\n') if not line.startswith(SYNC_PREFIX)]
    pairs = [(float(ms), float(s)) for ms, s in (pairs or [])]
    if len(pairs) < 2:
        return '\n'.join(lines)
    text = SYNC_PREFIX + ' ' + ' '.join(f'{ms:.0f}:{s:.3f}' for ms, s in pairs)
    at = next((i for i, line in enumerate(lines) if line.startswith('K:')), 1 if lines else 0)
    return '\n'.join(lines[:at] + [text] + lines[at:])


def without_sync(abc: str) -> str:
    """La partition sans ses repères — ce qu'on donne à un MOTEUR (YuE2 suit une partition) : les
    repères sont à WAMA, une ligne `% …` de plus n'a rien à faire dans une consigne de génération,
    et le lecteur de sections de YuE2 prend toute ligne `% ` pour un nom de section."""
    return '\n'.join(line for line in str(abc or '').split('\n') if not line.startswith(SYNC_PREFIX))


def sync_of(abc: str):
    """Les repères `[(ms écrit, s d'audio)]` de la partition, ou None."""
    for line in str(abc or '').split('\n'):
        if line.startswith(SYNC_PREFIX):
            pairs = [(float(a), float(b)) for a, b in _PAIR.findall(line[len(SYNC_PREFIX):])]
            return pairs if len(pairs) >= 2 else None
    return None


def audio_at(pairs, ms: float) -> float:
    """L'instant d'audio (s) du temps écrit `ms`, par les repères `pairs` : au prorata entre deux,
    prolongé au-delà par la pente du repère extrême — la règle de `WamaScore.timeMap` côté page."""
    p = sorted(pairs)
    i = 0 if ms <= p[0][0] else (len(p) - 2 if ms >= p[-1][0]
                                 else next(k for k in range(len(p) - 1) if p[k + 1][0] > ms))
    (a_ms, a_s), (b_ms, b_s) = p[i], p[i + 1]
    return a_s + (ms - a_ms) * (b_s - a_s) / (b_ms - a_ms) if b_ms != a_ms else a_s


def bar_lines_from_beats(beats, written):
    """L'instant (s) de chaque BARRE d'une partition écrite sur des temps DATÉS — `beats` :
    `[(instant, position dans la mesure à partir de 1, temps par mesure, valeur du temps), …]` (la
    grille d'un moteur qui note sa pulsation, SheetSage2) ; `written` : la longueur ÉCRITE de chaque
    mesure, en noires (`written_measures`, lue dans la partition). Rend `len(written) + 1` instants,
    ou None quand la grille ne donne pas une mesure par temps fort (rien de deviné : la page cale
    alors sur les attaques).

    La mesure k commence sur le k-ième temps fort. Ce que la notation COMPLÈTE de silence se lit en
    comparant l'audio à l'écrit (mesuré le 2026-11-15 sur deux sorties réelles de SheetSage2) :
      • la 1re mesure, plus courte dans l'audio que sur le papier (« padded leading 1/8 span to 4/4
        with preceding rest ») : écrite pleine, son silence DEVANT — sa barre tombe une mesure
        écrite avant la suivante ;
      • la dernière (« padded final 1/4 span … with trailing rest ») : son silence DERRIÈRE.
    Une mesure qui change de chiffrage en cours de morceau (`M:1/4`, `M:3/4` écrits) garde le sien."""
    rows = [(float(t), int(p), int(n), int(d)) for t, p, n, d, *_ in beats or ()]
    written = [float(w) for w in written or ()]
    if len(rows) < 2 or not written:
        return None
    downbeats = [t for t, p, _, _ in rows if p == 1]
    if len(downbeats) != len(written):
        return None
    gaps = sorted(b[0] - a[0] for a, b in zip(rows, rows[1:]))
    common = max(set(d for *_, d in rows), key=lambda d: sum(1 for *_, x in rows if x == d))
    quarter = gaps[(len(gaps) - 1) // 2] * common / 4.0          # la durée d'une noire jouée
    if quarter <= 0:
        return None
    lines = list(downbeats)
    if len(lines) > 1 and lines[1] - lines[0] < written[0] * quarter - quarter / 2:
        lines[0] = lines[1] - written[0] * quarter
    lines.append(lines[-1] + written[-1] * quarter)
    return lines


def written_measures(abc: str):
    """La longueur ÉCRITE (en noires) de chaque mesure d'une partition, lue sur sa PREMIÈRE voix :
    une barre `|` ferme une mesure, un silence `Z<n>` en compte n, une ligne `M:` ou un champ `[M:]`
    change le chiffrage des suivantes. None pour une partition sans mesure lisible."""
    text = str(abc or '')
    head, _, body = text.partition('\nK:')
    meter = re.search(r'(?m)^M:\s*(\d+)\s*/\s*(\d+)', head)
    if not meter or not body:
        return None
    length = int(meter.group(1)) * 4 / int(meter.group(2))
    lines = body.split('\n')[1:]
    first = next((re.match(r'V:\s*(\S+)', l).group(1) for l in lines if re.match(r'V:\s*\S', l)), None)
    voice, out = first, []
    for line in lines:
        found = re.match(r'V:\s*(\S+)', line)
        if found:
            voice = found.group(1)
            continue
        if voice != first:
            continue
        changed = re.match(r'M:\s*(\d+)\s*/\s*(\d+)', line)
        if changed:
            length = int(changed.group(1)) * 4 / int(changed.group(2))
            continue
        if not line.strip() or line.startswith('%') or re.match(r'[A-Za-z]:', line):
            continue
        for segment in line.split('|'):
            bar = re.sub(r'"[^"]*"|![^!]*!', '', segment).strip(' :][')
            inline = re.search(r'\[M:\s*(\d+)\s*/\s*(\d+)\]', segment)
            if inline:
                length = int(inline.group(1)) * 4 / int(inline.group(2))
            if not bar:
                continue
            rests = re.fullmatch(r'Z(\d*)', bar)
            out.extend([length] * (int(rests.group(1) or 1) if rests else 1))
    return out or None


def constant_tempo(abc: str):
    """`(valeur du temps en ronde, temps par minute)` d'une partition à tempo CONSTANT (un seul
    `Q:` d'en-tête, aucun changement dans le corps), ou None — une partition qui en change n'est
    pas datée par cette règle (ses changements de tempo se datent alors à la notation)."""
    text = str(abc or '')
    if re.search(r'\[Q:', text) or len(re.findall(r'(?m)^Q:', text)) != 1:
        return None
    tempo = re.search(r'(?m)^Q:\s*(?:(\d+)\s*/\s*(\d+)\s*=\s*)?(\d+(?:\.\d+)?)', text)
    if not tempo:
        return None
    unit = int(tempo.group(1)) / int(tempo.group(2)) if tempo.group(1) else 0.25
    return unit, float(tempo.group(3))


def sync_from_beats(abc: str, beats):
    """Les repères d'une partition à tempo constant écrite sur des temps DATÉS : chaque mesure à
    sa longueur écrite (`written_measures`), au tempo écrit, et à son instant d'audio
    (`bar_lines_from_beats`). None quand l'une des deux lectures manque ou qu'elles ne concordent pas."""
    tempo, written = constant_tempo(abc), written_measures(abc)
    lines = bar_lines_from_beats(beats, written) if tempo and written else None
    if not lines:
        return None
    unit, bpm = tempo
    quarter_ms = 0.25 / unit * 60000.0 / bpm
    pairs, ms = [], 0.0
    for length, t in zip(written + [0.0], lines):
        pairs.append((ms, t))
        ms += length * quarter_ms
    return pairs


def written_bar_ms(bar_quarters: float, tempi: list) -> list:
    """L'instant écrit (ms) de chaque barre, mesure 1 à 0 : `tempi[b]` est le tempo (noires par
    minute) de la mesure `b` — la règle de la gravure, une mesure jouée à son tempo écrit. Rend
    `len(tempi) + 1` instants (la dernière barre comprise)."""
    out, total = [0.0], 0.0
    for bpm in tempi:
        total += bar_quarters * 60000.0 / float(bpm)
        out.append(total)
    return out
