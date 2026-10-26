"""Surfaces du composer — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

`score` (2026-10-15, 3ᵉ surface du chantier SURFACES, consommateur pilote du transport commun —
`ROUTE §F3b`, « la page d'édition de YuE2 ») : voir la partition, l'écouter synchronisée au rendu
(les notes jouées se colorent), la corriger — à la gravure (glisser une note) ou dans sa source
ABC —, avec l'annuler/rétablir et les versions de WAMA. Toutes ses briques sont universelles.

La PARTITION COMPLÈTE (2026-10-16) : une partie par instrument (process optionnel `parts`,
MuScriptor), en lecture seule, sur le même axe. Depuis le 2026-10-22 (demande de Fabien : « une
seule UI […] afficher la partition complète dans une demi-fenêtre sera illisible ») elle se lit
dans LA MÊME vue que la partition réduite, sur toute la largeur — un choix « Partition » passe de
l'une à l'autre (`options.versions` de `score_view`) ; versions et actions vont au volet. Elle se
CORRIGE comme la réduite (même jour, demande de Fabien) : un champ édité de plus
(`Surface.also_edits`), ses versions gardées comme celles de la réduite (`apps.py`).

La partition est un RÉSULTAT de la card, écrit par l'un de deux process ALTERNATIFS : `plan`
(la consigne → la partition) ou `extract_score` (l'audio du morceau à reprendre → sa mélodie) —
la surface édite celui qui est rempli. L'enregistrer change l'empreinte de la sortie : le rendu
qui la suit passe périmé (`output_fingerprint`), « Appliquer » le rejoue.

L'ENTRÉE et la SORTIE (2026-10-26, décisions de Fabien) : la vue principale montre la partition
d'ENTRÉE — celle qu'on IMPORTE prime sur celle d'un cover (« elle doit être affichée à la place »),
puis l'extraite ou la planifiée ; sa partition complète décrit le MÊME audio d'entrée. La partition
du morceau PRODUIT (`rendered_parts`) se lit dans une SECONDE vue, pour juxtaposer l'entrée et la
sortie (« deux briques partition côte à côte ») ; la disposition se règle sur la page.
"""
from wama.common.surfaces import BrickSlot, Surface, register_surface
from wama.composer.models import ComposerGeneration

#: Les deux sorties « partition », dans l'ordre où la page les cherche (process alternatifs).
SCORE_FIELDS = ComposerGeneration.SCORE_FIELDS
#: La partition d'ENTRÉE que la page édite : l'IMPORTÉE d'abord (2026-10-26), puis les sorties.
INPUT_SCORE_FIELDS = ('reference_score',) + tuple(SCORE_FIELDS)


def _score_available(generation) -> tuple:
    """Une card sans partition l'aura-t-elle un jour ? Un modèle qui compose SANS partition
    (MusicGen…) n'en écrit jamais : on le dit, plutôt que « lancer d'abord la partition ». Sous
    « auto » le modèle n'est connu qu'au lancement : la règle commune nomme alors les process."""
    if any(getattr(getattr(generation, name, None), 'name', '') for name in INPUT_SCORE_FIELDS):
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
    slots=(BrickSlot('score', 'score_view', 0, 0, 12, 14, {
               'media': 'audio', 'title': "Partition d'entrée",
               # La réduite (mélodie et accords), puis la COMPLÈTE (une partie par instrument) —
               # toutes deux de l'ENTRÉE.
               'versions': [
                   {'label': 'Réduite'},
                   {'field': 'parts_score', 'label': 'Complète',
                    'empty': "Pas encore de partition complète : cocher « Partition complète "
                             "(instruments) » dans les réglages d'une card de reprise (cover), "
                             "puis relancer."}]}),
           BrickSlot('transport', 'media_transport', 0, 14, 12, 3, {'role': 'audio'}),
           # La SORTIE, lue seulement (2026-10-26) : à placer à côté de l'entrée pour comparer.
           BrickSlot('rendered', 'score_view', 0, 17, 12, 12, {
               'role': 'rendered', 'media': 'audio', 'title': 'Partition du rendu',
               'empty': "Pas encore de partition du rendu : cocher « Partition du rendu "
                        "(instruments) » dans les réglages de la card, puis relancer."}),
           BrickSlot('source', 'text_sections', 0, 29, 12, 6, {'title': 'Source ABC'}),
           BrickSlot('actions', 'surface_actions', 0, 0, 1, 5, zone='panel'),
           BrickSlot('versions', 'revision_history', 0, 5, 1, 6, zone='panel')),
    reads={'audio': 'audio_output', 'rendered': 'rendered_parts_score'},
    texts=('rendered',),
    edits=INPUT_SCORE_FIELDS,
    also_edits=('parts_score',),
    reruns='render', available=_score_available,
    # L'élément témoin des vignettes du catalogue des briques (nocturne) : une partition, sa
    # partition complète et un rendu audio — rien n'est lancé, les fichiers sont des témoins.
    witness={'prompt': "Témoin — la page d'édition de la partition", 'planned_score': '.abc',
             'parts_score': '.abc', 'rendered_parts_score': '.abc', 'audio_output': '.wav'}))
