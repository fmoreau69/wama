"""Les FONCTIONS du Converter qui ne sont pas un process de sa card — déclarées au catalogue commun.

`load_all()` importe ce module (les deux modules déclarants d'une app : `functions`,
`function_specs`). `function_specs.py` reste le PIPELINE de la card (convertir, post-traiter), que
le générateur relit pour ses jumelles ; ce qui s'applique à un FICHIER, hors de toute card, se
déclare ici.

`converter.shots` — `WAMA_APP_GENERATION_ROUTE.md §10.7.14 ⑲` : le producteur automatique de plans.
C'est le métier du Converter (ffmpeg ; il exportera le média recoupé, `⑱`), et le premier
PRODUCTEUR de marques du monde Médias : la fonction se déclare au catalogue (un nœud du Studio, ses
réglages typés), le producteur s'inscrit au commun (`media_marks`), qui range la piste une fois par
fichier et la rend à toute card qui emploie cette vidéo.
"""
from wama.common.catalog.data_types import DataType
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  ParamSpec, PortSpec, register)
from wama.common.catalog.marks import DERIVED, Track
from wama.common.utils.media_marks import Producer, register_producer

from .utils.shots import MIN_DURATION, THRESHOLD

SHOTS = 'shots'

register(FunctionSpec(
    key='converter.shots', name='Converter — détecter les plans',
    description="Repère les changements de plan d'une vidéo (ffmpeg) et range ses plans comme une "
                "piste de segments sur l'axe du fichier : ce qu'on gardera, masquera ou "
                "réordonnera pour la couper. La vidéo n'est pas modifiée.",
    category=FC.DETECTOR, binding=Binding.APP, app='converter',
    impl='converter.utils.shots:shots_job',
    tags=['ffmpeg', 'video', 'segments'],
    inputs=[PortSpec('video', 'video', description="La vidéo à analyser.")],
    outputs=[PortSpec(SHOTS, DataType.SEGMENTS, produced_fields=['start', 'end', 'score'],
                      description="Les plans, du début à la fin de la vidéo, sans trou ; `score` "
                                  "est la force de la coupe qui ouvre le plan.")],
    params=[ParamSpec('threshold', 'float', THRESHOLD, min=1, max=100,
                      description="Sensibilité : plus bas, plus de coupes (fondus, mouvements "
                                  "brusques) ; plus haut, les seules coupes franches."),
            ParamSpec('min_duration', 'float', MIN_DURATION, min=0, max=30, unit='s',
                      description="Durée minimale d'un plan : en deçà, il rejoint son voisin.")],
    cost={'cpu_bound': True},
))

#: La piste « Plans » d'une vidéo. Les plans sont DÉTECTÉS, pas mesurés à la main : on les corrige
#: (scinder, fusionner), on les nomme, on les masque et on les réordonne — c'est la coupe — et on
#: en tire une card ; toujours dans une piste dérivée, la détection reste intacte.
register_producer(Producer(
    track=Track(SHOTS, 'Plans', kind=DataType.SEGMENTS, origin=SHOTS, attributes=('score',),
                gestures=('extract', 'label', 'mask', 'merge', 'reorder', 'split'), edits=DERIVED),
    natures=('video',),
    detect='wama.converter.utils.shots:detect_shots',
    function='converter.shots',
))
