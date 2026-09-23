"""
Lecture d'une transcription PRODUITE AILLEURS — SRT, VTT, ou document à tours de parole
(TXT, MD, DOCX, PDF ; exports Sonal compris).

Sert les deux ports du RÉSULTAT du transcriber (`app_registry.app_result_ports`) :
`reference_result` (la sortie lui est comparée) et `work_result` (il tient lieu de
transcription). Rendu : des segments à la forme de `segments_json`
(`speaker_id`, `start_time`, `end_time`, `text`), dont les temps valent `None` quand le
document n'en porte pas — c'est l'alignement forcé, plus tard, qui les placera.

LA RÈGLE DE LECTURE — ce qui est de la parole, et ce qui n'en est pas.
Un document de transcription mêle la parole et son habillage : titre, en-tête d'export,
métadonnées, thématiques, résumé, notes. Compter l'habillage comme de la parole fausserait
toute mesure (un WER contre un titre qu'on n'a jamais prononcé). D'où :
  • est de la parole ce qui suit un LABEL DE LOCUTEUR (`Speaker 1 :`, `SPEAKER_00:`,
    `[Nom]  0:12—0:40` des exports WAMA), jusqu'au label suivant ;
  • un SÉPARATEUR (`=====`, `*****`) ou un EN-TÊTE D'EXTRAIT Sonal clôt le tour en cours ;
  • ce qui n'est sous aucun label est HORS PAROLE : il est rendu (`outside_speech`), jamais
    compté ;
  • EXCEPTION — un document SANS AUCUN label est une transcription sans locuteurs : tout son
    texte est de la parole (sinon on perdrait tout).

⚠ Les labels reconnus sont VOLONTAIREMENT étroits : `Nom :` en général ne l'est pas. Un en-tête
Sonal porte « Caractéristiques : » et « Observations : », qu'un motif large prendrait pour des
locuteurs — et leur contenu compterait comme de la parole. Une convention de labels de plus
s'ajoute à `_SPEAKER_LABEL`, jamais par un motif « tout ce qui finit par deux-points ».

⚠ Un crochet seul (`[rires]`) n'est PAS un locuteur : c'est une annotation de verbatim. Le
label entre crochets n'est reconnu que suivi d'une plage de temps (la forme des exports WAMA).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from wama.transcriber.utils.speakers import normalize_speaker_label

#: Extensions lues. Les formats texte passent par l'extracteur de documents COMMUN.
TIMED_EXTENSIONS = ('.srt', '.vtt')
TEXT_EXTENSIONS = ('.txt', '.md', '.docx', '.pdf')
SUPPORTED_EXTENSIONS = TIMED_EXTENSIONS + TEXT_EXTENSIONS

_TIME = r'\d{1,2}(?::\d{2}){1,2}(?:[.,]\d{1,3})?'

_SEPARATOR = re.compile(r'^\s*([=*_~#-])\1{4,}\s*$')

# Sonal : « 1 - 00:00 > 10:56 [ Pas de thématique] » — un EXTRAIT, borné dans le temps.
_EXTRACT_HEADER = re.compile(
    rf'^\s*(\d+)\s*-\s*({_TIME})\s*>\s*({_TIME})\s*(?:\[\s*(.*?)\s*\])?\s*$')

# « Speaker 1 : texte », « SPEAKER_00: », « Locuteur 2 : », « Intervenant 3 : » — le texte peut
# suivre sur la même ligne ou sur les suivantes.
_SPEAKER_LABEL = re.compile(
    r'^\s*((?:speaker|locuteur|intervenant|spk)[\s_-]*\d+)\s*:\s*(.*)$', re.IGNORECASE)

# Exports WAMA (DOCX, TXT) : « [SPEAKER_00]  0:12—0:40 » — crochet SUIVI d'une plage de temps.
_BRACKET_LABEL = re.compile(
    rf'^\s*\[([^\]]{{1,60}})\]\s+({_TIME})\s*[—–-]\s*({_TIME})\s*(.*)$')

_CUE_TIMING = re.compile(rf'^\s*({_TIME})\s*-->\s*({_TIME})')
_VTT_VOICE = re.compile(r'^<v(?:\.[^\s>]*)?\s+([^>]+)>(.*?)(?:</v>)?$')
_SRT_SPEAKER_PREFIX = re.compile(r'^\[([^\]]{1,60})\]\s*(.*)$')
_MARKUP = re.compile(r'<[^>]+>')


@dataclass
class TranscriptDocument:
    """Une transcription lue : sa parole (segments), et ce qui n'en est pas."""

    format: str                                     # 'srt' | 'vtt' | 'text'
    segments: List[dict] = field(default_factory=list)
    #: Extraits Sonal : bornes GROSSIÈRES d'une portion d'audio, pas des temps de segments.
    windows: List[dict] = field(default_factory=list)
    #: Lignes hors parole (titre, en-tête, titres d'extraits) — rendues, jamais comptées.
    outside_speech: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """La parole seule, en un texte — ce que compare une métrique."""
        return ' '.join(s['text'] for s in self.segments if s['text']).strip()

    @property
    def is_timed(self) -> bool:
        """Chaque segment porte ses temps (SRT/VTT) — sinon il faudra les aligner."""
        return bool(self.segments) and all(s['start_time'] is not None for s in self.segments)


