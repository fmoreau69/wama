"""
Studio — adapters d'exécution par app (« runners »).

⛔ SHIM V1 GELÉ (recadrage Fabien 2026-07-12 — STUDIO_VISION « principe directeur » +
mémoire feedback_studio_uniform_contract) : ces adapters manuels s'adaptent à l'état
COURANT des apps (signatures tool_api disparates, params dupliqués, champs de sortie par
modèle) — c'est l'anti-pattern. NE PLUS ÉTENDRE ce fichier : tout manque découvert est un
item de PORTAGE de l'app (normaliser sa triade tool_api / ses clés canoniques), et l'app
bascule alors sur le runner GÉNÉRIQUE (generic_runner.py) piloté par le contrat. Ce
fichier doit se VIDER app par app jusqu'à suppression.

Chaque app exécutable dans un pipeline déclare la triade canonique via `wama/tool_api.py`
(philosophie CLAUDE.md §5 : chaque app expose son API à l'assistant/méta-app) :

    create(user, inputs, params) -> item_id      # crée l'item dans l'app (PENDING)
    start(user, item_id)         -> None|error   # lance le traitement (Celery de l'app)
    poll(user, item_id)          -> {'status', 'progress', 'output', 'error'}
                                     # output = chemin MEDIA-relatif consommable en aval

`inputs` = valeurs produites par les nœuds AMONT, indexées par type de port ('audio',
'prompt', …). `params` = réglages saisis sur le nœud dans le canvas (JSON libre, validé ici).

V1 : chaîne phare synthesizer → avatarizer (décision 2026-07-11 : avatarizer est
standalone-only, le pipeline texte→TTS→avatar EST cette composition studio).
Ajouter une app = ajouter une entrée ici — AUCUNE logique d'orchestration à toucher
(elle vit dans studio/tasks.py).
"""
from __future__ import annotations


# ── synthesizer : texte → audio ────────────────────────────────────────────────

def _synthesizer_create(user, inputs, params):
    from wama import tool_api
    text = (inputs.get('prompt') or inputs.get('text') or params.get('text') or '').strip()
    if not text:
        raise ValueError("Nœud synthesizer : aucun texte (renseignez le paramètre « Texte » du nœud).")
    res = tool_api.synthesize_text(
        user, text,
        language=params.get('language', 'fr'),
        tts_model=params.get('tts_model', 'xtts_v2'),
        voice_preset=params.get('voice_preset', 'default'),
    )
    if 'error' in res:
        raise ValueError(f"synthesizer : {res['error']}")
    return res['synthesis_id']


def _synthesizer_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_synthesizer(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"synthesizer : {res['error']}")


def _synthesizer_poll(user, item_id):
    from wama.synthesizer.models import VoiceSynthesis
    s = VoiceSynthesis.objects.get(pk=item_id, user=user)
    return {
        'status': s.status,
        'progress': s.progress or 0,
        'output': (s.audio_output.name if s.audio_output else ''),
        'error': s.error_message or '',
    }


# ── avatarizer : audio (+ avatar) → vidéo ──────────────────────────────────────

def _avatarizer_create(user, inputs, params):
    from wama import tool_api
    audio = inputs.get('audio') or ''
    if not audio:
        raise ValueError("Nœud avatarizer : aucune entrée audio (connectez une sortie audio).")
    avatar = params.get('avatar_gallery_name') or ''
    if not avatar:
        raise ValueError("Nœud avatarizer : aucun avatar (renseignez le paramètre « Avatar » du nœud).")
    res = tool_api.add_to_avatarizer(
        user,
        mode='standalone',
        audio_path=audio,
        avatar_source='gallery',
        avatar_gallery_name=avatar,
        quality_mode=params.get('quality_mode', 'fast'),
        use_enhancer=bool(params.get('use_enhancer', False)),
        bbox_shift=int(params.get('bbox_shift', 0) or 0),
    )
    if 'error' in res:
        raise ValueError(f"avatarizer : {res['error']}")
    return res['job_id']


def _avatarizer_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_avatarizer(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"avatarizer : {res['error']}")


def _avatarizer_poll(user, item_id):
    from wama.avatarizer.models import AvatarJob
    j = AvatarJob.objects.get(pk=item_id, user=user)
    return {
        'status': j.status,
        'progress': j.progress or 0,
        'output': (j.output_video.name if j.output_video else ''),
        'error': j.error_message or '',
    }


# ── converter : média → média (changement de FORMAT — « configurer la sortie ») ──

def _category_of_path(path):
    """Catégorie WAMA ('audio'|'video'|'image'|'document') d'un chemin, via app_registry."""
    import os
    from wama.common import app_registry as AR
    ext = os.path.splitext(path)[1].lower()
    for cat, exts in (('audio', AR.AUDIO_EXTENSIONS), ('video', AR.VIDEO_EXTENSIONS),
                      ('image', AR.IMAGE_EXTENSIONS), ('document', AR.DOCUMENT_EXTENSIONS)):
        if ext in exts:
            return cat
    return 'document'


