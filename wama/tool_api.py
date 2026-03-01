"""
WAMA Tool API

Python functions (callable directly from the AI agentic loop) + thin HTTP views
for manual testing (curl / browser).

Tools available:
  - list_user_files(user, folder)          → list files in user's media folders
  - add_to_anonymizer(user, file_path, ...) → queue a file in the anonymizer
  - start_anonymizer(user, media_id)        → trigger Celery processing
  - get_anonymizer_status(user)             → current jobs progress
  - sam3_examples()                         → SAM3 text prompt suggestions

HTTP endpoints (login_required, GET/POST JSON):
  GET  /api/tools/list-files/
  POST /api/tools/anonymizer/add/
  POST /api/tools/anonymizer/start/
  GET  /api/tools/anonymizer/status/
  GET  /api/tools/sam3-examples/
"""

import json
import logging
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Folder mapping: logical name → MEDIA_ROOT-relative path template
# ---------------------------------------------------------------------------
_FOLDER_MAP = {
    'temp':      'users/{user_id}/temp',
    'anon_input': 'anonymizer/{user_id}/input',
    'anon_output': 'anonymizer/{user_id}/output',
}

_VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.m4v'}
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
_MEDIA_EXTS = _VIDEO_EXTS | _IMAGE_EXTS


# ===========================================================================
# Python tool functions (called directly from the agentic loop)
# ===========================================================================

def list_user_files(user, folder: str = 'temp') -> dict:
    """
    List media files in one of the user's folders.

    Args:
        user:   Django User instance
        folder: 'temp' | 'anon_input' | 'anon_output'

    Returns:
        {"files": [{"name", "path", "size_mb", "ext"}], "folder": folder}
    """
    template = _FOLDER_MAP.get(folder)
    if template is None:
        available = ', '.join(_FOLDER_MAP.keys())
        return {'error': f"Unknown folder '{folder}'. Available: {available}"}

    rel_dir = template.format(user_id=user.id)
    abs_dir = Path(settings.MEDIA_ROOT) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for f in sorted(abs_dir.rglob('*')):
        if f.is_file() and f.suffix.lower() in _MEDIA_EXTS:
            rel_path = f.relative_to(Path(settings.MEDIA_ROOT))
            files.append({
                'name': f.name,
                'path': str(rel_path).replace('\\', '/'),
                'size_mb': round(f.stat().st_size / 1_048_576, 2),
                'ext': f.suffix.lower(),
            })

    return {'files': files, 'folder': folder, 'count': len(files)}


def add_to_anonymizer(
    user,
    file_path: str,
    use_sam3: bool = False,
    sam3_prompt: str = '',
    classes: list = None,
    precision_level: int = 50,
) -> dict:
    """
    Copy a file into the anonymizer input queue and create a Media DB entry.

    Args:
        user:            Django User instance
        file_path:       Path relative to MEDIA_ROOT  (e.g. "users/1/temp/biovam.mp4")
        use_sam3:        Use SAM3 text-based segmentation
        sam3_prompt:     SAM3 text prompt  (e.g. "all human faces")
        classes:         YOLO detection classes  (default: ['face'])
        precision_level: 0–100 (0=Quick, 50=Balanced, 100=Precise)

    Returns:
        {"media_id": int, "name": str, "status": "queued"} or {"error": str}
    """
    if classes is None:
        classes = ['face']

    # Validate prompt if SAM3 requested
    if use_sam3 and sam3_prompt:
        from wama.anonymizer.utils.sam3_manager import validate_sam3_prompt
        valid, err = validate_sam3_prompt(sam3_prompt)
        if not valid:
            return {'error': f'SAM3 prompt invalide : {err}'}

    # Resolve source path
    src = (Path(settings.MEDIA_ROOT) / file_path).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not str(src).startswith(str(media_root)):
        return {'error': 'Accès refusé : chemin hors de MEDIA_ROOT.'}
    if not src.exists():
        return {'error': f'Fichier introuvable : {file_path}'}
    if src.suffix.lower() not in _MEDIA_EXTS:
        return {'error': f'Format non supporté : {src.suffix}'}

    # Copy to anonymizer input if not already there
    dest_dir = Path(settings.MEDIA_ROOT) / 'anonymizer' / str(user.id) / 'input'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    if src.resolve() != dest.resolve():
        # Avoid name collisions
        stem, suffix = src.stem, src.suffix
        counter = 1
        while dest.exists():
            dest = dest_dir / f'{stem}_{counter}{suffix}'
            counter += 1
        shutil.copy2(str(src), str(dest))

    # Create Media DB entry via anonymizer's process_media()
    try:
        from wama.anonymizer.views import process_media
        result = process_media(str(dest), user)
    except Exception as e:
        return {'error': f'Erreur création Media : {e}'}

    if isinstance(result, str):
        return {'error': result}
    if not result.get('is_valid'):
        return {'error': result.get('error', 'Erreur inconnue')}

    media_id = result['id']

    # Apply anonymizer settings
    from wama.anonymizer.models import Media
    try:
        media = Media.objects.get(pk=media_id)
        media.precision_level = max(0, min(100, int(precision_level)))
        if classes:
            media.classes2blur = classes
        if use_sam3:
            media.use_sam3 = True
            media.sam3_prompt = sam3_prompt or ''
        media.save(update_fields=['precision_level', 'classes2blur', 'use_sam3', 'sam3_prompt'])
    except Exception as e:
        logger.warning(f'[tool_api] Could not update Media #{media_id} settings: {e}')

    return {
        'media_id': media_id,
        'name': result['name'],
        'duration': result.get('duration', ''),
        'status': 'queued',
        'use_sam3': use_sam3,
        'sam3_prompt': sam3_prompt if use_sam3 else None,
    }