def parse_timecode(value: str) -> Optional[float]:
    """« 01:02:03,500 », « 02:03.5 », « 10:56 » → secondes. None si illisible."""
    parts = (value or '').strip().replace(',', '.').split(':')
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return None
    if not 2 <= len(numbers) <= 3:
        return None
    seconds = 0.0
    for n in numbers:
        seconds = seconds * 60 + n
    return seconds


def read_transcript_document(path: str) -> TranscriptDocument:
    """Lit une transcription externe. Lève ValueError sur une extension non prise en charge."""
    ext = os.path.splitext(path)[1].lower()
    if ext in TIMED_EXTENSIONS:
        return parse_cues(_read_text_file(path), 'vtt' if ext == '.vtt' else 'srt')
    if ext in TEXT_EXTENSIONS:
        # L'extracteur de documents COMMUN (txt/md/pdf/docx), celui que lit déjà
        # `reference_comprehension` pour les documents de référence — jamais un 4ᵉ.
        from wama.common.utils.batch_parsers import extract_batch_file_text
        return parse_speaker_turns(extract_batch_file_text(path))
    raise ValueError(f"Format de transcription non pris en charge : {ext or '(sans extension)'}")


def _read_text_file(path: str) -> str:
    with open(path, 'rb') as handle:
        raw = handle.read()
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _segment(speaker, text, start=None, end=None, window=None) -> dict:
    seg = {'speaker_id': normalize_speaker_label(speaker), 'start_time': start,
           'end_time': end, 'text': ' '.join((text or '').split())}
    if window is not None:
        seg['window'] = window
    return seg


def parse_cues(content: str, fmt: str) -> TranscriptDocument:
    """SRT / VTT : un bloc par réplique, temps exacts. Locuteur : `[Nom] ` (export SRT de WAMA)
    ou balise de voix VTT `<v Nom>`."""
    doc = TranscriptDocument(format=fmt)
    for block in re.split(r'\n\s*\n', content.replace('\r\n', '\n').replace('\r', '\n')):
        lines = [l for l in block.split('\n') if l.strip()]
        timing_at = next((i for i, l in enumerate(lines) if _CUE_TIMING.match(l)), None)
        if timing_at is None:
            continue                                    # en-tête WEBVTT, NOTE, STYLE…
        match = _CUE_TIMING.match(lines[timing_at])
        body = ' '.join(lines[timing_at + 1:]).strip()
        speaker = ''
        voice = _VTT_VOICE.match(body)
        prefix = _SRT_SPEAKER_PREFIX.match(body)
        if voice:
            speaker, body = voice.group(1), voice.group(2)
        elif prefix:
            speaker, body = prefix.group(1), prefix.group(2)
        body = _MARKUP.sub('', body).strip()
        if body:
            doc.segments.append(_segment(speaker, body, parse_timecode(match.group(1)),
                                         parse_timecode(match.group(2))))
    return doc


def parse_speaker_turns(content: str) -> TranscriptDocument:
    """Document à tours de parole (TXT/MD/DOCX/PDF, exports Sonal compris) — règle en tête."""
    doc = TranscriptDocument(format='text')
    lines = content.replace('﻿', '').replace('\r\n', '\n').replace('\r', '\n').split('\n')

    has_labels = any(_SPEAKER_LABEL.match(l) or _BRACKET_LABEL.match(l) for l in lines)
    if not has_labels:
        text = ' '.join(l.strip() for l in lines if l.strip() and not _SEPARATOR.match(l))
        if text:
            doc.segments.append(_segment('', text))
        return doc

    turn = None                                         # {'speaker', 'lines', 'start', 'end'}
    window = None

    def close_turn():
        nonlocal turn
        if turn and ' '.join(turn['lines']).strip():
            doc.segments.append(_segment(turn['speaker'], ' '.join(turn['lines']),
                                         turn['start'], turn['end'], window))
        turn = None

    for line in lines:
        if not line.strip():
            continue
        if _SEPARATOR.match(line):
            close_turn()
            continue
        extract = _EXTRACT_HEADER.match(line)
        if extract:
            close_turn()
            doc.windows.append({'index': int(extract.group(1)),
                                'start': parse_timecode(extract.group(2)),
                                'end': parse_timecode(extract.group(3)),
                                'label': extract.group(4) or ''})
            window = len(doc.windows) - 1
            continue
        label = _SPEAKER_LABEL.match(line)
        if label:
            close_turn()
            turn = {'speaker': label.group(1), 'lines': [label.group(2)],
                    'start': None, 'end': None}
            continue
        bracket = _BRACKET_LABEL.match(line)
        if bracket:
            close_turn()
            turn = {'speaker': bracket.group(1), 'lines': [bracket.group(4)],
                    'start': parse_timecode(bracket.group(2)),
                    'end': parse_timecode(bracket.group(3))}
            continue
        if turn is not None:
            turn['lines'].append(line.strip())
        else:
            doc.outside_speech.append(line.strip())
    close_turn()
    return doc