def _converter_create(user, inputs, params):
    from wama import tool_api
    src_path = (inputs.get('audio') or inputs.get('video') or inputs.get('image')
                or inputs.get('document') or '')
    if not src_path:
        raise ValueError("Nœud converter : aucune entrée média (connectez une sortie).")
    fmt = (params.get('output_format') or '').strip().lstrip('.').lower()
    if not fmt:
        raise ValueError("Nœud converter : renseignez le paramètre « Format de sortie ».")
    res = tool_api.convert_file(user, src_path, fmt,
                                quality_preset=params.get('quality_preset', 'balanced'))
    if 'error' in res:
        raise ValueError(f"converter : {res['error']}")
    return res['job_id']


def _converter_start(user, item_id):
    # convert_file dispatche déjà la tâche Celery (status RUNNING au retour) — rien à faire.
    pass


def _converter_poll(user, item_id):
    from wama.converter.models import ConversionJob
    j = ConversionJob.objects.get(pk=item_id, user=user)
    return {
        'status': j.status,
        'progress': j.progress or 0,
        'output': (j.output_file.name if j.output_file else ''),
        'error': j.error_message or '',
    }


# ── transcriber : audio/vidéo → TEXTE ─────────────────────────────────────────

def _transcriber_create(user, inputs, params):
    from wama import tool_api
    media = inputs.get('audio') or inputs.get('video') or ''
    if not media:
        raise ValueError("Nœud transcriber : aucune entrée audio/vidéo.")
    res = tool_api.add_to_transcriber(user, media, backend=params.get('backend', 'auto'))
    if 'error' in res:
        raise ValueError(f"transcriber : {res['error']}")
    return res['transcript_id']


def _transcriber_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_transcriber(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"transcriber : {res['error']}")


def _transcriber_poll(user, item_id):
    from wama.transcriber.models import Transcript
    t = Transcript.objects.get(pk=item_id, user=user)
    return {'status': t.status, 'progress': t.progress or 0,
            'output': t.text or '', 'is_text': True, 'error': ''}


# ── describer : média → TEXTE (description) ───────────────────────────────────

def _describer_create(user, inputs, params):
    from wama import tool_api
    media = (inputs.get('image') or inputs.get('video') or inputs.get('audio')
             or inputs.get('document') or '')
    if not media:
        raise ValueError("Nœud describer : aucune entrée média.")
    res = tool_api.add_to_describer(user, media,
                                    output_format=params.get('output_format', 'detailed'),
                                    output_language=params.get('output_language', 'fr'))
    if 'error' in res:
        raise ValueError(f"describer : {res['error']}")
    return res['description_id']


def _describer_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_describer(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"describer : {res['error']}")


def _describer_poll(user, item_id):
    from wama.describer.models import Description
    d = Description.objects.get(pk=item_id, user=user)
    return {'status': d.status, 'progress': d.progress or 0,
            'output': d.result_text or '', 'is_text': True,
            'error': d.error_message or ''}


# ── reader : document → TEXTE (OCR) ────────────────────────────────────────────

def _reader_create(user, inputs, params):
    from wama import tool_api
    doc = inputs.get('document') or inputs.get('image') or ''
    if not doc:
        raise ValueError("Nœud reader : aucune entrée document/image.")
    res = tool_api.add_to_reader(user, doc, backend=params.get('backend', 'auto'))
    if 'error' in res:
        raise ValueError(f"reader : {res['error']}")
    return res['item_id']


def _reader_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_reader(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"reader : {res['error']}")


def _reader_poll(user, item_id):
    from wama.reader.models import ReadingItem
    r = ReadingItem.objects.get(pk=item_id, user=user)
    return {'status': r.status, 'progress': r.progress or 0,
            'output': r.result_text or '', 'is_text': True,
            'error': r.error_message or ''}


# ── composer : prompt → musique/SFX (audio) ────────────────────────────────────

def _composer_create(user, inputs, params):
    from wama import tool_api
    prompt = (inputs.get('prompt') or inputs.get('text') or params.get('prompt') or '').strip()
    if not prompt:
        raise ValueError("Nœud composer : aucun prompt (connectez un nœud Texte ou renseignez le paramètre).")
    kwargs = {'duration': int(params.get('duration', 15) or 15)}
    if params.get('model'):
        kwargs['model'] = params['model']
    res = tool_api.compose_music(user, prompt, **kwargs)
    if 'error' in res:
        raise ValueError(f"composer : {res['error']}")
    return res['generation_id']


