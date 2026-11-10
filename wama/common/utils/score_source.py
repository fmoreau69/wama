"""
La SOURCE ABC d'une partition fournie en MIDI ou en MusicXML (2026-11-10, demande de Fabien).

La page d'édition d'une partition, ses versions et sa gravure travaillent sur du TEXTE ABC. Une
partition FOURNIE peut être un `.mid` ou un `.musicxml` : on en montre la VUE ABC, tirée par les
conversions communes (`midi_score.midi_to_abc`, `musicxml_score.musicxml_to_abc`). Le fichier
fourni n'est jamais réécrit ; une correction s'enregistre dans un `.abc` à côté de lui
(`surface_views._write_text`), que le rendu suit dès lors.

⚠ Une conversion lit tout le fichier : jamais depuis ce qui s'exécute par card d'une file
(`Surface.can_open`, que le bouton ✎ appelle), seulement à l'ouverture de la page.
"""
from __future__ import annotations

from pathlib import Path

_MIDI_SUFFIXES = ('.mid', '.midi')


def shown_as_abc(name) -> bool:
    """La partition `name` se montre-t-elle par sa VUE ABC ? Toute extension de partition
    (`SCORE_EXTENSIONS`, la déclaration unique) qui n'est pas déjà de l'ABC."""
    from wama.common.app_registry import SCORE_EXTENSIONS
    suffix = Path(str(name or '')).suffix.lower()
    return suffix in SCORE_EXTENSIONS and suffix != '.abc'


def abc_view(path, title: str = '') -> str:
    """Le texte ABC de la partition MIDI ou MusicXML `path`. `title` : le titre d'un fichier qui
    n'en écrit aucun (par défaut son nom). Lève `ValueError` en disant pourquoi : un fichier
    corrompu lève ici de tout (`OSError` de mido, `BadZipFile`, `ParseError`, xml2abc…), la page,
    elle, n'a qu'une chose à dire."""
    from wama.common.utils.midi_score import midi_to_abc
    from wama.common.utils.musicxml_score import musicxml_to_abc, read_musicxml, work_title
    path = Path(path)
    title = title or path.stem
    try:
        if path.suffix.lower() in _MIDI_SUFFIXES:
            return midi_to_abc(path.read_bytes(), title=title)
        text = read_musicxml(path)
        return musicxml_to_abc(text, title=work_title(text) or title)
    except Exception as error:
        raise ValueError(f"{path.name} : partition illisible ({error})") from error
