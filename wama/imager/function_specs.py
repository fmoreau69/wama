"""Le PIPELINE de l'imager — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

DEUX process, pour une image comme pour une vidéo :
  • `generate` — la consigne (et l'image de référence) → ce que le MODÈLE écrit : les images
    PNG, ou la vidéo MP4. C'est le process coûteux (GPU, de quelques secondes à plus d'une heure).
  • `output`   — les réglages de SORTIE appliqués à ce que le modèle a écrit : agrandissement
    (image) puis format et qualité (brique commune `output_formats.render_outputs`). Le fichier
    d'origine est GARDÉ tant que ces réglages le transforment.

Ce que la séparation apporte : changer le format, la qualité ou l'agrandissement ne REGÉNÈRE
plus — avant, tout relancement repassait par le modèle pour un réglage qui ne touche que la
sortie. Un agrandissement qui échoue se relance sans refaire l'image.

`output` a TOUJOURS lieu, même au format d'origine : c'est lui qui pose le rendu de la card, et
c'est en revenant au format d'origine qu'il rend le fichier natif tel quel — un process qui
n'aurait lieu que « quand il y a quelque chose à faire » laisserait la card périmée sans rien
pour la remettre à jour.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'imager'
_IMPL = 'imager.tasks:generate_image_task'

register(FunctionSpec(
    key='imager.generate', name='Imager — générer',
    description="Génère des images ou une vidéo à partir d'une consigne (et d'une image de "
                "référence quand le mode en prend une), avec le modèle de la card ou le tirage "
                "automatique. Rend ce que le modèle écrit, avant tout réglage de sortie.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'gpu'],
    inputs=[PortSpec('prompt', 'prompt', description="La consigne."),
            PortSpec('reference_image', 'image', optional=True,
                     description="L'image de référence (img2img, style, image → vidéo).")],
    outputs=[PortSpec('native', 'image', description="Les images (ou la vidéo) d'origine.")]))

register(FunctionSpec(
    key='imager.output', name='Imager — réglages de sortie',
    description="Applique les réglages de sortie de la card à ce que le modèle a écrit : "
                "agrandissement (image), format et qualité. Garde le fichier d'origine tant que "
                "ces réglages le transforment, pour se rejouer sans regénérer.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'format'],
    inputs=[PortSpec('native', 'image', description="Ce que le modèle a écrit.")],
    outputs=[PortSpec('result', 'image', description="Le rendu de la card.")]))


#: Réglages dont le changement périme la GÉNÉRATION : tout ce que le modèle lit. Les réglages de
#: sortie n'y sont pas — c'est le sens du découpage.
GENERATE_WATCHED = ('prompt', 'negative_prompt', 'prompt_keywords', 'model', 'quality_intent',
                    'generation_mode', 'reference_image', 'image_strength',
                    'width', 'height', 'steps', 'guidance_scale', 'seed', 'num_images',
                    'video_duration', 'video_fps', 'video_resolution')

PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('generate', label='Génération', watched=GENERATE_WATCHED, gpu=True, share=9,
                eta='imager.tasks:generate_eta'),
    output_spec(depends_on=('generate',)),
), label='Imager — génération puis réglages de sortie',
   source_ref='imager.function_specs:PIPELINE',
   model_of=lambda generation: generation.model or 'auto')
