"""
Partitions MUSICXML — la brique commune de WAMA (2026-11-06).

Commune à tout moteur de la tâche `image-to-score` (`ScoreReadingBackend`) : le moteur rend une
page ; ce qui en fait UNE partition, et demain son ABC (la notation que la page d'édition et le
composer lisent), vit ici — patron de `midi_score`, la notation de la tâche `audio-to-midi`.
Aucun moteur n'y est nommé.

`merge_pages` : un moteur de lecture lit PAGE par page (copisteria rend un document par page) ;
une partition de plusieurs pages en est la suite, partie par partie.

`musicxml_to_abc` : l'ABC d'une partition MusicXML, par `xml2abc` (W. G. Vree, LGPL, version 147,
emballé par la librairie `abc-xml-converter`, installée par la route — `manifests/libraries/
abc-xml-converter.json`). Il n'existait AUCUNE conversion MusicXML → ABC dans WAMA (mesuré le
2026-11-06) : la partition lue d'une page, et le MusicXML qu'on importe au composer (que YuE2
refusait en le disant), passent désormais par ici. `read_musicxml` lit un fichier, `.mxl` (compressé)
compris.

`apply_repeat_counts` (2026-11-08, demande de Fabien sur des partitions de batterie) : « x3 » écrit
au-dessus d'une mesure veut dire « jouée trois fois d'affilée » — l'auteur évite de la réécrire.
Le moteur ne lit pas ces deux caractères comme une reprise ; l'OCR de la page les lit
(`repeat_count`), le moteur les place comme des MOTS sur la note voisine (`repeat_words`), et la
partition reçoit ici une reprise que MusicXML sait compter (`<repeat times="3"/>`), le « ×3 »
restant écrit. ⚠ L'ABC (`xml2abc`) garde la reprise (`|: … :|`) et le « ×3 », pas le nombre de
passages : un lecteur ABC la joue deux fois.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

#: L'en-tête d'un document MusicXML 4.0 « partwise » — celui qu'écrivent les moteurs lus.
HEADER = ('<?xml version="1.0" encoding="UTF-8"?>\n'
          '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
          '"http://www.musicxml.org/dtds/partwise.dtd">\n')


def _root(text: str) -> ET.Element:
    root = ET.fromstring(text.encode('utf-8') if isinstance(text, str) else text)
    if root.tag != 'score-partwise':
        raise ValueError(f"MusicXML « {root.tag} » : seule la forme « score-partwise » est lue")
    return root


def read_musicxml(path) -> str:
    """Le TEXTE MusicXML d'un fichier `.musicxml` / `.xml`, ou d'un `.mxl` — l'archive compressée
    du format, dont `META-INF/container.xml` désigne la partition (son premier `rootfile`)."""
    path = Path(path)
    if path.suffix.lower() != '.mxl':
        return path.read_text(encoding='utf-8', errors='replace')
    with zipfile.ZipFile(path) as archive:
        container = ET.fromstring(archive.read('META-INF/container.xml'))
        rootfile = next((el.get('full-path') for el in container.iter() if el.tag.endswith('rootfile')
                         and el.get('full-path')), None)
        if not rootfile:
            raise ValueError(f"{path.name} : l'archive MusicXML ne désigne aucune partition")
        return archive.read(rootfile).decode('utf-8', errors='replace')


def _without_staffless_clefs(text: str) -> str:
    """`text` sans les CLÉS posées sur une portée où sa partie n'écrit aucune note. `xml2abc` range
    une clé dans les voix de sa portée et LÈVE quand la portée n'en a pas (`stfMap[n]`, KeyError) —
    mesuré le 2026-11-08 sur une page de batterie manuscrite lue par copisteria : une partie à
    clé de percussion dont la portée 1 restait vide, toute la partition perdue pour une clé. Une
    clé sans note à qui s'appliquer ne change rien à ce qui se joue. Un document sans tel cas est
    rendu tel quel."""
    try:
        root = _root(text)
    except (ET.ParseError, ValueError):
        return text
    removed = False
    for part in root.findall('part'):
        # Les notes que `xml2abc` compte : celles posées directement dans une mesure.
        staves = {(note.findtext('staff') or '1').strip() for note in part.findall('measure/note')}
        for index, measure in enumerate(part.findall('measure')):
            # La clé de la PREMIÈRE mesure va à l'en-tête de la voix, sans lecture des portées.
            if not index:
                continue
            for attributes in measure.findall('attributes'):
                for clef in list(attributes.findall('clef')):
                    if (clef.get('number') or '1') in staves:
                        continue
                    attributes.remove(clef)
                    removed = True
    return HEADER + ET.tostring(root, encoding='unicode') if removed else text


def musicxml_to_abc(text: str, title: str = '') -> str:
    """L'ABC de la partition MusicXML `text` (`xml2abc`) ; `title` remplace le titre écrit (sinon
    celui du document, « Title » quand le moteur n'en a lu aucun). Lève si rien n'est converti."""
    # `vertaal`, la conversion elle-même — pas `convert_xml2abc`, l'emballage du paquet, qui relit
    # les ARGUMENTS DU PROCESSUS (`optparse` sur `sys.argv`) : mesuré le 2026-11-07, il lève
    # « no such option: --keepdb » sous `manage.py test`, et lirait de même ceux d'un worker.
    from abc_xml_converter.xml2abc import vertaal
    abc, diagnostics = vertaal(_without_staffless_clefs(text))
    abc = (abc or '').strip()
    if 'K:' not in abc:
        raise ValueError(f"MusicXML non convertible en ABC ({(diagnostics or '').strip() or 'xml2abc n’a rien écrit'})")
    if title:
        lines = abc.splitlines()
        first = next((i for i, line in enumerate(lines) if line.startswith('T:')), None)
        if first is None:
            lines.insert(1, f'T:{title}')
        else:
            lines[first] = f'T:{title}'
        abc = '\n'.join(lines)
    return abc + '\n'


def note_count(text: str) -> int:
    """Le nombre de NOTES (silences exclus) d'un document MusicXML."""
    return sum(1 for note in _root(text).iter('note') if note.find('rest') is None)


