"""Le PIPELINE de l'avatarizer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `workers.py` en lit `PIPELINE`.

TROIS process :
  • `speak`   — le texte → l'audio qui sera dit (service TTS). N'a lieu qu'en mode « pipeline »
    (un job « standalone » APPORTE son audio) ; sa sortie est un artefact de la card
    (`audio_input`) : il se vérifie, s'écoute et se reprend.
  • `animate` — l'audio + l'avatar → la vidéo : MuseTalk (photo) ou TalkingHead (avatar 3D).
    C'est le process de toute card.
  • `enhance` — « Visage » : l'amélioration faciale (CodeFormer) de la vidéo animée d'une PHOTO.
    Il a toujours lieu pour une photo, comme le process « Sortie » des autres apps : demandée,
    il garde la vidéo animée à côté et rend l'améliorée ; retirée, il rend la vidéo animée telle
    quelle. Sans objet pour un avatar 3D (CodeFormer restaure un visage photo).

Ce que la séparation apporte : changer l'avatar, le cadrage (`bbox_shift`) ou la qualité ne
re-synthétise plus la voix — avant, tout re-lancement rappelait le service TTS ; une animation
qui échoue (GPU) se relance sans refaire l'audio ; demander ou retirer l'amélioration faciale ne
rejoue pas l'animation (2026-10-04 — la vidéo animée est gardée par la brique du process
« Sortie », `output_process.output_step(transform=, apply=)`, champ `native_outputs`).
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'avatarizer'
_IMPL = 'avatarizer.workers:generate_avatar'


def _speak_applies(job, model_key) -> bool:
    return getattr(job, 'mode', '') == 'pipeline'


def is_3d_avatar(job) -> bool:
    """L'avatar de la card est-il un objet 3D ? Lu sur la NATURE du fichier (la brique du
    tirage) — le même jugement que l'ETA (`workers.avatarizer_eta_key_size`)."""
    from wama.common.utils.input_match import work_token_for
    name = (job.avatar_gallery_name if job.avatar_source == 'gallery'
            else (job.avatar_upload.name if job.avatar_upload else '')) or ''
    return work_token_for(name) == 'work_object3d'


def _enhance_applies(job, model_key) -> bool:
    return not is_3d_avatar(job)


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
                "rendu d'un avatar 3D riggé (TalkingHead).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['video', 'lip-sync', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', description="La parole à animer."),
            PortSpec('work_image', 'image', optional=True, group='travail',
                     description="La photo de l'avatar (MuseTalk)."),
            PortSpec('work_object3d', '3d', optional=True, group='travail',
                     description="L'avatar 3D riggé (TalkingHead).")],
    outputs=[PortSpec('video', 'video', description="La vidéo de l'avatar parlant.")]))


register(FunctionSpec(
    key='avatarizer.enhance', name='Avatarizer — améliorer le visage',
    description="Amélioration faciale (CodeFormer) de la vidéo animée d'une photo. La vidéo "
                "animée est gardée : retirer l'amélioration la rend telle quelle, sans réanimer.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['video', 'face', 'gpu'],
    inputs=[PortSpec('animated', 'video', description="La vidéo animée.")],
    outputs=[PortSpec('video', 'video', description="La vidéo au visage amélioré.")]))


# `watched` : les champs HORS schéma (fichiers, avatar) — les RÉGLAGES déclarent eux-mêmes ce
# qu'ils périment (`Param.stales`, params.py, 2026-10-05) ; `PIPELINE.watched_of(spec)` réunit
# les deux. Voix : texte, modèle TTS, curseur, langue, voix ; animation : modèle, bbox ;
# visage : `use_enhancer`.
PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('speak', label='Voix',
                share=1, applies=_speak_applies, outputs=('audio_input',),
                eta='avatarizer.workers:speak_eta_key_size'),
    ProcessSpec('animate', label='Animation', depends_on=('speak',),
                watched=('audio_input', 'avatar_source', 'avatar_gallery_name', 'avatar_upload'),
                gpu=True, share=4, outputs=('output_video',),
                eta='avatarizer.workers:avatarizer_eta_key_size'),
    ProcessSpec('enhance', label='Visage', depends_on=('animate',),
                gpu=True, share=3, applies=_enhance_applies,
                eta='avatarizer.workers:enhance_eta_key_size'),
), label='Avatarizer — voix, animation, visage', source_ref='avatarizer.function_specs:PIPELINE',
   model_of=lambda job: job.animation_model or 'auto')