def _composer_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_composer(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"composer : {res['error']}")


def _composer_poll(user, item_id):
    from wama.composer.models import ComposerGeneration
    g = ComposerGeneration.objects.get(pk=item_id, user=user)
    return {'status': g.status, 'progress': g.progress or 0,
            'output': (g.audio_output.name if g.audio_output else ''),
            'error': g.error_message or ''}


# ── enhancer : image/vidéo → image/vidéo améliorée ─────────────────────────────

def _enhancer_create(user, inputs, params):
    from wama import tool_api
    media = inputs.get('image') or inputs.get('video') or ''
    if not media:
        raise ValueError("Nœud enhancer : aucune entrée image/vidéo.")
    res = tool_api.add_to_enhancer(user, media,
                                   ai_model=params.get('ai_model', 'RealESR_Gx4'),
                                   denoise=bool(params.get('denoise', False)))
    if 'error' in res:
        raise ValueError(f"enhancer : {res['error']}")
    return res['enhancement_id']


def _enhancer_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_enhancer(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"enhancer : {res['error']}")


def _enhancer_poll(user, item_id):
    from wama.enhancer.models import Enhancement
    e = Enhancement.objects.get(pk=item_id, user=user)
    return {'status': e.status, 'progress': e.progress or 0,
            'output': (e.output_file.name if e.output_file else ''),
            'error': e.error_message or ''}


# ── imager : prompt → image (ou vidéo) ─────────────────────────────────────────

def _imager_create(user, inputs, params):
    from wama import tool_api
    prompt = (inputs.get('prompt') or inputs.get('text') or params.get('prompt') or '').strip()
    if not prompt:
        raise ValueError("Nœud imager : aucun prompt (connectez un nœud Texte ou renseignez le paramètre).")
    res = tool_api.create_image(user, prompt,
                                model=params.get('model', 'stable-diffusion-xl'),
                                width=int(params.get('width', 1024) or 1024),
                                height=int(params.get('height', 1024) or 1024))
    if 'error' in res:
        raise ValueError(f"imager : {res['error']}")
    return res['generation_id']


def _imager_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_imager(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"imager : {res['error']}")


def _imager_poll(user, item_id):
    from wama.imager.models import ImageGeneration
    g = ImageGeneration.objects.get(pk=item_id, user=user)
    output = ''
    if g.output_video:
        output = g.output_video.name
    elif g.generated_images:
        imgs = g.generated_images if isinstance(g.generated_images, list) else []
        output = imgs[0] if imgs else ''
        if output.startswith('/media/'):
            output = output[len('/media/'):]
    return {'status': g.status, 'progress': g.progress or 0,
            'output': output, 'error': g.error_message or ''}


# ── anonymizer : image/vidéo → média flouté ────────────────────────────────────

def _anonymizer_create(user, inputs, params):
    from wama import tool_api
    media = inputs.get('image') or inputs.get('video') or ''
    if not media:
        raise ValueError("Nœud anonymizer : aucune entrée image/vidéo.")
    res = tool_api.add_to_anonymizer(user, media,
                                     use_sam3=bool(params.get('use_sam3', False)),
                                     sam3_prompt=params.get('sam3_prompt', ''))
    if 'error' in res:
        raise ValueError(f"anonymizer : {res['error']}")
    return res['media_id']


def _anonymizer_start(user, item_id):
    from wama import tool_api
    res = tool_api.start_anonymizer(user, item_id)
    if isinstance(res, dict) and res.get('error'):
        raise ValueError(f"anonymizer : {res['error']}")


def _anonymizer_poll(user, item_id):
    import glob
    import os
    from django.conf import settings
    from wama.anonymizer.models import Media
    m = Media.objects.get(pk=item_id, user=user)
    output = ''
    if m.status == 'SUCCESS':
        # Sortie = chemin DÉRIVÉ (_blurred_*) — même logique que la vue download_media
        base, ext = os.path.splitext(m.file.name)
        candidates = sorted(glob.glob(os.path.join(settings.MEDIA_ROOT, base + '_blurred*' + ext)))
        if candidates:
            output = os.path.relpath(candidates[0], settings.MEDIA_ROOT).replace('\\', '/')
    return {'status': m.status, 'progress': m.blur_progress or 0,
            'output': output, 'error': m.error_message or ''}