def work_title(text: str) -> str:
    """Le titre écrit dans un document MusicXML (`work/work-title`, sinon `movement-title`), ou ''."""
    root = _root(text)
    return ' '.join((root.findtext('work/work-title') or root.findtext('movement-title') or '').split())


# ── « x3 » : une mesure jouée plusieurs fois ─────────────────────────────────────────────────

#: Le nombre de passages admis : « x1 » ne répète rien, au-delà de 16 c'est une autre lecture.
REPEAT_TIMES = (2, 16)
#: Ce que l'OCR lit à la place d'un chiffre manuscrit, mesuré le 2026-11-08 (docTR sur un « x2 »
#: écrit à la main : « XZ »). Un seul caractère, jamais une suite.
_LOOKALIKE_DIGITS = {'Z': '2', 'z': '2', 'S': '5', 's': '5', 'I': '1', 'l': '1', '|': '1',
                     'O': '0', 'o': '0', 'B': '8', 'G': '6', 'q': '9'}
_REPEAT_FORMS = (re.compile(r'^[xX×]\s*(\d{1,2}|[ZzSsIl|OoBGq])$'),
                 re.compile(r'^(\d{1,2})\s*[xX×]$'))
#: Les MOTS par lesquels le compte passe dans le moteur, jusqu'à la mesure qu'il désigne — un mot
#: que le moteur range comme indication écrite (assez de lettres), et que la partition lue rend en
#: reprise. Un « repeat 3 » imprimé dit la même chose : il est lu pareil.
REPEAT_WORDS = 'repeat {times}'
_REPEAT_WORDS = re.compile(r'^repeat\s+(\d{1,2})$', re.I)


def repeat_count(text: str):
    """Le nombre de passages que dit un texte de page — « x3 », « ×2 », « 4x », « XZ » (un « x2 »
    manuscrit lu par l'OCR) —, ou None."""
    text = ''.join(str(text or '').split())
    for form in _REPEAT_FORMS:
        match = form.match(text)
        if match:
            digits = match.group(1)
            times = int(_LOOKALIKE_DIGITS.get(digits, digits)) if digits else 0
            return times if REPEAT_TIMES[0] <= times <= REPEAT_TIMES[1] else None
    return None


def repeat_words(times: int) -> str:
    """Les mots qui portent `times` passages jusqu'à la partition lue (`REPEAT_WORDS`)."""
    return REPEAT_WORDS.format(times=times)


def _barline(measure, location: str):
    for barline in measure.findall('barline'):
        if (barline.get('location') or 'right') == location:
            return barline
    barline = ET.Element('barline', {'location': location})
    if location == 'left':
        position = next((i for i, child in enumerate(measure) if child.tag not in ('print', 'attributes')),
                        len(measure))
        measure.insert(position, barline)
    else:
        measure.append(barline)
    return barline


def _set_repeat(measure, location: str, direction: str, times=None) -> None:
    barline = _barline(measure, location)
    style = barline.find('bar-style')
    if style is None:
        style = ET.Element('bar-style')
        barline.insert(0, style)
    style.text = 'heavy-light' if location == 'left' else 'light-heavy'
    repeat = barline.find('repeat')
    if repeat is None:
        repeat = ET.SubElement(barline, 'repeat')
    repeat.set('direction', direction)
    if times:
        repeat.set('times', str(times))


