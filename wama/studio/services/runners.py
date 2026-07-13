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
    # 'synthesizer' / 'composer' / 'imager' : BASCULÉS sur le runner GÉNÉRIQUE (2026-07-13)
    #   — entrée PROMPT du contrat + aliases normalisés add_to_* (tool_api, @wraps).
    # 'transcriber' / 'describer' / 'reader' : BASCULÉS sur le runner GÉNÉRIQUE (2026-07-13)
    #   — triades normalisées (item_id) + clé canonique result_text au detail.
    # 'enhancer' : BASCULÉ sur le runner GÉNÉRIQUE (generic_runner.py, 2026-07-13)
    #   — 1re app au contrat normalisé (item_id + detail canonique + params.py pointés).
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


_GENERIC_CACHE = {}


def runner_for(app_id: str):
    from .generic_runner import GENERIC_APPS, build_generic_runner
    if app_id in GENERIC_APPS:
        if app_id not in _GENERIC_CACHE:
            _GENERIC_CACHE[app_id] = build_generic_runner(app_id)
        return _GENERIC_CACHE[app_id]
    return RUNNERS.get(app_id)
