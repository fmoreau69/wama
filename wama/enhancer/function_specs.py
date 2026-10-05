"""Le PIPELINE de l'enhancer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

UN pipeline pour les DEUX files de l'app (image/vidéo : `Enhancement` ; audio :
`AudioEnhancement`) — un pipeline se déclare par app, et les deux files ont la même forme :
  • `generate` — le média → le média AMÉLIORÉ : agrandissement d'une image ou d'une vidéo par
    le modèle désigné ou tiré, ou restauration de la parole d'un audio. C'est le process coûteux.
  • `output`   — le format et la qualité de sortie (process COMMUN, `output_process`) : le
    fichier amélioré d'origine est gardé tant que la sortie le transforme.

Ce que la séparation apporte : changer le format ou la qualité ne relance plus l'amélioration.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'enhancer'
_IMPL = 'enhancer.tasks:enhance_media'

register(FunctionSpec(
    key='enhancer.generate', name='Enhancer — améliorer',
    description="Agrandit une image ou une vidéo avec le modèle désigné ou tiré (débruitage, "
                "mélange avec l'original, tuiles), ou restaure la parole d'un audio "
                "(débruitage, amélioration).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'audio', 'gpu'],
    inputs=[PortSpec('work_media', 'video', description="L'image, la vidéo ou l'audio à améliorer.")],
    outputs=[PortSpec('native', 'video', description="Le média amélioré, tel que le moteur l'écrit.")]))

register(FunctionSpec(
    key='enhancer.output', name='Enhancer — réglages de sortie',
    description="Applique le format et la qualité de sortie de la card au média amélioré. Garde "
                "le fichier d'origine tant que la sortie le transforme, pour se rejouer sans "
                "relancer l'amélioration.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'audio', 'format'],
    inputs=[PortSpec('native', 'video', description="Le média amélioré d'origine.")],
    outputs=[PortSpec('result', 'video', description="Le média amélioré au format demandé.")]))


#: Ce que l'AMÉLIORATION surveille HORS schéma : le fichier, la tuile, et `denoising_strength`
#: (le champ du réglage `strength`). Les RÉGLAGES des deux files déclarent eux-mêmes ce qu'ils
#: périment (`Param.stales`, params.py, 2026-10-05) ; `PIPELINE.watched_of(spec)` réunit les deux.
#: Les champs d'une file n'existent pas dans l'autre : la photo les lit absents, toujours pareil.
GENERATE_WATCHED = ('input_file', 'tile_size', 'denoising_strength')

PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('generate', label='Amélioration', watched=GENERATE_WATCHED, gpu=True, share=9,
                eta='enhancer.tasks:generate_eta_key_size'),
    output_spec(depends_on=('generate',)),
), label='Enhancer — amélioration puis réglages de sortie',
   source_ref='enhancer.function_specs:PIPELINE',
   # Deux files, un pipeline : le modèle d'un média (`ai_model`), le moteur d'un audio.
   model_of=lambda item: (getattr(item, 'ai_model', None)
                          or getattr(item, 'engine', None) or 'auto'))
