"""Surfaces du reader — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

Une page d'édition PAR NATURE de ce que la card a lu (2026-11-08, demande de Fabien : « la page
d'édition texte / partition / autre à venir », universelle) — une surface ne mêle pas des natures
(`Surface.text_value`) ; chacune s'ouvre selon ce que la card a produit (`available`).

`score` — la PARTITION lue d'une page imprimée (process `read_score`) : gravée, corrigée à la
gravure ou dans sa source ABC, ses versions gardées — les briques universelles de la page de la
partition du composer (`composer/surfaces.py`), sans l'audio : une page lue n'a pas de son.

`text` — le TEXTE lu (process `read`, mis en forme par `format`) : corrigé section par section
(`text_sections`). L'analyse qui le lit passe périmée (`analyze` surveille `result_text`) ;
« Appliquer » la rejoue.
"""
from wama.common.surfaces import BrickSlot, Surface, register_surface, validate_text


def _score_available(item) -> tuple:
    if getattr(getattr(item, 'score_file', None), 'name', ''):
        return True, ''
    if not item.read_as_score:
        return False, ("Cette lecture n'est pas une partition : cocher « Lire une partition » dans "
                       "ses réglages, puis relancer.")
    return True, ''


def _text_available(item) -> tuple:
    if getattr(getattr(item, 'score_file', None), 'name', '') or item.read_as_score:
        return False, "Cette lecture est une partition : elle se corrige dans « Éditer la partition »."
    if not (item.result_text or '').strip():
        return False, "Rien à corriger : lancer d'abord la lecture."
    return True, ''


register_surface(Surface(
    app='reader', key='score', label='Éditer la partition',
    model='reader.ReadingItem',
    slots=(BrickSlot('score', 'score_view', 0, 0, 12, 14, {'title': 'Partition lue'}),
           BrickSlot('source', 'text_sections', 0, 14, 12, 6, {'title': 'Source ABC'}),
           BrickSlot('actions', 'surface_actions', 0, 0, 1, 5, zone='panel'),
           BrickSlot('versions', 'revision_history', 0, 5, 1, 6, zone='panel')),
    reads={},
    edits='score_file',
    available=_score_available,
    # L'élément témoin des vignettes du catalogue des briques (nocturne) : une partition lue.
    witness={'score_file': '.abc', 'read_as_score': True, 'status': 'SUCCESS'}))

register_surface(Surface(
    app='reader', key='text', label='Corriger le texte',
    model='reader.ReadingItem',
    slots=(BrickSlot('text', 'text_sections', 0, 0, 12, 20, {'title': 'Texte lu'}),
           BrickSlot('actions', 'surface_actions', 0, 0, 1, 5, zone='panel')),
    reads={},
    edits='result_text', validate=validate_text,
    reruns='analyze',
    available=_text_available,
    witness={'result_text': '# Témoin\n\nLe texte lu, une section.', 'status': 'SUCCESS'}))
