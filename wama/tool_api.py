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
# File extension sets
# ---------------------------------------------------------------------------
_VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.m4v'}
_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif'}
_AUDIO_EXTS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a'}
_MEDIA_EXTS = _VIDEO_EXTS | _IMAGE_EXTS | _AUDIO_EXTS

# Describer: all accepted extensions → detected content type
_DESCRIBER_EXTS = (
    _IMAGE_EXTS
    | _VIDEO_EXTS
    | _AUDIO_EXTS
    | {'.txt', '.pdf', '.docx', '.md', '.csv'}
)
_DESCRIBER_TYPE_MAP = {
    **{ext: 'image' for ext in _IMAGE_EXTS},
    **{ext: 'video' for ext in _VIDEO_EXTS},
    **{ext: 'audio' for ext in _AUDIO_EXTS},
    '.txt': 'text', '.md': 'text', '.docx': 'text', '.csv': 'text',
    '.pdf': 'pdf',
}

# Transcriber: audio + video
_TRANSCRIBER_EXTS = _AUDIO_EXTS | _VIDEO_EXTS

# ---------------------------------------------------------------------------
# Folder mapping: logical name → MEDIA_ROOT-relative path template
# ---------------------------------------------------------------------------
_FOLDER_MAP = {
    'temp':               'users/{user_id}/temp',
    'anon_input':         'anonymizer/{user_id}/input',
    'anon_output':        'anonymizer/{user_id}/output',
    'transcriber_input':  'transcriber/{user_id}/input',
    'describer_input':    'describer/{user_id}/input',
}


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
        {"jobs": [{"id", "name", "progress", "status", "use_sam3", "output_url"}]}
    """
    from wama.anonymizer.models import Media
    from wama.anonymizer.utils.media_utils import get_blurred_media_path
    from django.conf import settings
    from django.core.cache import cache

    media_qs = Media.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for m in media_qs:
        progress = cache.get(f'anon_progress:{m.id}', m.blur_progress)
        if m.processed:
            status = 'done'
        elif progress > 0:
            status = 'running'
        else:
            status = 'queued'

        output_url = None
        if m.processed and m.file:
            try:
                import glob as _glob
                # Output file is named {base}_blurred_{model_suffix}{ext}
                # Scan output dir for any matching file since suffix varies by model
                base = os.path.splitext(os.path.basename(m.file.name))[0]
                ext_lower = m.file_ext.lower()
                out_ext = '.mp4' if ext_lower in ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv') else ext_lower
                out_dir = get_blurred_media_path(m.file.name, m.file_ext, m.user_id)
                # get_blurred_media_path returns a full path; use its parent as output dir
                out_dir = os.path.dirname(out_dir)
                pattern = os.path.join(out_dir, f"{base}_blurred*{out_ext}")
                matches = _glob.glob(pattern)
                if matches:
                    rel = os.path.relpath(matches[0], settings.MEDIA_ROOT)
                    output_url = settings.MEDIA_URL + rel.replace(os.sep, '/')
            except Exception:
                pass

        jobs.append({
            'id': m.id,
            'name': os.path.basename(m.file.name) if m.file else f'Media #{m.id}',
            'progress': progress,
            'status': status,
            'use_sam3': m.use_sam3,
            'sam3_prompt': m.sam3_prompt if m.use_sam3 else None,
            'output_url': output_url,
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
# Imager tools
# ===========================================================================

def create_image(
    user,
    prompt: str,
    model: str = 'hunyuan-image-2.1',
    width: int = 512,
    height: int = 512,
    steps: int = 30,
    guidance_scale: float = 7.5,
    negative_prompt: str = '',
    seed: int = None,
    num_images: int = 1,
) -> dict:
    """
    Create a txt2img generation job (status: PENDING).

    Args:
        user:            Django User instance
        prompt:          Text prompt for generation (required)
        model:           Model name (e.g. 'hunyuan-image-2.1', 'stable-diffusion-xl')
        width:           Output width in pixels (256–2048)
        height:          Output height in pixels (256–2048)
        steps:           Diffusion steps (1–100, default 30)
        guidance_scale:  Guidance scale (1.0–20.0, default 7.5)
        negative_prompt: What to avoid in the image
        seed:            Random seed for reproducibility (None = random)
        num_images:      Number of images to generate (1–4)

    Returns:
        {"generation_id": int, "status": "pending", "model": str, "prompt": str}
    """
    if not prompt.strip():
        return {'error': 'Le prompt est requis.'}

    num_images = max(1, min(4, int(num_images)))
    steps = max(1, min(100, int(steps)))
    guidance_scale = max(1.0, min(20.0, float(guidance_scale)))
    width = max(256, min(2048, int(width)))
    height = max(256, min(2048, int(height)))

    try:
        from wama.imager.models import ImageGeneration
        generation = ImageGeneration.objects.create(
            user=user,
            generation_mode='txt2img',
            prompt=prompt.strip(),
            negative_prompt=negative_prompt.strip(),
            model=model,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance_scale,
            seed=seed if seed else None,
            num_images=num_images,
            status='PENDING',
        )
    except Exception as e:
        return {'error': f'Erreur création ImageGeneration : {e}'}

    return {
        'generation_id': generation.id,
        'status': 'pending',
        'model': model,
        'prompt': prompt,
        'width': width,
        'height': height,
        'steps': steps,
        'num_images': num_images,
    }


def start_imager(user, generation_id: int = None) -> dict:
    """
    Launch Celery image generation task(s).

    Args:
        user:          Django User instance
        generation_id: Specific job to start (None = all PENDING jobs)

    Returns:
        {"task_id": str, "status": "started", ...}
    """
    from wama.imager.models import ImageGeneration
    from wama.imager.tasks import generate_image_task
    from django.core.cache import cache

    if generation_id is not None:
        try:
            generation = ImageGeneration.objects.get(pk=generation_id, user=user)
        except ImageGeneration.DoesNotExist:
            return {'error': f'Generation #{generation_id} introuvable ou non autorisée.'}

        if generation.status == 'RUNNING':
            return {'error': f'Generation #{generation_id} est déjà en cours.'}

        generation.status = 'PENDING'
        generation.progress = 0
        generation.error_message = ''
        generation.save(update_fields=['status', 'progress', 'error_message'])
        cache.delete(f'imager_progress_{generation_id}')

        task = generate_image_task.delay(generation.id)
        generation.status = 'RUNNING'
        generation.task_id = task.id
        generation.save(update_fields=['status', 'task_id'])

        return {'task_id': task.id, 'status': 'started', 'generation_id': generation_id}

    else:
        pending = ImageGeneration.objects.filter(user=user, status='PENDING')
        if not pending.exists():
            return {'error': 'Aucune génération en attente.'}

        started = []
        for gen in pending:
            cache.delete(f'imager_progress_{gen.id}')
            task = generate_image_task.delay(gen.id)
            gen.status = 'RUNNING'
            gen.task_id = task.id
            gen.save(update_fields=['status', 'task_id'])
            started.append(gen.id)

        return {'status': 'started', 'generation_id': None, 'count': len(started), 'ids': started}


def get_imager_status(user) -> dict:
    """
    Return status of the user's recent image generation jobs (last 10).

    Returns:
        {"jobs": [{"id", "prompt", "model", "status", "progress", "num_images", "images"}]}
    """
    from wama.imager.models import ImageGeneration
    from django.core.cache import cache

    jobs_qs = ImageGeneration.objects.filter(
        user=user,
        parent_generation__isnull=True,
    ).order_by('-id')[:10]

    jobs = []
    for gen in jobs_qs:
        cached_progress = cache.get(f'imager_progress_{gen.id}')
        progress = cached_progress if cached_progress is not None else gen.progress
        output_urls = gen.output_images if gen.status == 'SUCCESS' else []
        video_url = gen.output_video.url if (gen.status == 'SUCCESS' and gen.output_video) else None
        jobs.append({
            'id': gen.id,
            'prompt': gen.prompt[:80] + ('…' if len(gen.prompt) > 80 else ''),
            'model': gen.model,
            'status': gen.status,
            'progress': progress,
            'num_images': gen.num_images,
            'output_urls': output_urls,
            'video_url': video_url,
        })
    return {'jobs': jobs}


# ===========================================================================
# Enhancer tools
# ===========================================================================

_ENHANCER_VALID_MODELS = {
    'RealESR_Gx4', 'RealESR_Animex4', 'BSRGANx2',
    'BSRGANx4', 'RealESRGANx4', 'IRCNN_Mx1', 'IRCNN_Lx1',
}


def add_to_enhancer(
    user,
    file_path: str,
    ai_model: str = 'RealESR_Gx4',
    denoise: bool = False,
    blend_factor: float = 0.0,
) -> dict:
    """
    Register a file for enhancement and create the Enhancement DB entry.

    Args:
        user:         Django User instance
        file_path:    Path relative to MEDIA_ROOT (from list_user_files)
        ai_model:     Upscaling model (default: 'RealESR_Gx4')
        denoise:      Apply denoising before upscaling (default: False)
        blend_factor: 0.0 = full AI, 1.0 = original (default: 0.0)

    Returns:
        {"enhancement_id": int, "name": str, "media_type": str, "status": "pending"}
    """
    if ai_model not in _ENHANCER_VALID_MODELS:
        return {'error': f"Modèle inconnu : '{ai_model}'. Disponibles : {', '.join(sorted(_ENHANCER_VALID_MODELS))}"}

    blend_factor = max(0.0, min(1.0, float(blend_factor)))

    # Resolve and validate source file
    src = (Path(settings.MEDIA_ROOT) / file_path).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not str(src).startswith(str(media_root)):
        return {'error': 'Accès refusé : chemin hors de MEDIA_ROOT.'}
    if not src.exists():
        return {'error': f'Fichier introuvable : {file_path}'}

    ext = src.suffix.lower()
    if ext in _IMAGE_EXTS:
        media_type = 'image'
    elif ext in _VIDEO_EXTS:
        media_type = 'video'
    else:
        return {'error': f'Format non supporté pour l\'enhancer : {ext}'}

    try:
        from django.core.files import File
        from wama.enhancer.models import Enhancement
        from wama.common.utils.video_utils import get_media_info

        with open(str(src), 'rb') as f:
            django_file = File(f, name=src.name)
            enhancement = Enhancement.objects.create(
                user=user,
                media_type=media_type,
                input_file=django_file,
                ai_model=ai_model,
                denoise=bool(denoise),
                blend_factor=blend_factor,
                status='PENDING',
            )

        # Analyse dimensions / durée
        try:
            info = get_media_info(enhancement.input_file.path)
            enhancement.width     = info.get('width', 0)
            enhancement.height    = info.get('height', 0)
            enhancement.duration  = info.get('duration', 0)
            enhancement.file_size = info.get('file_size', 0)
            enhancement.save(update_fields=['width', 'height', 'duration', 'file_size'])
        except Exception as e:
            logger.warning(f'[tool_api] add_to_enhancer analyze failed: {e}')

    except Exception as e:
        return {'error': f'Erreur création Enhancement : {e}'}

    return {
        'enhancement_id': enhancement.id,
        'name': src.name,
        'media_type': media_type,
        'ai_model': ai_model,
        'status': 'pending',
    }


def start_enhancer(user, enhancement_id: int = None) -> dict:
    """
    Launch Celery enhancement task(s).

    Args:
        user:            Django User instance
        enhancement_id:  Specific job to start (None = all PENDING jobs)

    Returns:
        {"task_id": str, "status": "started", ...}
    """
    from wama.enhancer.models import Enhancement
    from wama.enhancer.tasks import enhance_media
    from django.core.cache import cache

    if enhancement_id is not None:
        try:
            enh = Enhancement.objects.get(pk=enhancement_id, user=user)
        except Enhancement.DoesNotExist:
            return {'error': f'Enhancement #{enhancement_id} introuvable ou non autorisé.'}

        if enh.status == 'RUNNING':
            return {'error': f'Enhancement #{enhancement_id} est déjà en cours.'}

        enh.status = 'PENDING'
        enh.progress = 0
        enh.error_message = ''
        enh.save(update_fields=['status', 'progress', 'error_message'])
        cache.delete(f'enhancer_progress_{enhancement_id}')

        task = enhance_media.delay(enh.id)
        enh.status = 'RUNNING'
        enh.task_id = task.id
        enh.save(update_fields=['status', 'task_id'])

        return {'task_id': task.id, 'status': 'started', 'enhancement_id': enhancement_id}

    else:
        pending = Enhancement.objects.filter(user=user, status='PENDING')
        if not pending.exists():
            return {'error': 'Aucun enhancement en attente.'}

        started = []
        for enh in pending:
            cache.delete(f'enhancer_progress_{enh.id}')
            task = enhance_media.delay(enh.id)
            enh.status = 'RUNNING'
            enh.task_id = task.id
            enh.save(update_fields=['status', 'task_id'])
            started.append(enh.id)

        return {'status': 'started', 'enhancement_id': None, 'count': len(started), 'ids': started}


def get_enhancer_status(user) -> dict:
    """
    Return status of the user's recent enhancement jobs (last 10).

    Returns:
        {"jobs": [{"id", "name", "media_type", "ai_model", "status", "progress"}]}
    """
    from wama.enhancer.models import Enhancement
    from django.core.cache import cache

    jobs_qs = Enhancement.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for enh in jobs_qs:
        cached = cache.get(f'enhancer_progress_{enh.id}')
        progress = cached if cached is not None else enh.progress
        output_url = enh.output_file.url if enh.output_file else None
        jobs.append({
            'id': enh.id,
            'name': enh.get_input_filename(),
            'media_type': enh.media_type,
            'ai_model': enh.ai_model,
            'status': enh.status,
            'progress': progress,
            'output_url': output_url,
        })
    return {'jobs': jobs}


# ===========================================================================
# Audio Enhancer tools
# ===========================================================================

_AUDIO_ENHANCER_ENGINES = {'resemble', 'deepfilternet'}
_AUDIO_ENHANCER_MODES = {'both', 'denoise', 'enhance'}
_AUDIO_ENHANCER_EXTS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma'}


def add_to_audio_enhancer(
    user,
    file_path: str,
    engine: str = 'resemble',
    mode: str = 'both',
    denoising_strength: float = 0.5,
    quality: int = 64,
) -> dict:
    """
    Register an audio file for speech enhancement.

    Args:
        user:               Django User instance
        file_path:          Path relative to MEDIA_ROOT (from list_user_files)
        engine:             'resemble' (quality) | 'deepfilternet' (speed)
        mode:               'both' | 'denoise' | 'enhance'  (Resemble only)
        denoising_strength: 0.0–1.0 denoising amount (Resemble only, default 0.5)
        quality:            NFE steps 32/64/128 (Resemble only, default 64)

    Returns:
        {"audio_enhancement_id": int, "name": str, "status": "pending"}
    """
    if engine not in _AUDIO_ENHANCER_ENGINES:
        return {'error': f"Moteur inconnu : '{engine}'. Disponibles : resemble, deepfilternet"}
    if mode not in _AUDIO_ENHANCER_MODES:
        return {'error': f"Mode inconnu : '{mode}'. Disponibles : both, denoise, enhance"}

    denoising_strength = max(0.0, min(1.0, float(denoising_strength)))
    quality = max(32, min(128, int(quality)))

    src = (Path(settings.MEDIA_ROOT) / file_path).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not str(src).startswith(str(media_root)):
        return {'error': 'Accès refusé : chemin hors de MEDIA_ROOT.'}
    if not src.exists():
        return {'error': f'Fichier introuvable : {file_path}'}
    if src.suffix.lower() not in _AUDIO_ENHANCER_EXTS:
        return {'error': f'Format audio non supporté : {src.suffix}. Formats acceptés : {", ".join(sorted(_AUDIO_ENHANCER_EXTS))}'}

    try:
        from django.core.files import File
        from wama.enhancer.models import AudioEnhancement

        with open(str(src), 'rb') as f:
            django_file = File(f, name=src.name)
            ae = AudioEnhancement.objects.create(
                user=user,
                input_file=django_file,
                file_size=src.stat().st_size,
                engine=engine,
                mode=mode,
                denoising_strength=denoising_strength,
                quality=quality,
                status='PENDING',
            )
    except Exception as e:
        return {'error': f'Erreur création AudioEnhancement : {e}'}

    return {
        'audio_enhancement_id': ae.id,
        'name': src.name,
        'engine': engine,
        'mode': mode,
        'status': 'pending',
    }


def start_audio_enhancer(user, audio_enhancement_id: int = None) -> dict:
    """
    Launch Celery audio enhancement task(s).

    Args:
        user:                  Django User instance
        audio_enhancement_id:  Specific job to start (None = all PENDING jobs)

    Returns:
        {"task_id": str, "status": "started", ...}
    """
    from wama.enhancer.models import AudioEnhancement
    from wama.enhancer.tasks import enhance_audio
    from django.core.cache import cache

    if audio_enhancement_id is not None:
        try:
            ae = AudioEnhancement.objects.get(pk=audio_enhancement_id, user=user)
        except AudioEnhancement.DoesNotExist:
            return {'error': f'AudioEnhancement #{audio_enhancement_id} introuvable ou non autorisé.'}

        if ae.status == 'RUNNING':
            return {'error': f'AudioEnhancement #{audio_enhancement_id} est déjà en cours.'}

        ae.status = 'PENDING'
        ae.progress = 0
        ae.error_message = ''
        ae.save(update_fields=['status', 'progress', 'error_message'])
        cache.delete(f'audio_enhancer_progress_{audio_enhancement_id}')

        task = enhance_audio.delay(ae.id)
        ae.status = 'RUNNING'
        ae.task_id = task.id
        ae.save(update_fields=['status', 'task_id'])

        return {'task_id': task.id, 'status': 'started', 'audio_enhancement_id': audio_enhancement_id}

    else:
        pending = AudioEnhancement.objects.filter(user=user, status='PENDING')
        if not pending.exists():
            return {'error': 'Aucun audio enhancement en attente.'}

        started = []
        for ae in pending:
            cache.delete(f'audio_enhancer_progress_{ae.id}')
            task = enhance_audio.delay(ae.id)
            ae.status = 'RUNNING'
            ae.task_id = task.id
            ae.save(update_fields=['status', 'task_id'])
            started.append(ae.id)

        return {'status': 'started', 'audio_enhancement_id': None, 'count': len(started), 'ids': started}


def get_audio_enhancer_status(user) -> dict:
    """
    Return status of the user's recent audio enhancement jobs (last 10).

    Returns:
        {"jobs": [{"id", "name", "engine", "mode", "status", "progress"}]}
    """
    from wama.enhancer.models import AudioEnhancement
    from django.core.cache import cache

    jobs_qs = AudioEnhancement.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for ae in jobs_qs:
        cached = cache.get(f'audio_enhancer_progress_{ae.id}')
        progress = cached if cached is not None else ae.progress
        output_url = ae.output_file.url if ae.output_file else None
        jobs.append({
            'id': ae.id,
            'name': ae.get_input_filename(),
            'engine': ae.engine,
            'mode': ae.mode,
            'status': ae.status,
            'progress': progress,
            'output_url': output_url,
        })
    return {'jobs': jobs}


# ===========================================================================
# Synthesizer tools
# ===========================================================================

def synthesize_text(
    user,
    text: str,
    language: str = 'fr',
    tts_model: str = 'xtts_v2',
    voice_preset: str = 'default',
    speed: float = 1.0,
    pitch: float = 1.0,
    emotion_intensity: float = 1.0,
) -> dict:
    """
    Create a VoiceSynthesis job from raw text.

    Args:
        user:              Django User instance
        text:              Text to synthesize (required)
        language:          Language code (e.g. 'fr', 'en', 'es')
        tts_model:         TTS model ('xtts_v2', 'higgs_audio_v2', etc.)
        voice_preset:      Voice preset key ('default', 'male_1', 'female_1', etc.)
        speed:             Speech speed 0.5–2.0 (default: 1.0)
        pitch:             Voice pitch 0.5–2.0 (default: 1.0)
        emotion_intensity: Emotional intensity 0.0–2.0 (default: 1.0)

    Returns:
        {"synthesis_id": int, "word_count": int, "duration_display": str, "status": "pending"}
    """
    import re as _re
    text = text.strip()
    if not text:
        return {'error': 'Le texte est vide.'}

    speed = max(0.5, min(2.0, float(speed)))
    pitch = max(0.5, min(2.0, float(pitch)))
    emotion_intensity = max(0.0, min(2.0, float(emotion_intensity)))

    # Build a safe filename from the first few words
    words = text.split()
    safe_title = _re.sub(r'[^\w\s-]', '', ' '.join(words[:5]))[:50].strip()
    filename = f"{safe_title or 'synthesizer'}.txt"

    try:
        from django.core.files.base import ContentFile
        from wama.synthesizer.models import VoiceSynthesis

        txt_file = ContentFile(text.encode('utf-8'), name=filename)

        synthesis = VoiceSynthesis.objects.create(
            user=user,
            text_file=txt_file,
            tts_model=tts_model,
            language=language,
            voice_preset=voice_preset,
            speed=speed,
            pitch=pitch,
            emotion_intensity=emotion_intensity,
        )

        # Extract text and compute metadata
        try:
            from wama.synthesizer.utils.text_extractor import extract_text_from_file, clean_text_for_tts
            extracted = extract_text_from_file(synthesis.text_file.path)
            synthesis.text_content = clean_text_for_tts(extracted)
        except Exception:
            synthesis.text_content = text

        synthesis.update_metadata()

        # Wrap in a batch-of-1 so it appears correctly in the unified queue
        try:
            from wama.synthesizer.models import BatchSynthesis, BatchSynthesisItem
            import os as _os
            stem = _os.path.splitext(_os.path.basename(synthesis.text_file.name))[0]
            batch = BatchSynthesis.objects.create(user=user, total=1)
            BatchSynthesisItem.objects.create(
                batch=batch, synthesis=synthesis,
                output_filename=stem + '.wav', row_index=0,
            )
        except Exception:
            pass

    except Exception as e:
        return {'error': f'Erreur création VoiceSynthesis : {e}'}

    return {
        'synthesis_id': synthesis.id,
        'word_count': synthesis.word_count,
        'duration_display': synthesis.duration_display or '—',
        'status': 'pending',
        'model': tts_model,
        'language': language,
        'voice_preset': voice_preset,
    }


def start_synthesizer(user, synthesis_id: int = None) -> dict:
    """
    Launch Celery synthesis task(s).

    Args:
        user:          Django User instance
        synthesis_id:  Specific job to start (None = all PENDING jobs)

    Returns:
        {"task_id": str, "status": "started", ...}
    """
    from wama.synthesizer.models import VoiceSynthesis
    from wama.synthesizer.workers import synthesize_voice
    from django.core.cache import cache

    if synthesis_id is not None:
        try:
            synthesis = VoiceSynthesis.objects.get(pk=synthesis_id, user=user)
        except VoiceSynthesis.DoesNotExist:
            return {'error': f'Synthesis #{synthesis_id} introuvable ou non autorisée.'}

        if synthesis.status == 'RUNNING':
            return {'error': f'Synthesis #{synthesis_id} est déjà en cours.'}

        synthesis.status = 'PENDING'
        synthesis.progress = 0
        synthesis.error_message = ''
        if synthesis.audio_output:
            try:
                synthesis.audio_output.delete(save=False)
            except Exception:
                pass
        synthesis.save(update_fields=['status', 'progress', 'error_message', 'audio_output'])
        cache.set(f'synthesizer_progress_{synthesis.id}', 0, timeout=3600)

        task = synthesize_voice.delay(synthesis.id)
        synthesis.task_id = task.id
        synthesis.status = 'RUNNING'
        synthesis.save(update_fields=['task_id', 'status'])

        return {'task_id': task.id, 'status': 'started', 'synthesis_id': synthesis_id}

    else:
        pending = VoiceSynthesis.objects.filter(user=user, status='PENDING')
        if not pending.exists():
            return {'error': 'Aucune synthèse en attente.'}

        started = []
        for synth in pending:
            cache.set(f'synthesizer_progress_{synth.id}', 0, timeout=3600)
            task = synthesize_voice.delay(synth.id)
            synth.task_id = task.id
            synth.status = 'RUNNING'
            synth.save(update_fields=['task_id', 'status'])
            started.append(synth.id)

        return {'status': 'started', 'synthesis_id': None, 'count': len(started), 'ids': started}


def get_synthesizer_status(user) -> dict:
    """
    Return status of the user's recent synthesis jobs (last 10).

    Returns:
        {"jobs": [{"id", "filename", "word_count", "duration_display", "model",
                   "language", "voice_preset", "status", "progress", "audio_url"}]}
    """
    from wama.synthesizer.models import VoiceSynthesis
    from django.core.cache import cache

    jobs_qs = VoiceSynthesis.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for synth in jobs_qs:
        cached = cache.get(f'synthesizer_progress_{synth.id}')
        progress = cached if cached is not None else (synth.progress or 0)
        jobs.append({
            'id': synth.id,
            'filename': synth.filename,
            'word_count': synth.word_count,
            'duration_display': synth.duration_display or '—',
            'model': synth.tts_model,
            'language': synth.language,
            'voice_preset': synth.voice_preset,
            'status': synth.status,
            'progress': progress,
            'audio_url': synth.audio_output.url if synth.audio_output else None,
        })
    return {'jobs': jobs}


# ===========================================================================
# Describer tools
# ===========================================================================

def add_to_describer(
    user,
    file_path: str,
    output_format: str = 'detailed',
    output_language: str = 'fr',
    max_length: int = 500,
) -> dict:
    """
    Copy a file into the describer queue and create a Description DB entry.

    Args:
        user:            Django User instance
        file_path:       Path relative to MEDIA_ROOT (from list_user_files)
        output_format:   'summary' | 'detailed' | 'scientific' | 'bullet_points'
        output_language: 'fr' | 'en' | 'auto'
        max_length:      Maximum length of result in words (default: 500)

    Returns:
        {"description_id": int, "filename": str, "detected_type": str, "status": "pending"}
    """
    valid_formats = {'summary', 'detailed', 'scientific', 'bullet_points'}
    if output_format not in valid_formats:
        return {'error': f"Format invalide : '{output_format}'. Disponibles : {', '.join(sorted(valid_formats))}"}

    src = (Path(settings.MEDIA_ROOT) / file_path).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not str(src).startswith(str(media_root)):
        return {'error': 'Accès refusé : chemin hors de MEDIA_ROOT.'}
    if not src.exists():
        return {'error': f'Fichier introuvable : {file_path}'}

    ext = src.suffix.lower()
    if ext not in _DESCRIBER_EXTS:
        return {'error': f'Format non supporté par le Describer : {ext}'}

    detected_type = _DESCRIBER_TYPE_MAP.get(ext, 'auto')

    try:
        from django.core.files import File
        from wama.describer.models import Description

        with open(str(src), 'rb') as f:
            django_file = File(f, name=src.name)
            description = Description.objects.create(
                user=user,
                input_file=django_file,
                filename=src.name,
                file_size=src.stat().st_size,
                detected_type=detected_type,
                output_format=output_format,
                output_language=output_language,
                max_length=int(max_length),
            )
    except Exception as e:
        return {'error': f'Erreur création Description : {e}'}

    return {
        'description_id': description.id,
        'filename': src.name,
        'detected_type': detected_type,
        'output_format': output_format,
        'output_language': output_language,
        'status': 'pending',
    }


def start_describer(user, description_id: int = None) -> dict:
    """
    Launch Celery description task(s).

    Args:
        user:           Django User instance
        description_id: Specific job to start (None = all PENDING jobs)

    Returns:
        {"task_id": str, "status": "started", ...}
    """
    from wama.describer.models import Description
    from wama.describer.workers import describe_content
    from django.core.cache import cache

    if description_id is not None:
        try:
            description = Description.objects.get(pk=description_id, user=user)
        except Description.DoesNotExist:
            return {'error': f'Description #{description_id} introuvable ou non autorisée.'}

        if description.status == 'RUNNING':
            return {'error': f'Description #{description_id} est déjà en cours.'}

        description.status = 'RUNNING'
        description.progress = 0
        description.error_message = ''
        description.result_text = ''
        description.save(update_fields=['status', 'progress', 'error_message', 'result_text'])
        cache.delete(f'describer_progress_{description_id}')
        cache.delete(f'describer_partial_{description_id}')

        task = describe_content.delay(description.id)
        description.task_id = task.id
        description.save(update_fields=['task_id'])

        return {'task_id': task.id, 'status': 'started', 'description_id': description_id}

    else:
        pending = Description.objects.filter(user=user, status='PENDING')
        if not pending.exists():
            return {'error': 'Aucune description en attente.'}

        started = []
        for desc in pending:
            cache.delete(f'describer_progress_{desc.id}')
            desc.status = 'RUNNING'
            desc.progress = 0
            desc.result_text = ''
            desc.save(update_fields=['status', 'progress', 'result_text'])
            task = describe_content.delay(desc.id)
            desc.task_id = task.id
            desc.save(update_fields=['task_id'])
            started.append(desc.id)

        return {'status': 'started', 'description_id': None, 'count': len(started), 'ids': started}


def get_describer_status(user) -> dict:
    """
    Return status of the user's recent description jobs (last 10).

    Returns:
        {"jobs": [{"id", "filename", "detected_type", "output_format", "status",
                   "progress", "result_preview"}]}
    """
    from wama.describer.models import Description
    from django.core.cache import cache

    jobs_qs = Description.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for desc in jobs_qs:
        cached = cache.get(f'describer_progress_{desc.id}')
        progress = cached if cached is not None else desc.progress
        partial = cache.get(f'describer_partial_{desc.id}', '')
        result_preview = None
        if desc.result_text:
            result_preview = (desc.result_text[:300] + '…') if len(desc.result_text) > 300 else desc.result_text
        elif partial:
            result_preview = (partial[:300] + '…') if len(partial) > 300 else partial

        jobs.append({
            'id': desc.id,
            'filename': desc.filename or desc.input_filename,
            'detected_type': desc.detected_type,
            'output_format': desc.output_format,
            'output_language': desc.output_language,
            'status': desc.status,
            'progress': progress,
            'result_preview': result_preview,
        })
    return {'jobs': jobs}


# ===========================================================================
# Transcriber tools
# ===========================================================================

def add_to_transcriber(
    user,
    file_path: str,
    backend: str = 'auto',
    preprocess_audio: bool = False,
    hotwords: str = '',
    enable_diarization: bool = True,
) -> dict:
    """
    Copy a file into the transcriber queue and create a Transcript DB entry.

    Args:
        user:               Django User instance
        file_path:          Path relative to MEDIA_ROOT (audio or video file)
        backend:            'auto' | 'whisper' | 'vibevoice'
        preprocess_audio:   Apply audio preprocessing before transcription
        hotwords:           Domain-specific terms to improve recognition
        enable_diarization: Enable speaker diarization (VibeVoice only)

    Returns:
        {"transcript_id": int, "filename": str, "duration_display": str, "status": "pending"}
    """
    src = (Path(settings.MEDIA_ROOT) / file_path).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not str(src).startswith(str(media_root)):
        return {'error': 'Accès refusé : chemin hors de MEDIA_ROOT.'}
    if not src.exists():
        return {'error': f'Fichier introuvable : {file_path}'}

    ext = src.suffix.lower()
    if ext not in _TRANSCRIBER_EXTS:
        exts_str = ', '.join(sorted(_TRANSCRIBER_EXTS))
        return {'error': f'Format non supporté par le Transcriber : {ext}. Formats acceptés : {exts_str}'}

    try:
        from django.core.files import File
        from wama.transcriber.models import Transcript

        with open(str(src), 'rb') as f:
            django_file = File(f, name=src.name)
            transcript = Transcript.objects.create(
                user=user,
                audio=django_file,
                backend=backend,
                preprocess_audio=bool(preprocess_audio),
                hotwords=hotwords or '',
                enable_diarization=bool(enable_diarization),
            )

        # Populate duration / properties via ffprobe
        try:
            from wama.transcriber.views import _describe_audio
            _describe_audio(transcript)
        except Exception:
            pass

    except Exception as e:
        return {'error': f'Erreur création Transcript : {e}'}

    return {
        'transcript_id': transcript.id,
        'filename': transcript.filename,
        'duration_display': transcript.duration_display or '—',
        'properties': transcript.properties or '—',
        'backend': backend,
        'preprocess_audio': preprocess_audio,
        'status': 'pending',
    }


def start_transcriber(user, transcript_id: int = None) -> dict:
    """
    Launch Celery transcription task(s).

    Args:
        user:          Django User instance
        transcript_id: Specific job to start (None = all PENDING jobs)

    Returns:
        {"task_id": str, "status": "started", ...}
    """
    from wama.transcriber.models import Transcript, TranscriptSegment
    from wama.transcriber.workers import transcribe, transcribe_without_preprocessing
    from django.core.cache import cache

    if transcript_id is not None:
        try:
            t = Transcript.objects.get(pk=transcript_id, user=user)
        except Transcript.DoesNotExist:
            return {'error': f'Transcript #{transcript_id} introuvable ou non autorisé.'}

        if t.status == 'RUNNING':
            return {'error': f'Transcript #{transcript_id} est déjà en cours.'}

        t.status = 'PENDING'
        t.progress = 0
        t.text = ''
        t.language = ''
        t.used_backend = ''
        t.save()
        TranscriptSegment.objects.filter(transcript=t).delete()
        cache.set(f'transcriber_progress_{t.id}', 0, timeout=3600)

        task = transcribe.delay(t.id) if t.preprocess_audio else transcribe_without_preprocessing.delay(t.id)
        t.task_id = task.id
        t.status = 'RUNNING'
        t.save()

        return {'task_id': task.id, 'status': 'started', 'transcript_id': transcript_id}

    else:
        pending = Transcript.objects.filter(user=user, status='PENDING')
        if not pending.exists():
            return {'error': 'Aucune transcription en attente.'}

        started = []
        for t in pending:
            TranscriptSegment.objects.filter(transcript=t).delete()
            cache.set(f'transcriber_progress_{t.id}', 0, timeout=3600)
            task = transcribe.delay(t.id) if t.preprocess_audio else transcribe_without_preprocessing.delay(t.id)
            t.task_id = task.id
            t.status = 'RUNNING'
            t.save()
            started.append(t.id)

        return {'status': 'started', 'transcript_id': None, 'count': len(started), 'ids': started}


def get_transcriber_status(user) -> dict:
    """
    Return status of the user's recent transcription jobs (last 10).

    Returns:
        {"jobs": [{"id", "filename", "duration_display", "backend", "used_backend",
                   "language", "status", "progress", "text_preview"}]}
    """
    from wama.transcriber.models import Transcript
    from django.core.cache import cache

    jobs_qs = Transcript.objects.filter(user=user).order_by('-id')[:10]
    jobs = []
    for t in jobs_qs:
        cached = cache.get(f'transcriber_progress_{t.id}')
        progress = cached if cached is not None else t.progress
        partial = cache.get(f'transcriber_partial_text_{t.id}', '')
        text_preview = None
        if t.text:
            text_preview = (t.text[:300] + '…') if len(t.text) > 300 else t.text
        elif partial:
            text_preview = (partial[:300] + '…') if len(partial) > 300 else partial

        jobs.append({
            'id': t.id,
            'filename': t.filename,
            'duration_display': t.duration_display or '—',
            'backend': t.backend,
            'used_backend': t.used_backend or None,
            'language': t.language or None,
            'status': t.status,
            'progress': progress,
            'text_preview': text_preview,
        })
    return {'jobs': jobs}


# ===========================================================================
# Media Library tools
# ===========================================================================

def list_media_assets(user, asset_type: str = '', q: str = '') -> dict:
    """
    List the user's personal media library assets.

    Args:
        user:       Django User instance
        asset_type: Filter by type: 'voice' | 'audio_music' | 'audio_sfx' |
                    'image' | 'video' | 'document' | 'avatar' (empty = all)
        q:          Search in name / tags / description

    Returns:
        {"assets": [{"id", "name", "asset_type", "file_url", "duration",
                     "file_size", "tags"}], "total": int}
    """
    try:
        from wama.media_library.models import UserAsset
        from django.db.models import Q as DQ

        qs = UserAsset.objects.filter(user=user)
        if asset_type:
            qs = qs.filter(asset_type=asset_type)
        if q:
            qs = qs.filter(
                DQ(name__icontains=q) | DQ(tags__icontains=q) | DQ(description__icontains=q)
            )
        qs = qs.order_by('asset_type', 'name')[:50]

        assets = [{
            'id':         a.id,
            'name':       a.name,
            'asset_type': a.asset_type,
            'file_url':   a.file.url if a.file else '',
            'duration':   a.duration_display or '',
            'file_size':  a.file_size_display,
            'tags':       a.tags,
        } for a in qs]

        return {'assets': assets, 'total': len(assets)}
    except Exception as e:
        return {'error': f'Erreur lecture médiathèque : {e}', 'assets': [], 'total': 0}


def get_media_asset_url(user, asset_id: int) -> dict:
    """
    Get the file URL of a specific media library asset.

    Args:
        user:     Django User instance
        asset_id: ID of the UserAsset

    Returns:
        {"id", "name", "asset_type", "file_url", "duration", "mime_type"}
    """
    try:
        from wama.media_library.models import UserAsset
        a = UserAsset.objects.get(pk=asset_id, user=user)
        return {
            'id':         a.id,
            'name':       a.name,
            'asset_type': a.asset_type,
            'file_url':   a.file.url if a.file else '',
            'duration':   a.duration_display or '',
            'mime_type':  a.mime_type,
        }
    except UserAsset.DoesNotExist:
        return {'error': f'Asset #{asset_id} introuvable ou accès refusé.'}
    except Exception as e:
        return {'error': f'Erreur : {e}'}


# ===========================================================================
# Tool dispatcher (used by the agentic loop in views.py)
# ===========================================================================

TOOL_REGISTRY = {
    'list_user_files':       list_user_files,
    'add_to_anonymizer':     add_to_anonymizer,
    'start_anonymizer':      start_anonymizer,
    'get_anonymizer_status': get_anonymizer_status,
    'sam3_examples':         sam3_examples,
    'create_image':          create_image,
    'start_imager':          start_imager,
    'get_imager_status':     get_imager_status,
    'add_to_enhancer':           add_to_enhancer,
    'start_enhancer':            start_enhancer,
    'get_enhancer_status':       get_enhancer_status,
    'add_to_audio_enhancer':     add_to_audio_enhancer,
    'start_audio_enhancer':      start_audio_enhancer,
    'get_audio_enhancer_status': get_audio_enhancer_status,
    'synthesize_text':        synthesize_text,
    'start_synthesizer':      start_synthesizer,
    'get_synthesizer_status': get_synthesizer_status,
    'add_to_describer':       add_to_describer,
    'start_describer':        start_describer,
    'get_describer_status':   get_describer_status,
    'add_to_transcriber':     add_to_transcriber,
    'start_transcriber':      start_transcriber,
    'get_transcriber_status': get_transcriber_status,
    'list_media_assets':      list_media_assets,
    'get_media_asset_url':    get_media_asset_url,
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
    'create_image': {
        'description': "Crée un job de génération d'image (txt2img) en attente.",
        'args': {
            'prompt':          'str  — description de l\'image (requis)',
            'model':           "str  — modèle (ex: 'hunyuan-image-2.1', 'stable-diffusion-xl', 'dreamshaper-8') (défaut: 'hunyuan-image-2.1')",
            'width':           'int  — largeur en pixels 256–2048 (défaut: 512)',
            'height':          'int  — hauteur en pixels 256–2048 (défaut: 512)',
            'steps':           'int  — nombre de pas de diffusion 1–100 (défaut: 30)',
            'guidance_scale':  'float — échelle de guidage 1.0–20.0 (défaut: 7.5)',
            'negative_prompt': 'str  — ce qu\'il faut éviter dans l\'image (défaut: "")',
            'seed':            'int|null — graine aléatoire pour reproductibilité (défaut: null)',
            'num_images':      'int  — nombre d\'images à générer 1–4 (défaut: 1)',
        },
    },
    'start_imager': {
        'description': "Lance la génération Celery pour un job ou tous les jobs en attente.",
        'args': {
            'generation_id': 'int|null — ID retourné par create_image, ou null pour tous les jobs PENDING',
        },
    },
    'get_imager_status': {
        'description': "Retourne l'état des 10 derniers jobs Imager de l'utilisateur.",
        'args': {},
    },
    'add_to_enhancer': {
        'description': "Enregistre un fichier image/vidéo pour amélioration (upscaling/débruitage).",
        'args': {
            'file_path':    'str  — chemin relatif à MEDIA_ROOT (valeur "path" de list_user_files)',
            'ai_model':     "str  — modèle IA : 'RealESR_Gx4' (défaut), 'RealESR_Animex4', 'BSRGANx2', 'BSRGANx4', 'RealESRGANx4', 'IRCNN_Mx1', 'IRCNN_Lx1'",
            'denoise':      'bool — appliquer un débruitage avant l\'upscaling (défaut: false)',
            'blend_factor': 'float — 0.0 = 100% IA, 1.0 = original (défaut: 0.0)',
        },
    },
    'start_enhancer': {
        'description': "Lance le traitement Celery de l'enhancer pour un ou tous les jobs en attente.",
        'args': {
            'enhancement_id': 'int|null — ID retourné par add_to_enhancer, ou null pour tous les PENDING',
        },
    },
    'get_enhancer_status': {
        'description': "Retourne l'état des 10 derniers jobs Enhancer image/vidéo de l'utilisateur.",
        'args': {},
    },
    'add_to_audio_enhancer': {
        'description': "Enregistre un fichier audio pour amélioration de la parole (alternative à Adobe Podcast).",
        'args': {
            'file_path':          'str   — chemin relatif à MEDIA_ROOT (valeur "path" de list_user_files)',
            'engine':             "str   — 'resemble' (qualité, défaut) | 'deepfilternet' (rapide)",
            'mode':               "str   — 'both' (défaut), 'denoise' (rapide), 'enhance' (qualité seule) — Resemble uniquement",
            'denoising_strength': 'float — force de débruitage 0.0–1.0 (défaut: 0.5) — Resemble uniquement',
            'quality':            'int   — qualité NFE 32/64/128 (défaut: 64) — Resemble uniquement',
        },
    },
    'start_audio_enhancer': {
        'description': "Lance le traitement Celery audio pour un job ou tous les jobs en attente.",
        'args': {
            'audio_enhancement_id': 'int|null — ID retourné par add_to_audio_enhancer, ou null pour tous les PENDING',
        },
    },
    'get_audio_enhancer_status': {
        'description': "Retourne l'état des 10 derniers jobs Audio Enhancer de l'utilisateur.",
        'args': {},
    },
    'synthesize_text': {
        'description': "Crée un job de synthèse vocale à partir d'un texte brut.",
        'args': {
            'text':              'str   — texte à synthétiser (requis)',
            'language':          "str   — code langue (ex: 'fr', 'en', 'es', 'de') (défaut: 'fr')",
            'tts_model':         "str   — modèle TTS ('xtts_v2', 'higgs_audio_v2', etc.) (défaut: 'xtts_v2')",
            'voice_preset':      "str   — preset de voix ('default', 'male_1', 'female_1', etc.) (défaut: 'default')",
            'speed':             'float — vitesse de parole 0.5–2.0 (défaut: 1.0)',
            'pitch':             'float — hauteur de la voix 0.5–2.0 (défaut: 1.0)',
            'emotion_intensity': 'float — intensité émotionnelle 0.0–2.0 (défaut: 1.0)',
        },
    },
    'start_synthesizer': {
        'description': "Lance la synthèse Celery pour un job ou tous les jobs en attente.",
        'args': {
            'synthesis_id': 'int|null — ID retourné par synthesize_text, ou null pour tous les PENDING',
        },
    },
    'get_synthesizer_status': {
        'description': "Retourne l'état des 10 derniers jobs Synthesizer de l'utilisateur.",
        'args': {},
    },
    'add_to_describer': {
        'description': "Enregistre un fichier (image, vidéo, audio, texte, PDF) pour description/résumé IA.",
        'args': {
            'file_path':       'str  — chemin relatif à MEDIA_ROOT (valeur "path" de list_user_files)',
            'output_format':   "str  — 'summary' (court), 'detailed' (défaut), 'scientific', 'bullet_points'",
            'output_language': "str  — 'fr' (défaut), 'en', 'auto'",
            'max_length':      'int  — longueur max du résultat en mots (défaut: 500)',
        },
    },
    'start_describer': {
        'description': "Lance le traitement Celery du Describer pour un job ou tous les jobs en attente.",
        'args': {
            'description_id': 'int|null — ID retourné par add_to_describer, ou null pour tous les PENDING',
        },
    },
    'get_describer_status': {
        'description': "Retourne l'état des 10 derniers jobs Describer, avec un aperçu du résultat.",
        'args': {},
    },
    'add_to_transcriber': {
        'description': "Enregistre un fichier audio ou vidéo pour transcription.",
        'args': {
            'file_path':          'str  — chemin relatif à MEDIA_ROOT (audio ou vidéo)',
            'backend':            "str  — 'auto' (défaut), 'whisper', 'vibevoice'",
            'preprocess_audio':   'bool — prétraitement audio avant transcription (défaut: false)',
            'hotwords':           'str  — termes spécifiques au domaine séparés par des virgules',
            'enable_diarization': 'bool — identification des locuteurs (VibeVoice) (défaut: true)',
        },
    },
    'start_transcriber': {
        'description': "Lance la transcription Celery pour un job ou tous les jobs en attente.",
        'args': {
            'transcript_id': 'int|null — ID retourné par add_to_transcriber, ou null pour tous les PENDING',
        },
    },
    'get_transcriber_status': {
        'description': "Retourne l'état des 10 derniers jobs Transcriber, avec un aperçu du texte.",
        'args': {},
    },
    'list_media_assets': {
        'description': "Liste les assets de la Médiathèque personnelle de l'utilisateur (voix, images, musiques, etc.).",
        'args': {
            'asset_type': "str — filtre par type : 'voice' | 'audio_music' | 'audio_sfx' | 'image' | 'video' | 'document' | 'avatar' (vide = tous)",
            'q':          'str — recherche dans le nom / tags / description',
        },
    },
    'get_media_asset_url': {
        'description': "Retourne l'URL de fichier d'un asset spécifique de la Médiathèque.",
        'args': {
            'asset_id': 'int — ID de l\'UserAsset',
        },
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
