"""Surfaces du composer — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

`score` (2026-10-15, 3ᵉ surface du chantier SURFACES, consommateur pilote du transport commun —
`ROUTE §F3b`, « la page d'édition de YuE2 ») : voir la partition, l'écouter synchronisée au rendu
(les notes jouées se colorent), la corriger — à la gravure (glisser une note) ou dans sa source
ABC —, avec l'annuler/rétablir et les versions de WAMA. Toutes ses briques sont universelles.

La partition est un RÉSULTAT de la card, écrit par l'un de deux process ALTERNATIFS : `plan`
(la consigne → la partition) ou `extract_score` (l'audio du morceau à reprendre → sa mélodie) —
la surface édite celui qui est rempli. L'enregistrer change l'empreinte de la sortie : le rendu
qui la suit passe périmé (`output_fingerprint`), « Appliquer » le rejoue.
"""
from wama.common.surfaces import BrickSlot, Surface, register_surface
from wama.composer.models import ComposerGeneration

#: Les deux sorties « partition », dans l'ordre où la page les cherche (process alternatifs).
SCORE_FIELDS = ComposerGeneration.SCORE_FIELDS


def _score_available(generation) -> tuple:
    """Une card sans partition l'aura-t-elle un jour ? Un modèle qui compose SANS partition
    (MusicGen…) n'en écrit jamais : on le dit, plutôt que « lancer d'abord la partition ». Sous
    « auto » le modèle n'est connu qu'au lancement : la règle commune nomme alors les process."""
    if any(getattr(getattr(generation, name, None), 'name', '') for name in SCORE_FIELDS):
        return True, ''
    from wama.composer.function_specs import PIPELINE
    model = PIPELINE.requested_model(generation)
    if model and not any(PIPELINE.takes_place(PIPELINE.spec(key), generation, model)
                         for key in ('plan', 'extract_score')):
        return False, ("Ce modèle compose sans partition : seuls les modèles qui écrivent ou suivent "
                       "une partition (YuE2) en ont une à éditer.")
    return True, ''


register_surface(Surface(
    app='composer', key='score', label='Éditer la partition',
    model='composer.ComposerGeneration',
    slots=(BrickSlot('score', 'score_view', 0, 0, 8, 12, {'media': 'audio'}),
           BrickSlot('transport', 'media_transport', 0, 12, 8, 4, {'role': 'audio'}),
           BrickSlot('source', 'text_sections', 8, 0, 4, 8, {'title': 'Source ABC'}),
           BrickSlot('versions', 'revision_history', 8, 8, 4, 4),
           BrickSlot('actions', 'surface_actions', 8, 12, 4, 4)),
    reads={'audio': 'audio_output'},
    edits=SCORE_FIELDS,
    reruns='render', available=_score_available))
