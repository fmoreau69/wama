"""Le PIPELINE de l'anonymizer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

DEUX process :
  • `generate` — le média → le média FLOUTÉ : choix du ou des modèles (couverture des classes),
    détection, floutage (YOLO ou SAM3). C'est le process coûteux (GPU, la durée d'une vidéo).
  • `output`   — le format et la qualité de sortie (process COMMUN, `output_process`) : le
    fichier flouté d'origine est gardé tant que la sortie le transforme.

Ce que la séparation apporte : changer le format ou la qualité ne re-floute plus.

⏳ Détection et floutage restent UN process : les séparer demande de garder les détections
(décision n°2), ce qui n'est pas fait.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'anonymizer'
_IMPL = 'anonymizer.tasks:process_single_media'

register(FunctionSpec(
    key='anonymizer.generate', name='Anonymizer — flouter',
    description="Détecte et floute, dans une image ou une vidéo, les classes désignées (visages, "
                "plaques…) ou ce qu'une description nomme, avec le ou les modèles qui les couvrent.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'gpu'],
    inputs=[PortSpec('work_media', 'video', description="L'image ou la vidéo à anonymiser.")],
    outputs=[PortSpec('native', 'video', description="Le média flouté, tel que le moteur l'écrit.")]))

register(FunctionSpec(
    key='anonymizer.output', name='Anonymizer — réglages de sortie',
    description="Applique le format et la qualité de sortie de la card au média flouté. Garde le "
                "fichier d'origine tant que la sortie le transforme, pour se rejouer sans re-flouter.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'format'],
    inputs=[PortSpec('native', 'video', description="Le média flouté d'origine.")],
    outputs=[PortSpec('result', 'video', description="Le média flouté au format demandé.")]))


#: Réglages dont le changement périme le FLOUTAGE : tout ce que sa glu lit de l'élément.
GENERATE_WATCHED = ('file', 'target_mode', 'classes2blur', 'sam3_prompt', 'model_to_use',
                    'precision_level', 'use_segmentation', 'blur_ratio', 'roi_enlargement',
                    'progressive_blur', 'detection_threshold', 'interpolate_detections',
                    'max_interpolation_frames', 'show_preview', 'show_boxes', 'show_labels',
                    'show_conf')

PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('generate', label='Floutage', watched=GENERATE_WATCHED, gpu=True, share=9),
    output_spec(depends_on=('generate',)),
), label='Anonymizer — floutage puis réglages de sortie',
   source_ref='anonymizer.function_specs:PIPELINE')
