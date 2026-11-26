"""Les FONCTIONS du Composer qui ne sont pas un process de sa card — déclarées au catalogue commun.

`load_all()` importe ce module (les deux modules déclarants d'une app : `functions`,
`function_specs`). `function_specs.py` reste le PIPELINE de la card ; ce qui s'applique à un
FICHIER, hors de toute card, se déclare ici — la forme du Converter et de ses plans.

`composer.music_marks` — `WAMA_APP_GENERATION_ROUTE.md §10.7.14 ㉑` : la STRUCTURE d'un morceau.
C'est le métier du Composer (la musique) et le premier producteur À MODÈLE : une passe du modèle de
la tâche `audio-to-score` remplit quatre pistes de l'audio — ses parties, ses mesures, sa tonalité,
ses accords —, rangées une fois par fichier et rendues à toute card qui l'emploie. Elles ne sont
analysées que sur demande (un modèle occupe la carte graphique), et un process de card qui fait
déjà passer ce modèle les dépose au passage (`utils/music_marks.keep`).
"""
from wama.common.backends.score_extraction_base import CHORDS, MEASURES, STRUCTURE, TONALITY
from wama.common.catalog.data_types import DataType
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.catalog.marks import CATEGORY, DERIVED, Track
from wama.common.utils.media_marks import Producer, register_producer

from .utils.music_marks import ANALYSIS

MUSIC_MARKS_FUNCTION = 'composer.music_marks'

#: Les quatre pistes d'un morceau, sur le temps de son audio. Les PARTIES sont détectées : on les
#: corrige (renommer, scinder, fusionner, retailler), on en masque, on en tire une card — dans une
#: piste dérivée, la détection reste intacte. Mesures, tonalité et accords se regardent.
MUSIC_TRACKS = (
    Track(STRUCTURE, 'Parties', kind=DataType.SEGMENTS, origin=STRUCTURE, attributes=('label',),
          color_by='label', scale=CATEGORY,
          gestures=('extract', 'label', 'mask', 'merge', 'retime', 'split'), edits=DERIVED),
    Track(MEASURES, 'Mesures', kind=DataType.SEGMENTS, origin=MEASURES,
          attributes=('number', 'meter', 'tempo'), color_by='meter', scale=CATEGORY),
    Track(TONALITY, 'Tonalité', kind=DataType.SEGMENTS, origin=TONALITY, attributes=('key',),
          color_by='key', scale=CATEGORY),
    Track(CHORDS, 'Accords', kind=DataType.SEGMENTS, origin=CHORDS, attributes=('chord',),
          color_by='chord', scale=CATEGORY),
)

register(FunctionSpec(
    key=MUSIC_MARKS_FUNCTION, name="Composer — structure d'un morceau",
    description="Repère la structure d'un morceau dans son audio et la range comme des pistes de "
                "segments sur l'axe du fichier : ses parties (intro, couplet, refrain, pont…), "
                "ses mesures (chiffrage et tempo de chacune), sa tonalité et ses accords. Par le "
                "modèle qui en extrait la partition réduite ; l'audio n'est pas modifié.",
    category=FC.DETECTOR, binding=Binding.APP, app='composer',
    impl='composer.tasks:music_marks_task',
    tags=['audio', 'music', 'gpu', 'segments'],
    inputs=[PortSpec('audio', 'audio', description="L'audio du morceau à analyser.")],
    outputs=[PortSpec(STRUCTURE, DataType.SEGMENTS,
                      produced_fields=['start', 'end', 'label', 'number', 'meter', 'tempo',
                                       'key', 'chord'],
                      description="Les parties du morceau ; les mesures (`number`, `meter`, "
                                  "`tempo`), la tonalité (`key`) et les accords (`chord`) sont "
                                  "rangés avec elles, chacun dans sa piste.")],
))

for _track in MUSIC_TRACKS:
    register_producer(Producer(
        track=_track, natures=('audio',),
        detect='wama.composer.utils.music_marks:analyse',
        function=MUSIC_MARKS_FUNCTION,
        analysis=ANALYSIS,
        task='wama.composer.tasks:music_marks_task',
        on_demand=True,
    ))