def start_anonymizer(user, media_id: int = None) -> dict:
    """
    Trigger Celery processing for a specific media item or all pending items.

    Args:
        user:     Django User instance
        media_id: Process only this job (None = process all pending)

    Returns:
        {"task_id": str, "status": "started", "media_id": int|None}
    """
    from wama.anonymizer.tasks import process_single_media, process_user_media_batch
    from django.core.cache import cache

    if media_id is not None:
        # Validate ownership
        from wama.anonymizer.models import Media
        try:
            media = Media.objects.get(pk=media_id, user=user)
        except Media.DoesNotExist:
            return {'error': f'Media #{media_id} introuvable ou non autorisé.'}

        # Reset processing state
        media.processed = False
        media.blur_progress = 0
        media.save(update_fields=['processed', 'blur_progress'])
        cache.set(f'anon_lock:media:{media_id}', True, timeout=7200)

        task = process_single_media.delay(media_id)
        return {'task_id': task.id, 'status': 'started', 'media_id': media_id}
    else:
        # Batch: reset all pending media and launch batch task
        from wama.anonymizer.models import Media
        pending = Media.objects.filter(user=user, processed=False)
        if not pending.exists():
            return {'error': 'Aucun média en attente de traitement.'}

        pending.update(blur_progress=0)
        for m in pending:
            cache.set(f'anon_lock:media:{m.id}', True, timeout=7200)

        task = process_user_media_batch.delay(user.id)
        return {'task_id': task.id, 'status': 'started', 'media_id': None,
                'count': pending.count()}


def get_anonymizer_status(user) -> dict:
    """
    Return status of the user's current anonymizer jobs (last 10).

    Returns:
        {"jobs": [{"id", "name", "progress", "status", "use_sam3"}]}
    """
    from wama.anonymizer.models import Media
    from django.core.cache import cache

    media_qs = Media.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for m in media_qs:
        # Try to get live progress from cache first
        progress = cache.get(f'anon_progress:{m.id}', m.blur_progress)
        if m.processed:
            status = 'done'
        elif progress > 0:
            status = 'running'
        else:
            status = 'queued'
        jobs.append({
            'id': m.id,
            'name': os.path.basename(m.file.name) if m.file else f'Media #{m.id}',
            'progress': progress,
            'status': status,
            'use_sam3': m.use_sam3,
            'sam3_prompt': m.sam3_prompt if m.use_sam3 else None,
        })
    return {'jobs': jobs}


def sam3_examples() -> dict:
    """
    Return recommended SAM3 text prompt examples.

    Returns:
        {"examples": [str, ...]}
    """
    try:
        from wama.anonymizer.utils.sam3_manager import get_recommended_prompt_examples
        return {'examples': get_recommended_prompt_examples()}
    except Exception as e:
        return {'error': str(e), 'examples': [
            'all human faces',
            'license plates and car registration numbers',
            'computer screens and monitors',
            'all text and written content',
        ]}


