import os
import io
import json
import re
import logging
import zipfile
import shutil
import platform
import subprocess
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.views.generic import TemplateView
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str

import datetime
from .models import Transcript, BatchTranscript, BatchTranscriptItem
from wama.common.utils.console_utils import get_console_lines
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance

logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return ''
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def _get_ffprobe_path() -> str | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe

    candidates = [
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
        "/usr/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        "/opt/homebrew/bin/ffprobe",
    ]

    if platform.system().lower().startswith('linux'):
        wsl_candidates = [
            "/mnt/c/ffmpeg/bin/ffprobe.exe",
            "/mnt/c/Program Files/ffmpeg/bin/ffprobe.exe",
            "/mnt/c/Program Files (x86)/ffprobe/bin/ffprobe.exe",
        ]
        candidates.extend(wsl_candidates)

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def _describe_audio(transcript: Transcript) -> None:
    ffprobe = _get_ffprobe_path()
    if not ffprobe:
        return

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=duration,codec_name,sample_rate,channels:format=duration",
                "-of", "json",
                transcript.audio.path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        duration = float(stream.get("duration") or 0)
        if not duration:
            fmt_duration = (data.get("format") or {}).get("duration")
            if fmt_duration:
                duration = float(fmt_duration)
        sample_rate = stream.get("sample_rate")
        codec = stream.get("codec_name")
        channels = int(stream.get("channels") or 0)

        channel_label = ""
        if channels == 1:
            channel_label = "mono"
        elif channels == 2:
            channel_label = "stéréo"
        elif channels:
            channel_label = f"{channels} canaux"

        sr_label = ""
        if sample_rate:
            try:
                sr_hz = int(sample_rate)
                sr_label = f"{sr_hz / 1000:.1f} kHz"
            except (TypeError, ValueError):
                sr_label = f"{sample_rate} Hz"

        props = " • ".join(filter(None, [codec, sr_label, channel_label]))

        transcript.duration_seconds = duration
        transcript.duration_display = _format_duration(duration)
        transcript.properties = props
        transcript.save(update_fields=['duration_seconds', 'duration_display', 'properties'])
    except Exception:
        return


def _wrap_transcript_in_batch(transcript):
    """Wrap a standalone Transcript in a new BatchTranscript-of-1."""
    batch = BatchTranscript.objects.create(user=transcript.user, total=1)
    BatchTranscriptItem.objects.create(batch=batch, transcript=transcript, row_index=0)
    return batch


def _auto_wrap_orphans(user):
    """Wrap any Transcript not yet in a batch into a batch-of-1 (called on page load)."""
    existing_ids = set(
        BatchTranscriptItem.objects.filter(batch__user=user)
        .values_list('transcript_id', flat=True)
    )
    orphans = Transcript.objects.filter(user=user).exclude(id__in=existing_ids)
    for orphan in orphans:
        try:
            _wrap_transcript_in_batch(orphan)
        except Exception:
            pass


class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily wrap any orphan transcripts into a batch-of-1
        _auto_wrap_orphans(user)

        # All batches with prefetched items+transcript
        batches_qs = BatchTranscript.objects.filter(user=user).prefetch_related(
            'items__transcript'
        ).order_by('-id')

        batches_list = []
        for batch in batches_qs:
            items = list(batch.items.all())
            success_count = sum(1 for i in items if i.transcript and i.transcript.status == 'SUCCESS')
            batches_list.append({
                'obj': batch,
                'items': items,
                'success_count': success_count,
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'has_success': success_count > 0,
            })

        queue_count = sum(len(b['items']) for b in batches_list)

        # Backfill duration for existing transcripts that were stored without it
        all_transcripts = Transcript.objects.filter(user=user)
        for t in all_transcripts:
            if not t.duration_display and t.audio:
                _describe_audio(t)

        # Récupérer les préférences utilisateur
        enable_preprocessing = cache.get(f"user_{user.id}_preprocessing_enabled", True)
        selected_backend = cache.get(f"user_{user.id}_transcriber_backend", 'auto')
        user_hotwords = cache.get(f"user_{user.id}_transcriber_hotwords", '')
        global_diarization = cache.get(f"user_{user.id}_transcriber_diarization", True)
        global_generate_summary = cache.get(f"user_{user.id}_transcriber_generate_summary", False)
        global_summary_type = cache.get(f"user_{user.id}_transcriber_summary_type", 'structured')
        global_verify_coherence = cache.get(f"user_{user.id}_transcriber_verify_coherence", False)

        # Backends are loaded asynchronously by JS (via /transcriber/backends/) to avoid
        # blocking the page render on heavy transformers imports (VibeVoice, Qwen3-ASR).
        return render(request, 'transcriber/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'transcripts': all_transcripts,  # kept for global progress bar
            'preprocessing_enabled': enable_preprocessing,
            'selected_backend': selected_backend,
            'user_hotwords': user_hotwords,
            'global_diarization': global_diarization,
            'global_generate_summary': global_generate_summary,
            'global_summary_type': global_summary_type,
            'global_verify_coherence': global_verify_coherence,
        })


