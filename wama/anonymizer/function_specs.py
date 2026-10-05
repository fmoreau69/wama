"""Le PIPELINE de l'anonymizer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

TROIS process (2026-10-04, décision de Fabien : « on sépare détection/segmentation et
floutage ») :
  • `detect` — « Détection » : le média → ses DÉTECTIONS (document `detections`, type de donnée
    commun) — choix du ou des modèles (couverture des classes), YOLO ou SAM3, boîtes et contours.
    C'est le process coûteux (GPU, la durée d'une vidéo).
  • `blur`   — « Floutage » : le média réécrit depuis ses détections — intensité, contour
    progressif, agrandissement de la zone, interpolation des trous d'une piste. Aucun modèle.
  • `output` — le format et la qualité de sortie (process COMMUN, `output_process`) : le
    fichier flouté d'origine est gardé tant que la sortie le transforme.

Ce que la séparation apporte : changer l'intensité du flou ou l'interpolation ne redétecte plus ;
changer le format ne re-floute plus ; et l'aperçu peut montrer les détections à côté du flou.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'anonymizer'
_IMPL = 'anonymizer.tasks:process_single_media'

register(FunctionSpec(
    key='anonymizer.detect', name='Anonymizer — détecter',
    description="Détecte, dans une image ou une vidéo, les classes désignées (visages, plaques…) "
                "ou ce qu'une description nomme, avec le ou les modèles qui les couvrent : boîtes, "
                "contours (segmentation) et pistes, frame par frame.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'detection', 'gpu'],
    inputs=[PortSpec('work_media', 'video', description="L'image ou la vidéo à anonymiser.")],
    outputs=[PortSpec('detections', 'detections',
                      description="Les objets détectés, frame par frame (boîte, contour, piste).")]))

register(FunctionSpec(
    key='anonymizer.blur', name='Anonymizer — flouter',
    description="Floute le média selon ses détections : au contour quand elles en portent un, au "
                "rectangle sinon, trous d'une piste interpolés. Aucun modèle n'est chargé.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'blur'],
    inputs=[PortSpec('work_media', 'video', description="L'image ou la vidéo à anonymiser."),
            PortSpec('detections', 'detections', description="Ce qu'il faut flouter.")],
    outputs=[PortSpec('native', 'video', description="Le média flouté, tel que le floutage "
                                                     "l'écrit.")]))

register(FunctionSpec(
    key='anonymizer.output', name='Anonymizer — réglages de sortie',
    description="Applique le format et la qualité de sortie de la card au média flouté. Garde le "
                "fichier d'origine tant que la sortie le transforme, pour se rejouer sans re-flouter.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'format'],
    inputs=[PortSpec('native', 'video', description="Le média flouté d'origine.")],
    outputs=[PortSpec('result', 'video', description="Le média flouté au format demandé.")]))


#: Ce que la DÉTECTION surveille HORS schéma : le fichier et les classes (liste éditée à part).
#: Les RÉGLAGES déclarent eux-mêmes ce qu'ils périment (`Param.stales`, params.py, 2026-10-05) —
#: détection : mode, prompt SAM3, modèle, curseur, segmentation, seuil ; floutage : flou, bords,
#: zone, flou progressif, interpolation. `PIPELINE.watched_of(spec)` réunit les deux. Les réglages
#: d'AFFICHAGE (`show_*`) ne périment rien : ils ne changent que l'aperçu (`stales=()`).
DETECT_WATCHED = ('file', 'classes2blur')
BLUR_WATCHED = ()

PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('detect', label='Détection', watched=DETECT_WATCHED, gpu=True, share=7,
                outputs=('detections_file',), eta='anonymizer.tasks:anonymizer_eta_key_size'),
    ProcessSpec('blur', label='Floutage', depends_on=('detect',), watched=BLUR_WATCHED, share=3,
                eta='anonymizer.tasks:blur_eta'),
    output_spec(depends_on=('blur',)),
), label='Anonymizer — détection, floutage, réglages de sortie',
   source_ref='anonymizer.function_specs:PIPELINE',
   model_of=lambda media: media.model_to_use or 'auto')