# ===========================================================================
# Tool dispatcher (used by the agentic loop in views.py)
# ===========================================================================

TOOL_REGISTRY = {
    'list_user_files':       list_user_files,
    'add_to_anonymizer':     add_to_anonymizer,
    'start_anonymizer':      start_anonymizer,
    'get_anonymizer_status': get_anonymizer_status,
    'sam3_examples':         sam3_examples,
}

# Metadata consumed by GET /api/v1/tools/ — update this when adding a new tool.
TOOL_DESCRIPTIONS = {
    'list_user_files': {
        'description': "Liste les fichiers média de l'utilisateur dans un dossier.",
        'args': {
            'folder': "str — 'temp' | 'anon_input' | 'anon_output'  (défaut: 'temp')",
        },
    },
    'add_to_anonymizer': {
        'description': "Copie un fichier dans la file d'entrée de l'anonymizer et crée l'entrée DB.",
        'args': {
            'file_path':       'str  — chemin relatif à MEDIA_ROOT (valeur "path" de list_user_files)',
            'use_sam3':        'bool — utiliser SAM3 pour la segmentation (défaut: false)',
            'sam3_prompt':     'str  — prompt texte SAM3 (ex: "all human faces")',
            'classes':         'list — classes YOLO à flouter (défaut: ["face"])',
            'precision_level': 'int  — précision 0–100 (0=Rapide, 50=Équilibré, 100=Précis)',
        },
    },
    'start_anonymizer': {
        'description': "Lance le traitement Celery de l'anonymizer pour un ou tous les médias en attente.",
        'args': {
            'media_id': 'int|null — ID retourné par add_to_anonymizer, ou null pour traiter tous',
        },
    },
    'get_anonymizer_status': {
        'description': "Retourne l'état des 10 derniers jobs de l'anonymizer pour l'utilisateur connecté.",
        'args': {},
    },
    'sam3_examples': {
        'description': "Retourne des exemples de prompts texte recommandés pour SAM3.",
        'args': {},
    },
}


def execute_tool(tool_name: str, args: dict, user) -> dict:
    """
    Dispatch a tool call from the agentic loop.

    Args:
        tool_name: Name of the tool to call
        args:      Arguments dict from the LLM
        user:      Django User instance

    Returns:
        Tool result dict (always a dict, never raises)
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        available = ', '.join(TOOL_REGISTRY.keys())
        return {'error': f"Outil inconnu : '{tool_name}'. Disponibles : {available}"}

    try:
        # Tools that don't take a user argument
        if tool_name == 'sam3_examples':
            return fn()
        return fn(user=user, **args)
    except TypeError as e:
        return {'error': f"Mauvais arguments pour '{tool_name}' : {e}"}
    except Exception as e:
        logger.error(f'[tool_api] execute_tool({tool_name}) error: {e}', exc_info=True)
        return {'error': str(e)}


# ===========================================================================
# HTTP views (for manual testing with curl or browser)
# ===========================================================================

@login_required
@require_GET
def list_user_files_view(request):
    folder = request.GET.get('folder', 'temp')
    return JsonResponse(list_user_files(request.user, folder=folder))


@login_required
@require_POST
def add_to_anonymizer_view(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    result = add_to_anonymizer(
        user=request.user,
        file_path=data.get('file_path', ''),
        use_sam3=bool(data.get('use_sam3', False)),
        sam3_prompt=data.get('sam3_prompt', ''),
        classes=data.get('classes', ['face']),
        precision_level=int(data.get('precision_level', 50)),
    )
    status_code = 400 if 'error' in result else 200
    return JsonResponse(result, status=status_code)


@login_required
@require_POST
def start_anonymizer_view(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    media_id = data.get('media_id')
    if media_id is not None:
        try:
            media_id = int(media_id)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'media_id doit être un entier'}, status=400)

    result = start_anonymizer(user=request.user, media_id=media_id)
    status_code = 400 if 'error' in result else 200
    return JsonResponse(result, status=status_code)


@login_required
@require_GET
def get_anonymizer_status_view(request):
    return JsonResponse(get_anonymizer_status(request.user))


@login_required
@require_GET
def sam3_examples_view(request):
    return JsonResponse(sam3_examples())