class AboutView(TemplateView):
    template_name = 'transcriber/about.html'


class HelpView(TemplateView):
    template_name = 'transcriber/help.html'


@require_POST
def upload(request):
    file = request.FILES.get('file')
    if not file:
        return HttpResponseBadRequest('Missing file')

    preprocess_requested = str(request.POST.get('preprocess_audio', '')).lower() in ('1', 'true', 'on')
    backend_requested = request.POST.get('backend', 'auto')
    hotwords_requested = request.POST.get('hotwords', '')

    # Persist preferences for future uploads
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    cache_timeout = 30 * 24 * 3600
    cache.set(f"user_{user.id}_preprocessing_enabled", preprocess_requested, timeout=cache_timeout)
    if backend_requested:
        cache.set(f"user_{user.id}_transcriber_backend", backend_requested, timeout=cache_timeout)
    if hotwords_requested:
        cache.set(f"user_{user.id}_transcriber_hotwords", hotwords_requested, timeout=cache_timeout)

    from ..common.utils.video_utils import is_video_file, extract_audio_from_video

    # Common transcript fields
    transcript_fields = {
        'user': user,
        'preprocess_audio': preprocess_requested,
        'backend': backend_requested,
        'hotwords': hotwords_requested,
    }

    # Vérifier si c'est une vidéo
    if is_video_file(file.name):
        try:
            # Sauvegarder temporairement la vidéo
            import tempfile
            from django.core.files.base import ContentFile

            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as temp_video:
                for chunk in file.chunks():
                    temp_video.write(chunk)
                temp_video_path = temp_video.name

            # Extraire l'audio
            audio_path = extract_audio_from_video(temp_video_path)

            # Lire le fichier audio
            with open(audio_path, 'rb') as audio_file:
                audio_content = audio_file.read()

            # Créer un ContentFile pour Django
            audio_name = os.path.splitext(file.name)[0] + '_audio.wav'
            audio_django_file = ContentFile(audio_content, name=audio_name)

            # Créer le transcript avec l'audio extrait
            t = Transcript.objects.create(
                audio=audio_django_file,
                **transcript_fields
            )

            # Nettoyer les fichiers temporaires
            try:
                os.remove(temp_video_path)
                os.remove(audio_path)
            except OSError:
                pass

        except Exception as e:
            return JsonResponse({
                'error': f'Erreur lors de l\'extraction audio de la vidéo: {str(e)}'
            }, status=500)
    else:
        # Fichier audio normal
        t = Transcript.objects.create(
            audio=file,
            **transcript_fields
        )

    _describe_audio(t)
    _wrap_transcript_in_batch(t)
    return JsonResponse({
        'id': t.id,
        'audio_url': t.audio.url,
        'audio_label': os.path.basename(smart_str(t.audio.name)),
        'status': t.status,
        'properties': t.properties,
        'duration_display': t.duration_display,
        'preprocess_audio': t.preprocess_audio,
        'backend': t.backend,
        'hotwords': t.hotwords,
    })


