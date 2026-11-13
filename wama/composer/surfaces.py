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

Une partition importée en MIDI ou MusicXML (2026-11-10) s'y ouvre par sa vue ABC, le fichier
importé jamais réécrit (`common/utils/score_source.py`, règle de toutes les surfaces).
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
    # La partition COMPLÈTE compte aussi (2026-11-07) : une card qui ne demande qu'elle — rendu
    # coupé, partition complète d'un audio — a bien une partition à éditer.
    if model and not any(PIPELINE.takes_place(PIPELINE.spec(key), generation, model)
                         for key in ('plan', 'extract_score', 'parts')):
        # Un AUDIO repris dont les partitions ne sont simplement pas cochées (2026-11-13 : une card
        # PISTE, née d'une séparation, hérite les cases de sa source) : dire lesquelles cocher —
        # leurs libellés sont ceux des étapes déclarées —, pas que le modèle compose sans partition.
        possible = [spec for spec in map(PIPELINE.spec, ('extract_score', 'parts'))
                    if spec.applies(generation, model)]
        if possible:
            steps = ' ou '.join(f'« {spec.label} »' for spec in possible)
            return False, (f"Pas encore de partition : cocher {steps} dans les réglages de la card, "
                           "puis la lancer.")
        return False, ("Ce modèle compose sans partition : seuls les modèles qui écrivent ou suivent "
                       "une partition (YuE2) en ont une à éditer.")
    return True, ''


register_surface(Surface(
    app='composer', key='score', label='Éditer la partition',
    model='composer.ComposerGeneration',
    # « RÉFÉRENCE » / « JOUÉE » (2026-11-08, décision de Fabien) : la vue de gauche montre ce qui
    # était DEMANDÉ — la partition importée, tirée du morceau repris, ou composée par le modèle —,
    # celle de droite ce qui a été JOUÉ ; « d'entrée » / « de sortie » appelait « d'entrée » une
    # partition composée. Chacune pose sous ses notes les paroles horodatées de SON côté
    # (`lyrics` : un rôle lu, le JSON rangé par l'écoute), la règle commune `WamaScore.withLyrics`.
    slots=(BrickSlot('score', 'score_view', 0, 0, 12, 14, {
               'media': 'audio', 'title': 'Partition de référence', 'lyrics': 'lyrics_in',
               # La réduite (mélodie et accords), puis la COMPLÈTE (une partie par instrument) —
               # toutes deux de l'ENTRÉE.
               'versions': [
                   {'label': 'Réduite'},
                   {'field': 'parts_score', 'label': 'Complète',
                    'empty': "Pas encore de partition complète : cocher « Partition complète » "
                             "dans les réglages d'une card de reprise (cover), puis relancer."}]}),
           BrickSlot('transport', 'media_transport', 0, 14, 12, 3, {'role': 'audio'}),
           # Ce qui a été JOUÉ, lu seulement (2026-10-26) : à placer à côté de la référence. Réduite
           # et complète comme la référence (2026-11-08, décision de Fabien : la symétrie).
           BrickSlot('rendered', 'score_view', 0, 17, 12, 12, {
               'media': 'audio', 'title': 'Partition jouée', 'lyrics': 'lyrics_out',
               'versions': [
                   {'label': 'Réduite', 'role': 'rendered_score',
                    'empty': "Pas encore de partition réduite jouée : cocher « Partition réduite "
                             "jouée » (et « Paroles chantées » pour ses paroles) dans les réglages "
                             "de la card, puis relancer."},
                   {'label': 'Complète', 'role': 'rendered',
                    'empty': "Pas encore de partition complète jouée : cocher « Partition complète "
                             "jouée » dans les réglages de la card, puis relancer."}]}),
           BrickSlot('source', 'text_sections', 0, 29, 12, 6, {'title': 'Source ABC'}),
           BrickSlot('actions', 'surface_actions', 0, 0, 1, 5, zone='panel'),
           BrickSlot('versions', 'revision_history', 0, 5, 1, 6, zone='panel')),
    reads={'audio': 'audio_output', 'rendered': 'rendered_parts_score',
           'rendered_score': 'rendered_score',
           'lyrics_in': 'input_lyrics_timed', 'lyrics_out': 'rendered_lyrics_timed'},
    texts=('rendered', 'rendered_score', 'lyrics_in', 'lyrics_out'),
    edits=INPUT_SCORE_FIELDS,
    also_edits=('parts_score',),
    reruns='render', available=_score_available,
    # L'élément témoin des vignettes du catalogue des briques (nocturne) : une partition, sa
    # partition complète et un rendu audio — rien n'est lancé, les fichiers sont des témoins.
    witness={'prompt': "Témoin — la page d'édition de la partition", 'planned_score': '.abc',
             'parts_score': '.abc', 'rendered_parts_score': '.abc', 'rendered_score': '.abc',
             'audio_output': '.wav'}))