# ── Registre ───────────────────────────────────────────────────────────────────
# output_type : type de port produit (pour router la sortie vers le bon port aval).
# params_spec : déclaration des réglages de nœud (rendus par le canvas — métadonnée-driven).
RUNNERS = {
    'synthesizer': {
        'create': _synthesizer_create,
        'start': _synthesizer_start,
        'poll': _synthesizer_poll,
        'output_type': 'audio',
        'params_spec': [
            {'name': 'text', 'label': 'Texte', 'type': 'textarea',
             'placeholder': 'Texte à synthétiser (si aucun nœud prompt en amont)…'},
            {'name': 'language', 'label': 'Langue', 'type': 'select',
             'options': ['fr', 'en', 'es', 'de'], 'default': 'fr'},
            {'name': 'voice_preset', 'label': 'Voix', 'type': 'select',
             'options': ['default', 'male_1', 'male_2', 'female_1', 'female_2'], 'default': 'default'},
        ],
    },
    'transcriber': {
        'create': _transcriber_create, 'start': _transcriber_start, 'poll': _transcriber_poll,
        'output_type': 'text',
        'params_spec': [
            {'name': 'backend', 'label': 'Moteur ASR', 'type': 'select',
             'options': ['auto', 'whisper', 'vibevoice'], 'default': 'auto'},
        ],
    },
    'describer': {
        'create': _describer_create, 'start': _describer_start, 'poll': _describer_poll,
        'output_type': 'text',
        'params_spec': [
            {'name': 'output_format', 'label': 'Style', 'type': 'select',
             'options': ['detailed', 'concise', 'technical'], 'default': 'detailed'},
            {'name': 'output_language', 'label': 'Langue', 'type': 'select',
             'options': ['fr', 'en'], 'default': 'fr'},
        ],
    },
    'reader': {
        'create': _reader_create, 'start': _reader_start, 'poll': _reader_poll,
        'output_type': 'text',
        'params_spec': [
            {'name': 'backend', 'label': 'Moteur OCR', 'type': 'select',
             'options': ['auto', 'doctr', 'olmocr', 'glmocr'], 'default': 'auto'},
        ],
    },
    'composer': {
        'create': _composer_create, 'start': _composer_start, 'poll': _composer_poll,
        'output_type': 'audio',
        'params_spec': [
            {'name': 'prompt', 'label': 'Prompt (si pas de nœud Texte en amont)', 'type': 'textarea'},
            {'name': 'duration', 'label': 'Durée (s)', 'type': 'text', 'default': '15'},
        ],
    },
    'enhancer': {
        'create': _enhancer_create, 'start': _enhancer_start, 'poll': _enhancer_poll,
        'output_type': 'auto',   # image OU vidéo — catégorie du fichier produit
        'params_spec': [
            {'name': 'ai_model', 'label': 'Modèle', 'type': 'text',
             'placeholder': 'RealESR_Gx4 (défaut) — clés du catalogue enhancer'},
        ],
    },
    'imager': {
        'create': _imager_create, 'start': _imager_start, 'poll': _imager_poll,
        'output_type': 'auto',   # image (ou vidéo selon le mode)
        'params_spec': [
            {'name': 'prompt', 'label': 'Prompt (si pas de nœud Texte en amont)', 'type': 'textarea'},
            {'name': 'model', 'label': 'Modèle', 'type': 'select',
             'options': ['stable-diffusion-xl', 'hunyuan-image-2.1', 'qwen-image-2'],
             'default': 'stable-diffusion-xl'},
        ],
    },
    'anonymizer': {
        'create': _anonymizer_create, 'start': _anonymizer_start, 'poll': _anonymizer_poll,
        'output_type': 'auto',
        'params_spec': [
            {'name': 'use_sam3', 'label': 'SAM3 (segmentation fine)', 'type': 'select',
             'options': ['', '1'], 'default': ''},
            {'name': 'sam3_prompt', 'label': 'Prompt SAM3', 'type': 'text',
             'placeholder': 'ex. person, face…'},
        ],
    },
    'converter': {
        'create': _converter_create,
        'start': _converter_start,
        'poll': _converter_poll,
        # le type produit dépend du format demandé → résolu par output_type_fn(params)
        'output_type_fn': lambda params: _category_of_path('x.' + (params.get('output_format') or 'mp4')),
        'params_spec': [
            {'name': 'output_format', 'label': 'Format de sortie', 'type': 'text',
             'placeholder': 'mp3, wav, mp4, webm, png, pdf…'},
            {'name': 'quality_preset', 'label': 'Qualité', 'type': 'select',
             'options': ['fast', 'balanced', 'high'], 'default': 'balanced'},
        ],
    },
    'avatarizer': {
        'create': _avatarizer_create,
        'start': _avatarizer_start,
        'poll': _avatarizer_poll,
        'output_type': 'video',
        'params_spec': [
            {'name': 'avatar_gallery_name', 'label': 'Avatar', 'type': 'select',
             'options_source': 'avatar_gallery'},
            {'name': 'quality_mode', 'label': 'Mode', 'type': 'select',
             'options': ['fast', 'quality'], 'default': 'fast'},
        ],
    },
}


def runner_for(app_id: str):
    return RUNNERS.get(app_id)