def _repeat_marks(measure) -> list:
    """Les `(direction, mots, passages)` des comptes de passages écrits dans `measure`."""
    out = []
    for direction in measure.findall('direction'):
        for words in direction.iter('words'):
            match = _REPEAT_WORDS.match(' '.join((words.text or '').split()))
            if match:
                out.append((direction, words, int(match.group(1))))
    return out


def apply_repeat_counts(text: str) -> str:
    """La partition MusicXML `text` où chaque compte de passages écrit (`REPEAT_WORDS`) devient une
    REPRISE : la mesure qui le porte — ou, si une reprise ouvrante la précède sans être refermée,
    tout ce qui va d'elle à cette mesure — se joue `times` fois (`<repeat direction="backward"
    times="…"/>`). Les mots deviennent « ×3 », ce que la page montrait. Les parties reçoivent la
    même reprise aux mêmes mesures. Un document sans compte est rendu tel quel."""
    root = _root(text)
    parts = root.findall('part')
    counted = {}                                  # index de mesure → passages
    for part in parts:
        for index, measure in enumerate(part.findall('measure')):
            for direction, words, times in _repeat_marks(measure):
                counted[index] = times
                words.text = f'×{times}'
    if not counted:
        return text
    for part in parts:
        measures = part.findall('measure')
        opened = None
        for index, measure in enumerate(measures):
            if any(r.get('direction') == 'forward' for r in measure.iter('repeat')):
                opened = index
            times = counted.get(index)
            if times:
                # Une mesure VIDE de cette partie (une portée que le système masque) ne reçoit rien :
                # `xml2abc` lève sur une barre de reprise sans aucune voix (mesuré le 2026-11-08).
                start = opened if opened is not None else index
                if all(m.find('note') is not None or m.find('forward') is not None
                       for m in (measures[start], measure)):
                    _set_repeat(measures[start], 'left', 'forward')
                    _set_repeat(measure, 'right', 'backward', times)
                opened = None
            elif any(r.get('direction') == 'backward' for r in measure.iter('repeat')):
                opened = None
    return HEADER + ET.tostring(root, encoding='unicode')


# ── La légende d'une partition de batterie ───────────────────────────────────────────────────

_STEPS = 'CDEFGAB'
#: La place 0 d'une portée (`score_page.drum_key`, demi-interlignes) : la ligne du milieu, si4 —
#: l'écriture de la portée de percussion comme d'une clé de sol, celle des moteurs lus.
_MIDDLE_LINE = 4 * 7 + _STEPS.index('B')
#: Ce qui suit une tête dans une note MusicXML (sa place de `<notehead>`), et ce qui précède la
#: place de `<instrument>`.
_AFTER_NOTEHEAD = ('notehead-text', 'staff', 'beam', 'notations', 'lyric', 'play', 'listen')
_BEFORE_INSTRUMENT = ('duration', 'tie')
#: Ce qu'une `score-part` écrit après ses `score-instrument`.
_AFTER_SCORE_INSTRUMENT = ('player', 'midi-device', 'midi-instrument')


def unpitched_position(step: str, octave) -> int:
    """La place d'une note sans hauteur sur la portée (demi-interlignes, 0 = ligne du milieu)."""
    return int(octave) * 7 + _STEPS.index(step) - _MIDDLE_LINE


def drop_leading_measures(text: str, count: int) -> str:
    """La partition `text` sans ses `count` premières mesures — une LÉGENDE lue comme de la musique
    (2026-11-09 : la « Drum Key » d'une page de batterie devenait la mesure 1, en clé de sol). Les
    attributs qu'elles portent (divisions, mesure, clé) passent à la première mesure gardée qui ne
    les écrit pas ; les mesures sont renumérotées. `count` ≤ 0 rend `text` tel quel."""
    if count <= 0:
        return text
    root = _root(text)
    for part in root.findall('part'):
        measures = part.findall('measure')
        if len(measures) <= count:
            continue
        kept = measures[count]
        carried = {}
        for measure in measures[:count]:
            for attributes in measure.findall('attributes'):
                for child in attributes:
                    carried[child.tag] = child
            part.remove(measure)
        if carried:
            target = kept.find('attributes')
            if target is None:
                target = ET.Element('attributes')
                kept.insert(next((i for i, c in enumerate(kept) if c.tag != 'print'), len(kept)), target)
            own = {child.tag for child in target}
            for tag, child in carried.items():
                if tag not in own:
                    target.insert(0 if tag == 'divisions' else len(target), child)
        for number, measure in enumerate(part.findall('measure'), start=1):
            measure.set('number', str(number))
    return HEADER + ET.tostring(root, encoding='unicode')


def _insert_before(parent, element, tags) -> None:
    position = next((i for i, child in enumerate(parent) if child.tag in tags), len(parent))
    parent.insert(position, element)