@require_POST
def upload_youtube(request):
    """
    Télécharge l'audio depuis YouTube et crée une transcription.
    """
    youtube_url = request.POST.get('youtube_url', '').strip()
    if not youtube_url:
        return JsonResponse({
            'error': 'URL YouTube manquante'
        }, status=400)

    # Valider l'URL YouTube
    import re
    youtube_regex = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
    if not re.match(youtube_regex, youtube_url):
        return JsonResponse({
            'error': 'URL YouTube invalide'
        }, status=400)

    preprocess_requested = str(request.POST.get('preprocess_audio', '')).lower() in ('1', 'true', 'on')
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    cache.set(f"user_{user.id}_preprocessing_enabled", preprocess_requested, timeout=30 * 24 * 3600)

    try:
        from ..common.utils.video_utils import download_youtube_audio
        from django.core.files.base import ContentFile
        import tempfile

        # Créer un dossier temporaire pour le téléchargement
        temp_dir = tempfile.mkdtemp()

        # Télécharger l'audio
        audio_path, video_title = download_youtube_audio(youtube_url, temp_dir)

        # Lire le fichier audio
        with open(audio_path, 'rb') as audio_file:
            audio_content = audio_file.read()

        # Créer un ContentFile pour Django
        audio_name = f"{video_title[:100]}_youtube.wav"  # Limiter la longueur du nom
        audio_django_file = ContentFile(audio_content, name=audio_name)

        # Créer le transcript
        t = Transcript.objects.create(
            user=user,
            audio=audio_django_file,
            preprocess_audio=preprocess_requested,
        )

        # Nettoyer le dossier temporaire
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass

        _describe_audio(t)
        _wrap_transcript_in_batch(t)

        return JsonResponse({
            'id': t.id,
            'audio_url': t.audio.url,
            'audio_label': os.path.basename(smart_str(t.audio.name)),
            'status': t.status,
            'properties': t.properties,
            'duration_display': t.duration_display,
            'preprocess_audio': t.preprocess_audio,
            'video_title': video_title,
        })

    except Exception as e:
        return JsonResponse({
            'error': f'Erreur lors du téléchargement YouTube: {str(e)}'
        }, status=500)


@require_POST
def start(request, pk: int):
    """
    Démarre ou relance la transcription d'un fichier audio.
    Utilise les paramètres individuels du transcript (backend, preprocess_audio, etc.).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)

    if t.status == 'RUNNING':
        return JsonResponse({'error': 'Transcription déjà en cours'}, status=409)

    # Reset for relaunch
    from .models import TranscriptSegment
    TranscriptSegment.objects.filter(transcript=t).delete()
    t.status = 'PENDING'
    t.progress = 0
    t.text = ''
    t.segments_json = None
    t.language = ''
    t.used_backend = ''
    cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)

    # Use the transcript's own preprocess_audio setting
    from .workers import transcribe, transcribe_without_preprocessing
    if t.preprocess_audio:
        task = transcribe.delay(t.id)
    else:
        task = transcribe_without_preprocessing.delay(t.id)

    t.task_id = task.id
    t.status = 'RUNNING'
    t.save()

    return JsonResponse({
        'task_id': task.id,
        'status': 'RUNNING',
    })


def progress(request, pk: int):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)
    p = int(cache.get(f"transcriber_progress_{t.id}", t.progress or 0))

    # Get partial text for live display
    partial_text = cache.get(f"transcriber_partial_text_{t.id}", '')

    response_data = {
        'progress': p,
        'status': t.status,
        'partial_text': partial_text,
    }

    if t.status == 'SUCCESS':
        response_data['text'] = t.text or ''
        response_data['summary'] = t.summary or ''
        response_data['summary_type'] = t.summary_type or 'structured'
        response_data['key_points'] = t.key_points or []
        response_data['action_items'] = t.action_items or []
        response_data['coherence_score'] = t.coherence_score
        response_data['coherence_notes'] = t.coherence_notes or ''
        response_data['coherence_suggestion'] = t.coherence_suggestion or ''

    return JsonResponse(response_data)


def _output_stem(t: Transcript) -> str:
    """Build output filename stem: {input_stem}_{backend}."""
    input_stem = os.path.splitext(t.filename)[0]
    return f"{input_stem}_{t.used_backend}" if t.used_backend else input_stem


def download(request, pk: int):
    """Download transcript in requested format: txt (default), srt, pdf, docx."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)
    if not t.text:
        return HttpResponseBadRequest('No transcript yet')

    fmt = request.GET.get('format', 'txt').lower()
    stem = _output_stem(t)

    if fmt == 'srt':
        # Delegate to existing SRT logic (preserving download_srt for backward compat)
        from wama.common.utils.media_paths import get_app_media_path
        disk_path = get_app_media_path('transcriber', user.id, 'output') / f"{stem}.srt"
        if disk_path.exists():
            return FileResponse(open(disk_path, 'rb'), as_attachment=True,
                                filename=f"{stem}.srt", content_type='text/plain; charset=utf-8')
        # Generate on the fly from segments
        from .models import TranscriptSegment
        segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')
        srt_lines = []
        if segments.exists():
            for i, seg in enumerate(segments, 1):
                def _srt_ts(s):
                    h, rem = divmod(int(s), 3600)
                    m, sec = divmod(rem, 60)
                    ms = int((s - int(s)) * 1000)
                    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
                speaker = f'[{seg.speaker_id}] ' if seg.speaker_id else ''
                srt_lines += [str(i), f"{_srt_ts(seg.start_time)} --> {_srt_ts(seg.end_time)}", speaker + seg.text, '']
        else:
            srt_lines = ['1', '00:00:00,000 --> 99:59:59,000', t.text, '']
        buf = io.BytesIO('\n'.join(srt_lines).encode('utf-8'))
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=f"{stem}.srt",
                            content_type='text/plain; charset=utf-8')

    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_transcript_pdf
            pdf_bytes = generate_transcript_pdf(t)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{stem}.pdf"'
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Transcriber] PDF generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur PDF : {e}')

    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_transcript_docx
            docx_bytes = generate_transcript_docx(t)
            response = HttpResponse(
                docx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            response['Content-Disposition'] = f'attachment; filename="{stem}.docx"'
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Transcriber] DOCX generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur DOCX : {e}')

    # Default: txt
    from wama.common.utils.media_paths import get_app_media_path
    disk_path = get_app_media_path('transcriber', user.id, 'output') / f"{stem}.txt"
    if disk_path.exists():
        return FileResponse(open(disk_path, 'rb'), as_attachment=True,
                            filename=f"{stem}.txt", content_type='text/plain; charset=utf-8')
    buf = io.BytesIO(t.text.encode('utf-8'))
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f"{stem}.txt",
                        content_type='text/plain; charset=utf-8')


