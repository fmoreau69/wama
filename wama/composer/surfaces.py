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

DEUX VUES « PARTITION », UNE LISTE (2026-11-19, décision de Fabien du 18/11 : « une brique partition
générique […] choisir l'origine », deux gardées pour comparer) : chaque vue choisit son ORIGINE
(Partition de travail, Audio source, Audio généré) puis sa FORME (réduite, complète) dans la même
liste (`SCORE_VERSIONS`) ; la première ouvre sur ce que la page édite, la seconde sur l'audio généré.

Une partition importée en MIDI ou MusicXML (2026-11-10) s'y ouvre par sa vue ABC, le fichier
importé jamais réécrit (`common/utils/score_source.py`, règle de toutes les surfaces).

Le MIXAGE en temps réel (2026-11-17, décision de Fabien : « le mixage temps réel va dans la page
d'édition, la card porte les process ») : une card à pistes séparées règle le niveau de chacune
à l'oreille (brique commune `stem_mixer`, au volet), sur l'audio lu ; les niveaux sont les réglages
de la refusion, que « Rendre le mixage » lance. Une card qui n'a que ses pistes ouvre la page
(`opens_with`) : on y mixe avant d'avoir une partition. Depuis le 2026-11-19, le même mixeur vit
aussi dans l'onglet « Pistes séparées » de l'aperçu (`BrickSlot.face`).
"""
from wama.common.surfaces import INPUT_SOURCE, BrickSlot, Surface, register_surface
from wama.composer.models import ComposerGeneration

#: Les deux sorties « partition », dans l'ordre où la page les cherche (process alternatifs).
SCORE_FIELDS = ComposerGeneration.SCORE_FIELDS
#: La partition d'ENTRÉE que la page édite : l'IMPORTÉE d'abord (2026-10-26), puis les sorties.
INPUT_SCORE_FIELDS = ('reference_score',) + tuple(SCORE_FIELDS)
#: Les autres partitions que la page CORRIGE (`Surface.also_edits`) : la complète de l'entrée.
ALSO_EDITED = ('parts_score',)


def _score_available(generation) -> tuple:
    """Une card sans partition l'aura-t-elle un jour ? Un modèle qui compose SANS partition
    (MusicGen…) n'en écrit jamais : on le dit, plutôt que « lancer d'abord la partition ». Sous
    « auto » le modèle n'est connu qu'au lancement : la règle commune nomme alors les process.
    Une partition COMPLÈTE déjà écrite ouvre la page (2026-11-13 : une piste séparée qui n'a qu'elle)."""
    if any(getattr(getattr(generation, name, None), 'name', '')
           for name in INPUT_SCORE_FIELDS + ALSO_EDITED):
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


#: TOUTES les partitions qu'une card peut porter, rangées par ORIGINE et par FORME (2026-11-19,
#: décision de Fabien du 18/11 : « une brique partition générique […] un sélecteur d'origine »,
#: deux briques gardées pour comparer). La MÊME liste pour les deux vues de la page : chacune choisit
#: ce qu'elle montre (`score_view` : choix « Origine », puis « Forme » quand l'origine en a deux).
#: Une version `edits` se corrige quand la page l'édite (`''` : la partition PRINCIPALE, celle que
#: le rendu suit) ; `role` : lue en texte ; `same_as` : cachée quand elle EST la principale (la
#: réduite d'un cover est alors sa « Partition de travail »). Chaque version dit l'audio dont elle
#: est tirée (`follows` : ses REPÈRES, `score_timing`) et ses paroles horodatées (`lyrics`).
#: ⏳ « Audio source par pistes » (les partitions des pistes séparées réunies) : une étape à écrire,
#: après la mesure pistes contre mélange (`WAMA_QUALITE`).
SCORE_VERSIONS = [
    {'origin': 'Partition de travail', 'edits': '', 'follows': INPUT_SOURCE, 'lyrics': 'lyrics_in',
     'help': "Celle que le rendu suit : importée (dépôt, MIDI, Reader), composée par le modèle, ou "
             "réduite de l'audio source"},
    {'origin': 'Audio source', 'form': 'Réduite', 'role': 'extracted', 'same_as': 'extracted_score',
     'follows': INPUT_SOURCE, 'lyrics': 'lyrics_in',
     'empty': "Pas encore de partition réduite de l'audio source : cocher « Partition réduite » "
              "dans les réglages d'une card de reprise (cover), puis relancer."},
    {'origin': 'Audio source', 'form': 'Complète', 'edits': 'parts_score', 'role': 'parts',
     'follows': INPUT_SOURCE, 'lyrics': 'lyrics_in',
     'empty': "Pas encore de partition complète : cocher « Partition complète » dans les réglages "
              "d'une card de reprise (cover), puis relancer."},
    {'origin': 'Audio généré', 'form': 'Réduite', 'role': 'rendered_score', 'lyrics': 'lyrics_out',
     'empty': "Pas encore de partition réduite jouée : cocher « Partition réduite jouée » (et "
              "« Paroles chantées » pour ses paroles) dans les réglages de la card, puis relancer."},
    {'origin': 'Audio généré', 'form': 'Complète', 'role': 'rendered', 'lyrics': 'lyrics_out',
     'empty': "Pas encore de partition complète jouée : cocher « Partition complète jouée » dans "
              "les réglages de la card, puis relancer."},
]
#: Ce qu'est la « Partition de travail », selon le champ principal que la card remplit.
WORK_KINDS = {'reference_score': 'importée', 'planned_score': 'composée',
              'extracted_score': "réduite de l'audio source"}


register_surface(Surface(
    app='composer', key='score', label='Éditer la partition',
    model='composer.ComposerGeneration',
    # DEUX vues « Partition », une seule liste (2026-11-19) : la première ouvre sur la partition
    # que la page édite, la seconde sur celle du morceau produit — chacune passe à toute autre
    # origine pour comparer. Remplace « Partition de référence » / « Partition jouée » (2026-11-08),
    # dont chacune ne montrait que son côté.
    slots=(BrickSlot('score', 'score_view', 0, 0, 12, 14, {
               'media': 'audio', 'title': 'Partition', 'versions': SCORE_VERSIONS,
               'kinds': WORK_KINDS}),
           BrickSlot('transport', 'media_transport', 0, 14, 12, 3, {'role': 'audio'}),
           BrickSlot('rendered', 'score_view', 0, 17, 12, 12, {
               'media': 'audio', 'title': 'Partition comparée', 'versions': SCORE_VERSIONS,
               'kinds': WORK_KINDS, 'origin': 'Audio généré'}),
           BrickSlot('source', 'text_sections', 0, 29, 12, 6, {'title': 'Source ABC'}),
           BrickSlot('actions', 'surface_actions', 0, 0, 1, 5, zone='panel'),
           BrickSlot('versions', 'revision_history', 0, 5, 1, 6, zone='panel'),
           # Le MIXAGE en temps réel des pistes séparées (2026-11-17, décision de Fabien : « le
           # mixage temps réel va dans la page d'édition, la card porte les process ») — une
           # version de plus de l'audio lu ; ses niveaux sont les réglages de la refusion.
           BrickSlot('mixer', 'stem_mixer', 0, 11, 1, 9, {
               'role': 'audio', 'tracks': 'stems', 'levels': 'remix_levels',
               'without': 'remix_without', 'process': 'remix',
               'empty': "Pas de pistes séparées : cocher « Pistes séparées » dans les réglages "
                        "de la card, puis la lancer."}, zone='panel',
                     # Aussi dans l'onglet « Pistes séparées » de l'aperçu (2026-11-19, décision de
                     # Fabien : l'aperçu en écriture là où c'est justifié) : on y mixe et l'on y
                     # lance la refusion sans ouvrir la page.
                     face='separate')),
    reads={'audio': 'audio_output', 'rendered': 'rendered_parts_score',
           'rendered_score': 'rendered_score',
           # Les partitions de l'audio source LUES (2026-11-19) : ce qu'une vue montre quand la page
           # en édite une autre.
           'extracted': 'extracted_score', 'parts': 'parts_score',
           'lyrics_in': 'input_lyrics_timed', 'lyrics_out': 'rendered_lyrics_timed'},
    texts=('rendered', 'rendered_score', 'extracted', 'parts', 'lyrics_in', 'lyrics_out'),
    edits=INPUT_SCORE_FIELDS,
    also_edits=ALSO_EDITED,
    # La COMPLÈTE d'abord quand elle existe (2026-11-17, demande de Fabien : « si on l'a demandée,
    # c'est elle qu'on veut voir ») ; la réduite reste au choix « Partition ».
    edits_first=ALSO_EDITED,
    # Les niveaux du mixage et les pistes retirées : les réglages de la refusion (`params.py`).
    settings=('remix_levels', 'remix_without'),
    # L'original et ses pistes, servis avec le niveau que la refusion leur donnerait.
    context={'stems': 'stem_tracks'},
    # Une card à pistes s'ouvre pour les mixer, même sans partition.
    opens_with=('stems_index',),
    reruns='render', available=_score_available,
    # L'élément témoin des vignettes du catalogue des briques (nocturne) : une partition, sa
    # partition complète et un rendu audio — rien n'est lancé, les fichiers sont des témoins.
    witness={'prompt': "Témoin — la page d'édition de la partition", 'planned_score': '.abc',
             'parts_score': '.abc', 'rendered_parts_score': '.abc', 'rendered_score': '.abc',
             'audio_output': '.wav'}))
