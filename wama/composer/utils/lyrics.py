"""Des paroles ÉCOUTÉES → le champ « Paroles » d'une card (2026-11-03, décision de Fabien).

Ce que chantent des segments de transcription, sous la forme que lisent les moteurs et que
l'utilisateur corrige : des sections balisées (`[Verse]`, `[Chorus]`…). La doc de YuE2 le demande :
« align section tags and lyric order with the score » (`vendor/yue/docs/covers.md`). Les sections
viennent du moteur (`score_sections`), la lecture de la partition n'est pas écrite ici.
"""

import re

#: En deçà, ce n'est pas une chanson qu'on a entendue. Mesuré le 2026-11-03 sur 3 vrais morceaux :
#: Whisper invente en boucle (« Thank you for watching! » : 4 mots DISTINCTS sur 48, « Thank you so
#: much » : 4 sur 46), Qwen3-ASR rend les paroles (142 et 148 distincts). Un compte de mots n'y voit
#: rien : la boucle en fait autant que des paroles.
MIN_DISTINCT_WORDS = 8
#: Le même seuil pour une écriture sans espaces (le chinois, que YuE2 chante) : des signes distincts.
MIN_DISTINCT_SIGNS = 30

_SENTENCE_END = re.compile(r'(?<=[.!?…。！？])\s+')


def fit_to_duration(sections, duration) -> list:
    """Les temps de la partition, recalés sur la durée RÉELLE de l'audio : son tempo est une moyenne
    (mesuré sur 12 morceaux : 1 à 4 s d'écart à la fin). Inchangés sans durée connue."""
    sections = list(sections or ())
    end = sections[-1]['end'] if sections else 0
    if not end or not duration:
        return sections
    ratio = float(duration) / float(end)
    return [{**s, 'start': s['start'] * ratio, 'end': s['end'] * ratio} for s in sections]


def _section_at(sections, moment):
    for section in sections:
        if moment < section['end']:
            return section
    return sections[-1]


def _timed_lines(segment):
    """Les phrases d'un segment `(moment, ligne)`. Un moteur rend de longs passages sans le temps de
    ses mots (Qwen3-ASR : 7 à 10 segments par chanson) : le moment d'une phrase s'estime à sa place
    dans le texte, au prorata des signes. Une ESTIMATION, assez bonne pour choisir une section."""
    text = str(getattr(segment, 'text', '') or '').strip()
    start, end = float(segment.start), float(segment.end)
    done = 0
    for line in _SENTENCE_END.split(text):
        line = line.strip()
        if line:
            yield start + (end - start) * (done + len(line) / 2) / max(1, len(text)), line
        done += len(line) + 1


def enough_heard(text) -> bool:
    """A-t-on entendu des paroles, ou une transcription qui tourne en boucle sur de la musique ?"""
    words = set(str(text or '').lower().split())
    return len(words) >= MIN_DISTINCT_WORDS or len(set(str(text or ''))) >= MIN_DISTINCT_SIGNS


def lyrics_from_segments(segments, sections=()) -> str:
    """Le texte de `segments` (`.start`, `.end`, `.text`) sous ses balises de section : chaque phrase
    va à la section où elle tombe, une section où la VOIX de la partition se tait n'en reçoit aucune
    (ce qu'une transcription y « entend » est inventé). '' si l'on n'a pas entendu de quoi faire des
    paroles. Sans sections : un seul couplet, la forme de `vocals.as_lyrics`."""
    from .vocals import as_lyrics
    sections = list(sections or ())
    blocks = []                        # [nom, [lignes]]
    for segment in segments or ():
        for moment, line in _timed_lines(segment):
            name = 'Verse'
            if sections:
                section = _section_at(sections, moment)
                if not section.get('sings', True):
                    continue
                name = str(section['name']).title()
            if not blocks or blocks[-1][0] != name:
                blocks.append([name, []])
            blocks[-1][1].append(line)
    if not enough_heard(' '.join(line for _name, lines in blocks for line in lines)):
        return ''
    return as_lyrics('\n\n'.join(f"[{name}]\n" + '\n'.join(lines) for name, lines in blocks))
