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
"""
from __future__ import annotations

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


def musicxml_to_abc(text: str, title: str = '') -> str:
    """L'ABC de la partition MusicXML `text` (`xml2abc`) ; `title` remplace le titre écrit (sinon
    celui du document, « Title » quand le moteur n'en a lu aucun). Lève si rien n'est converti."""
    # `vertaal`, la conversion elle-même — pas `convert_xml2abc`, l'emballage du paquet, qui relit
    # les ARGUMENTS DU PROCESSUS (`optparse` sur `sys.argv`) : mesuré le 2026-11-07, il lève
    # « no such option: --keepdb » sous `manage.py test`, et lirait de même ceux d'un worker.
    from abc_xml_converter.xml2abc import vertaal
    abc, diagnostics = vertaal(text)
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