def _cleanup_output_files(t: Transcript, user_id: int) -> None:
    """Remove output TXT/SRT files for a transcript."""
    if t.used_backend:
        try:
            from wama.common.utils.media_paths import get_app_media_path
            output_dir = get_app_media_path('transcriber', user_id, 'output')
            stem = _output_stem(t)
            for ext in ('.txt', '.srt'):
                path = output_dir / f"{stem}{ext}"
                if path.exists():
                    path.unlink()
        except Exception:
            pass


@require_POST
def enrich(request, pk: int):
    """Lance l'enrichissement LLM (résumé, points clés, actions) sur un transcript déjà transcrit."""
    import json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)

    if not t.text:
        return JsonResponse({'error': 'Pas de texte transcrit'}, status=400)

    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    summary_type = data.get('summary_type', t.summary_type or 'structured')

    from .workers import enrich_transcript
    task = enrich_transcript.delay(t.id, summary_type)
    return JsonResponse({'ok': True, 'task_id': task.id, 'summary_type': summary_type})


@require_POST
def delete(request, pk: int):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)
    # Output files are unique to this transcript — always delete
    _cleanup_output_files(t, user.id)
    # Audio file may be shared with a duplicate — only delete if no other row references it
    safe_delete_file(t, 'audio')
    t.delete()
    cache.delete(f"transcriber_progress_{pk}")
    return JsonResponse({'deleted': pk})


@require_POST
def duplicate(request, pk: int):
    """Duplicate a Transcript sharing the same audio file, resetting all results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)
    new_t = duplicate_instance(
        t,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'properties': '',
            'language': '',
            'text': '',
            'used_backend': '',
            'summary': '',
            'coherence_notes': '',
            'coherence_suggestion': '',
        },
        clear_fields=['segments_json', 'key_points', 'action_items', 'coherence_score'],
    )
    _wrap_transcript_in_batch(new_t)
    return JsonResponse({'duplicated': new_t.id})


def console_content(request):
    """Retourne un flux textuel des logs en cours pour affichage console (via Redis/Cache + logs Celery)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