def apply_drum_key(text: str, entries: list) -> str:
    """La partition `text` dont les notes sans hauteur portent l'instrument que leur donne la
    légende de la page (`entries` : `{'pos', 'name', 'sound'}`, `score_page.drum_key`) : chaque
    partie de batterie déclare ses instruments (`score-instrument`, `midi-instrument` au canal 10,
    `midi-unpitched` = son General MIDI + 1), chaque note le sien (`<instrument id>`), et une
    cymbale ou un charleston sa tête en croix. `xml2abc` en tire la table de percussion de l'ABC
    (`I:percmap`, `%%MIDI drummap`). Une note à une place que la légende ne nomme pas reste telle
    quelle. Sans entrée, `text` est rendu tel quel."""
    from wama.common.utils.midi_score import CROSS_SOUNDS
    by_pos = {entry['pos']: entry for entry in entries or ()}
    if not by_pos:
        return text
    root = _root(text)
    declared = {sp.get('id'): sp for sp in root.findall('part-list/score-part')}
    changed = False
    taken = {el.get('id') for el in root.iter('score-instrument')}
    for part in root.findall('part'):
        ids = {}
        for note in part.iter('note'):
            unpitched = note.find('unpitched')
            if unpitched is None:
                continue
            step, octave = unpitched.findtext('display-step'), unpitched.findtext('display-octave')
            if not step or not octave:
                continue
            entry = by_pos.get(unpitched_position(step, octave))
            if entry is None:
                continue
            if entry['pos'] not in ids:
                ident = next(f"{part.get('id')}-I{n}" for n in range(len(ids) + 1, len(ids) + len(taken) + 2)
                             if f"{part.get('id')}-I{n}" not in taken)
                ids[entry['pos']] = ident
                taken.add(ident)
            ident = ids[entry['pos']]
            if note.find('instrument') is None:
                before = [i for i, child in enumerate(note) if child.tag in _BEFORE_INSTRUMENT]
                note.insert(before[-1] + 1 if before else list(note).index(unpitched) + 1,
                            ET.Element('instrument', {'id': ident}))
            if entry.get('sound') in CROSS_SOUNDS and note.find('notehead') is None:
                head = ET.Element('notehead')
                head.text = 'x'
                _insert_before(note, head, _AFTER_NOTEHEAD)
            changed = True
        score_part = declared.get(part.get('id'))
        if not ids or score_part is None:
            continue
        for pos, ident in ids.items():
            entry = by_pos[pos]
            instrument = ET.Element('score-instrument', {'id': ident})
            ET.SubElement(instrument, 'instrument-name').text = entry['name']
            _insert_before(score_part, instrument, _AFTER_SCORE_INSTRUMENT)
            midi = ET.SubElement(score_part, 'midi-instrument', {'id': ident})
            ET.SubElement(midi, 'midi-channel').text = '10'
            if entry.get('sound'):
                ET.SubElement(midi, 'midi-unpitched').text = str(int(entry['sound']) + 1)
    return HEADER + ET.tostring(root, encoding='unicode') if changed else text


def drum_instruments(text: str) -> list:
    """Les noms des instruments que déclarent les parties d'une partition (`score-instrument`)."""
    return [name for name in (' '.join((el.text or '').split())
                              for el in _root(text).iter('instrument-name')) if name]


def merge_pages(pages: list) -> str:
    """UNE partition MusicXML faite de `pages` (textes MusicXML « partwise », dans l'ordre) : la
    i-ème partie de chaque page prolonge la i-ème partie de la première, ses mesures renumérotées
    à la suite ; une page qui porte plus de parties ajoute les siennes (déclarées dans la liste
    des parties). Chaque page nouvelle commence par un saut de page (`<print new-page="yes"/>`).
    Une seule page est rendue telle quelle."""
    pages = [p for p in pages if p and p.strip()]
    if not pages:
        raise ValueError("aucune page de partition à assembler")
    if len(pages) == 1:
        return pages[0]
    base = _root(pages[0])
    part_list = base.find('part-list')
    parts = base.findall('part')
    numbers = [len(part.findall('measure')) for part in parts]
    for text in pages[1:]:
        page = _root(text)
        declared = {sp.get('id'): sp for sp in page.find('part-list').findall('score-part')}
        for index, part in enumerate(page.findall('part')):
            if index >= len(parts):
                new_id = f"P{len(parts) + 1}"
                score_part = declared.get(part.get('id'))
                if score_part is not None:
                    score_part.set('id', new_id)
                    part_list.append(score_part)
                target = ET.SubElement(base, 'part', id=new_id)
                parts.append(target)
                numbers.append(0)
            target = parts[index]
            for position, measure in enumerate(part.findall('measure')):
                numbers[index] += 1
                measure.set('number', str(numbers[index]))
                if position == 0:
                    measure.insert(0, ET.Element('print', {'new-page': 'yes'}))
                target.append(measure)
    return HEADER + ET.tostring(base, encoding='unicode')
