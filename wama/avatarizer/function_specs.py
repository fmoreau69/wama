"""Le PIPELINE de l'avatarizer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `workers.py` en lit `PIPELINE`.

DEUX process :
  • `speak`   — le texte → l'audio qui sera dit (service TTS). N'a lieu qu'en mode « pipeline »
    (un job « standalone » APPORTE son audio) ; sa sortie est un artefact de la card
    (`audio_input`) : il se vérifie, s'écoute et se reprend.
  • `animate` — l'audio + l'avatar → la vidéo : MuseTalk (photo) ou TalkingHead (avatar 3D), puis
    CodeFormer quand l'amélioration faciale est demandée. C'est le process de toute card.

Ce que la séparation apporte : changer l'avatar, le cadrage (`bbox_shift`) ou la qualité ne
re-synthétise plus la voix — avant, tout re-lancement rappelait le service TTS ; une animation
qui échoue (GPU) se relance sans refaire l'audio.

⏳ CodeFormer n'est pas un process à part : la vidéo animée qu'il reprend vit dans un dossier de
travail, pas dans un champ de la card — l'en séparer demande de la persister (décision n°2).
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'avatarizer'
_IMPL = 'avatarizer.workers:generate_avatar'


def _speak_applies(job, model_key) -> bool:
    return getattr(job, 'mode', '') == 'pipeline'


register(FunctionSpec(
    key='avatarizer.speak', name='Avatarizer — dire le texte',
    description="Synthétise le texte de la card (service TTS, voix et langue de la card) : "
                "l'audio que l'avatar dira. Sans objet quand la card apporte son audio.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech', 'tts'],
    inputs=[PortSpec('prompt', 'prompt', description="Le texte à dire.")],
    outputs=[PortSpec('audio', 'audio', description="L'audio de la parole.")]))

register(FunctionSpec(
    key='avatarizer.animate', name="Avatarizer — animer l'avatar",
    description="Anime l'avatar sur l'audio : synchronisation labiale d'une photo (MuseTalk) ou "
                "rendu d'un avatar 3D riggé (TalkingHead), puis amélioration faciale si demandée.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['video', 'lip-sync', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', description="La parole à animer."),
            PortSpec('work_image', 'image', optional=True, group='travail',
                     description="La photo de l'avatar (MuseTalk)."),
            PortSpec('work_object3d', '3d', optional=True, group='travail',
                     description="L'avatar 3D riggé (TalkingHead).")],
    outputs=[PortSpec('video', 'video', description="La vidéo de l'avatar parlant.")]))


PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('speak', label='Voix',
                watched=('text_content', 'tts_model', 'voice_preset', 'language', 'quality_intent'),
                share=1, applies=_speak_applies, outputs=('audio_input',)),
    ProcessSpec('animate', label='Animation', depends_on=('speak',),
                watched=('audio_input', 'avatar_source', 'avatar_gallery_name', 'avatar_upload',
                         'animation_model', 'bbox_shift', 'use_enhancer', 'quality_mode'),
                gpu=True, share=4, outputs=('output_video',)),
), label='Avatarizer — voix puis animation', source_ref='avatarizer.function_specs:PIPELINE',
   model_of=lambda job: job.animation_model or 'auto')