@require_POST
def start_all(request):
    """
    Démarre toutes les transcriptions non terminées.
    Respecte les paramètres individuels de chaque transcript.
    """
    from .workers import transcribe, transcribe_without_preprocessing
    from .models import TranscriptSegment

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    qs = Transcript.objects.filter(user=user).exclude(status='SUCCESS')
    started = []
    for t in qs:
        if t.status == 'RUNNING':
            continue

        # Reset for relaunch
        TranscriptSegment.objects.filter(transcript=t).delete()
        t.progress = 0
        t.text = ''
        t.segments_json = None
        t.language = ''
        t.used_backend = ''
        cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)

        # Use transcript's own preprocess setting
        if t.preprocess_audio:
            task = transcribe.delay(t.id)
        else:
            task = transcribe_without_preprocessing.delay(t.id)

        t.task_id = task.id
        t.status = 'RUNNING'
        t.save()
        started.append(t.id)

    return JsonResponse({
        'started_ids': started,
        'count': len(started),
    })


@require_POST
def clear_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    transcripts = Transcript.objects.filter(user=user)
    cleared = []
    for transcript in transcripts:
        cleared.append(transcript.id)
        audio_path = transcript.audio.path
        _cleanup_output_files(transcript, user.id)
        transcript.audio.delete(save=False)
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        cache.delete(f"transcriber_progress_{transcript.id}")
    transcripts.delete()
    return JsonResponse({'cleared_ids': cleared, 'count': len(cleared)})


def download_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    transcripts = Transcript.objects.filter(user=user).exclude(text='')
    if not transcripts.exists():
        return HttpResponseBadRequest('No transcripts ready')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for transcript in transcripts:
            stem = _output_stem(transcript)
            archive.writestr(f"{stem}.txt", transcript.text or '')
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="transcripts.zip")


# =============================================================================
# BATCH VIEWS
# =============================================================================

def batch_template(request):
    """Download a batch file template (.txt)."""
    from django.http import HttpResponse
    content = (
        "# WAMA Transcriber - Batch Import\n"
        "# Format : une URL ou chemin de fichier audio/vidéo par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n\n"
        "https://example.com/audio.mp3\n"
        "https://example.com/video.mp4\n"
        "/media/uploads/recording.wav\n"
    )
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_transcriber_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchTranscript + Transcript entries.
    Returns batch_id and list of transcript IDs.
    Files are not downloaded yet — download happens when each task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    backend = request.POST.get('backend', 'auto')
    hotwords = request.POST.get('hotwords', '')
    preprocess_audio = str(request.POST.get('preprocess_audio', '')).lower() in ('1', 'true', 'on')

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    # Save the batch file reference, then seek back
    batch_file.seek(0)
    batch = BatchTranscript.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        # Create a Transcript with source_url, no audio file yet
        t = Transcript.objects.create(
            user=user,
            source_url=url_or_path,
            audio='',  # empty — will be populated when task downloads the file
            backend=backend,
            hotwords=hotwords,
            preprocess_audio=preprocess_audio,
        )
        BatchTranscriptItem.objects.create(batch=batch, transcript=t, row_index=i)
        created_ids.append(t.id)

    return JsonResponse({
        'batch_id': batch.id,
        'transcript_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List the current user's batches with status counts."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchTranscript.objects.filter(user=user).prefetch_related('items__transcript')

    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for item in batch.items.all():
            if item.transcript:
                k = item.transcript.status.lower()
                counts[k] = counts.get(k, 0) + 1

        total = batch.total
        if total > 0 and counts['success'] == total:
            status = 'SUCCESS'
        elif counts['running'] > 0:
            status = 'RUNNING'
        elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
            status = 'FAILURE'
        else:
            status = 'PENDING'

        data.append({
            'id': batch.id,
            'created_at': batch.created_at.strftime('%d/%m/%Y %H:%M'),
            'total': total,
            'status': status,
            'counts': counts,
        })

    return JsonResponse({'batches': data})


@require_POST
def batch_start(request, pk):
    """Start all PENDING transcripts in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchTranscript, pk=pk, user=user)

    from .workers import transcribe, transcribe_without_preprocessing

    started = []
    for item in batch.items.select_related('transcript').all():
        t = item.transcript
        if not t or t.status == 'RUNNING':
            continue
        t.status = 'RUNNING'
        t.progress = 0
        t.save(update_fields=['status', 'progress'])
        cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)

        if t.preprocess_audio:
            task = transcribe.delay(t.id)
        else:
            task = transcribe_without_preprocessing.delay(t.id)

        t.task_id = task.id
        t.status = 'RUNNING'
        t.save(update_fields=['task_id', 'status'])
        started.append(t.id)

    return JsonResponse({'started': started, 'count': len(started)})


def batch_status(request, pk):
    """Return status of all items in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchTranscript, pk=pk, user=user)

    counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
    items_data = []

    for item in batch.items.select_related('transcript').all():
        t = item.transcript
        if not t:
            continue
        key = t.status.lower()
        counts[key] = counts.get(key, 0) + 1
        p = int(cache.get(f"transcriber_progress_{t.id}", t.progress or 0))
        fname = t.filename if t.audio else (t.source_url.split('/')[-1] or t.source_url)
        items_data.append({
            'id': t.id,
            'filename': fname,
            'status': t.status,
            'progress': p,
        })

    total = batch.total
    if total > 0 and counts['success'] == total:
        status_str = 'SUCCESS'
    elif counts['running'] > 0:
        status_str = 'RUNNING'
    elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
        status_str = 'FAILURE'
    else:
        status_str = 'PENDING'

    return JsonResponse({
        'batch_id': pk,
        'status': status_str,
        'total': total,
        'counts': counts,
        'items': items_data,
    })


def batch_download(request, pk):
    """Download a ZIP of all completed transcription results in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchTranscript, pk=pk, user=user)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in batch.items.select_related('transcript').order_by('row_index'):
            t = item.transcript
            if t and t.status == 'SUCCESS' and t.text:
                stem = _output_stem(t) if t.audio else (
                    os.path.splitext(t.source_url.split('/')[-1])[0] or f'transcript_{t.id}'
                )
                archive.writestr(f'{stem}.txt', t.text.encode('utf-8'))

    buffer.seek(0)
    zip_name = f"batch_transcriber_{pk}_{datetime.date.today()}.zip"
    return FileResponse(buffer, as_attachment=True, filename=zip_name)


@require_POST
def batch_delete(request, pk):
    """Delete an entire batch: cascade-delete transcripts, clean up files."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchTranscript, pk=pk, user=user)

    transcripts_to_delete = []
    for item in batch.items.select_related('transcript').all():
        t = item.transcript
        if not t:
            continue
        if t.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(t.task_id).revoke(terminate=False)
            except Exception:
                pass
        transcripts_to_delete.append(t)

    safe_delete_file(batch, 'batch_file')
    batch.delete()  # CASCADE deletes BatchTranscriptItems (not Transcripts)

    for t in transcripts_to_delete:
        _cleanup_output_files(t, user.id)
        safe_delete_file(t, 'audio')
        cache.delete(f"transcriber_progress_{t.id}")
        t.delete()

    return JsonResponse({'success': True, 'batch_id': pk})


@require_POST
def batch_duplicate(request, pk):
    """Duplicate an entire batch (shares source files, results cleared)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchTranscript, pk=pk, user=user)

    new_batch = BatchTranscript.objects.create(user=user, total=batch.total)
    for item in batch.items.select_related('transcript').order_by('row_index'):
        t = item.transcript
        if not t:
            continue
        new_t = duplicate_instance(t, reset_fields={
            'status': 'PENDING', 'progress': 0, 'task_id': '',
            'language': '', 'text': '', 'used_backend': '',
            'properties': '', 'duration_seconds': 0, 'duration_display': '',
            'summary': '', 'coherence_notes': '', 'coherence_suggestion': '',
        }, clear_fields=['segments_json', 'key_points', 'action_items', 'coherence_score'])
        BatchTranscriptItem.objects.create(batch=new_batch, transcript=new_t, row_index=item.row_index)

    return JsonResponse({'success': True, 'batch_id': new_batch.id})


@require_POST
def set_preprocessing_preference(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            payload = {}
    enabled = payload.get('enabled')
    if enabled is None:
        enabled = str(request.POST.get('enabled', '')).lower() in ('1', 'true', 'on')
    else:
        enabled = bool(enabled)
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    cache.set(f"user_{user.id}_preprocessing_enabled", enabled, timeout=30 * 24 * 3600)
    return JsonResponse({'enabled': enabled})


@require_POST
def toggle_preprocessing(request):
    """
    Nouvelle vue pour activer/désactiver le prétraitement audio.
    """
    enable = request.POST.get('enable', 'true').lower() == 'true'
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    cache.set(f"user_{user.id}_preprocessing_enabled", enable, timeout=None)

    return JsonResponse({
        'preprocessing_enabled': enable,
        'message': 'Prétraitement activé' if enable else 'Prétraitement désactivé',
    })


def preprocessing_status(request):
    """
    Retourne le statut actuel du prétraitement pour l'utilisateur.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enabled = cache.get(f"user_{user.id}_preprocessing_enabled", True)
    return JsonResponse({
        'preprocessing_enabled': enabled,
    })


def global_progress(request):
    """Get overall progress for all user transcripts"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        transcripts = Transcript.objects.filter(user=user)

        if not transcripts.exists():
            return JsonResponse({
                'total': 0,
                'pending': 0,
                'running': 0,
                'success': 0,
                'failure': 0,
                'overall_progress': 0
            })

        total = transcripts.count()
        pending = transcripts.filter(status='PENDING').count()
        running = transcripts.filter(status='RUNNING').count()
        success = transcripts.filter(status='SUCCESS').count()
        failure = transcripts.filter(status='FAILURE').count()

        # Calculate overall progress
        total_progress = sum(t.progress for t in transcripts)
        overall_progress = int(total_progress / total) if total > 0 else 0

        return JsonResponse({
            'total': total,
            'pending': pending,
            'running': running,
            'success': success,
            'failure': failure,
            'overall_progress': overall_progress
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# =============================================================================
# NEW: VibeVoice-related views
# =============================================================================

def get_backends(request):
    """
    Get list of available transcription backends.

    Returns:
        JSON with backend info including availability and features.
    """
    _BACKENDS_CACHE_KEY = 'transcriber_backends_info'
    backends = cache.get(_BACKENDS_CACHE_KEY)
    if backends is None:
        try:
            from .backends import get_backends_info
            backends = get_backends_info()
            cache.set(_BACKENDS_CACHE_KEY, backends, timeout=3600)
        except ImportError:
            backends = [
                {
                    'name': 'whisper',
                    'display_name': 'Whisper (OpenAI)',
                    'available': True,
                    'supports_diarization': False,
                    'supports_timestamps': True,
                    'supports_hotwords': False,
                }
            ]
    return JsonResponse({'backends': backends, 'default': 'auto'})


def get_segments(request, pk: int):
    """
    Get transcript segments with speaker and timestamp info.

    Returns:
        JSON with segments array containing speaker_id, start_time, end_time, text.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)

    # Try to get segments from database first
    from .models import TranscriptSegment
    segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')

    if segments.exists():
        segments_data = [
            {
                'id': seg.id,
                'speaker_id': seg.speaker_id,
                'start_time': seg.start_time,
                'end_time': seg.end_time,
                'text': seg.text,
                'confidence': seg.confidence,
                'time_range': seg.format_time_range(),
            }
            for seg in segments
        ]
    elif t.segments_json:
        # Fallback to JSON backup
        segments_data = t.segments_json
    else:
        segments_data = []

    # Get unique speakers
    speakers = list(set(s.get('speaker_id', '') for s in segments_data if s.get('speaker_id')))

    return JsonResponse({
        'id': t.id,
        'has_segments': len(segments_data) > 0,
        'segment_count': len(segments_data),
        'speaker_count': len(speakers),
        'speakers': speakers,
        'segments': segments_data,
        'backend': t.used_backend,
    })


def download_srt(request, pk: int):
    """
    Download transcript as SRT subtitle file.

    Returns:
        SRT file with speaker labels and timestamps.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)

    stem = _output_stem(t)

    # Serve saved file from disk if it exists
    from wama.common.utils.media_paths import get_app_media_path
    disk_path = get_app_media_path('transcriber', user.id, 'output') / f"{stem}.srt"
    if disk_path.exists():
        return FileResponse(
            open(disk_path, 'rb'),
            as_attachment=True,
            filename=f"{stem}.srt",
            content_type='text/plain; charset=utf-8'
        )

    # Fallback: generate on the fly
    from .models import TranscriptSegment

    segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')

    if not segments.exists():
        if not t.text:
            return HttpResponseBadRequest('No transcript content')
        srt_content = f"1\n00:00:00,000 --> 00:00:00,000\n{t.text}\n\n"
    else:
        srt_content = ""
        for i, seg in enumerate(segments, 1):
            srt_content += seg.to_srt_entry(i)

    buffer = io.BytesIO(srt_content.encode('utf-8'))
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{stem}.srt",
        content_type='text/plain; charset=utf-8'
    )


@require_POST
def save_settings(request, pk: int):
    """
    Save transcript settings (backend, hotwords, etc.) before processing.

    Expected JSON body:
    {
        "backend": "whisper" | "vibevoice" | "auto",
        "hotwords": "term1, term2, ...",
        "enable_diarization": true,
        "temperature": 0.0,
        "max_tokens": 32768
    }
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    # Update fields
    if 'backend' in data:
        t.backend = data['backend']
    if 'hotwords' in data:
        t.hotwords = data['hotwords']
    if 'enable_diarization' in data:
        t.enable_diarization = bool(data['enable_diarization'])
    if 'temperature' in data:
        t.temperature = float(data['temperature'])
    if 'max_tokens' in data:
        t.max_tokens = int(data['max_tokens'])
    if 'preprocess_audio' in data:
        t.preprocess_audio = bool(data['preprocess_audio'])
    if 'generate_summary' in data:
        t.generate_summary = bool(data['generate_summary'])
    if 'summary_type' in data:
        t.summary_type = data['summary_type']
    if 'verify_coherence' in data:
        t.verify_coherence = bool(data['verify_coherence'])

    t.save()

    return JsonResponse({
        'id': t.id,
        'backend': t.backend,
        'hotwords': t.hotwords,
        'enable_diarization': t.enable_diarization,
        'temperature': t.temperature,
        'max_tokens': t.max_tokens,
        'preprocess_audio': t.preprocess_audio,
        'generate_summary': t.generate_summary,
        'summary_type': t.summary_type,
        'verify_coherence': t.verify_coherence,
    })


@require_POST
def save_user_transcriber_settings(request):
    """
    Save user-level transcriber settings (cached).

    Expected JSON body:
    {
        "backend": "whisper" | "vibevoice" | "auto",
        "hotwords": "default hotwords",
        "enable_diarization": true,
        "preprocessing_enabled": true
    }
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    # Cache settings
    cache_timeout = 30 * 24 * 3600  # 30 days

    if 'backend' in data:
        cache.set(f"user_{user.id}_transcriber_backend", data['backend'], timeout=cache_timeout)
    if 'hotwords' in data:
        cache.set(f"user_{user.id}_transcriber_hotwords", data['hotwords'], timeout=cache_timeout)
    if 'enable_diarization' in data:
        cache.set(f"user_{user.id}_transcriber_diarization", data['enable_diarization'], timeout=cache_timeout)
    if 'preprocessing_enabled' in data:
        cache.set(f"user_{user.id}_preprocessing_enabled", data['preprocessing_enabled'], timeout=cache_timeout)
    if 'generate_summary' in data:
        cache.set(f"user_{user.id}_transcriber_generate_summary", data['generate_summary'], timeout=cache_timeout)
    if 'summary_type' in data:
        cache.set(f"user_{user.id}_transcriber_summary_type", data['summary_type'], timeout=cache_timeout)
    if 'verify_coherence' in data:
        cache.set(f"user_{user.id}_transcriber_verify_coherence", data['verify_coherence'], timeout=cache_timeout)

    return JsonResponse({
        'backend': cache.get(f"user_{user.id}_transcriber_backend", 'auto'),
        'hotwords': cache.get(f"user_{user.id}_transcriber_hotwords", ''),
        'enable_diarization': cache.get(f"user_{user.id}_transcriber_diarization", True),
        'preprocessing_enabled': cache.get(f"user_{user.id}_preprocessing_enabled", True),
        'generate_summary': cache.get(f"user_{user.id}_transcriber_generate_summary", False),
        'summary_type': cache.get(f"user_{user.id}_transcriber_summary_type", 'structured'),
        'verify_coherence': cache.get(f"user_{user.id}_transcriber_verify_coherence", False),
    })


def get_user_transcriber_settings(request):
    """
    Get user-level transcriber settings.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    return JsonResponse({
        'backend': cache.get(f"user_{user.id}_transcriber_backend", 'auto'),
        'hotwords': cache.get(f"user_{user.id}_transcriber_hotwords", ''),
        'enable_diarization': cache.get(f"user_{user.id}_transcriber_diarization", True),
        'preprocessing_enabled': cache.get(f"user_{user.id}_preprocessing_enabled", True),
        'generate_summary': cache.get(f"user_{user.id}_transcriber_generate_summary", False),
        'summary_type': cache.get(f"user_{user.id}_transcriber_summary_type", 'structured'),
        'verify_coherence': cache.get(f"user_{user.id}_transcriber_verify_coherence", False),
    })