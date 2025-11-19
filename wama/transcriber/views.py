import os
import io
import json
import re
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
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str

from .models import Transcript
from wama.medias.utils.console_utils import (
    get_console_lines,
    get_celery_worker_logs,
)


def _format_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return ''
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


# def _get_ffprobe_path():
#     env_binary = os.getenv("FFMPEG_BINARY")
#     if env_binary and os.path.isfile(env_binary):
#         print(f"✅ Using ffmpeg from FFMPEG_BINARY: {env_binary}")
#         return env_binary
#
#     ffprobe = shutil.which("ffprobe")
#     if ffprobe:
#         return ffprobe
#
#     windows_candidates = [
#         r"C:\ffmpeg\bin\ffprobe.exe",
#         r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
#         r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
#     ]
#     wsl_candidates = [
#         "/mnt/c/ffmpeg/bin/ffprobe.exe",
#         "/mnt/c/Program Files/ffmpeg/bin/ffprobe.exe",
#         "/mnt/c/Program Files (x86)/ffmpeg/bin/ffprobe.exe",
#     ]
#     linux_candidates = [
#         "/usr/bin/ffprobe",
#         "/usr/local/bin/ffprobe",
#     ]
#
#     if platform.system() == "Windows":
#         for candidate in windows_candidates:
#             if os.path.isfile(candidate):
#                 print(f"✅ Using ffprobe for Windows: {candidate}")
#                 return candidate
#
#     if is_wsl():
#         for candidate in wsl_candidates:
#             if os.path.isfile(candidate):
#                 print(f"✅ Using Windows ffprobe via WSL: {candidate}")
#                 return candidate
#
#     for candidate in linux_candidates:
#         if os.path.isfile(candidate):
#             print(f"✅ Using ffprobe for Linux: {candidate}")
#             return candidate
#
#     print("❌ FFMPEG binary not found. Please install ffmpeg or set FFMPEG_BINARY.")
#     return None


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
                "-show_entries", "stream=duration,codec_name,sample_rate,channels",
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
                sr_label = f"{sr_hz/1000:.1f} kHz"
            except (TypeError, ValueError):
                sr_label = f"{sample_rate} Hz"

        props = " • ".join(filter(None, [codec, sr_label, channel_label]))

        transcript.duration_seconds = duration
        transcript.duration_display = _format_duration(duration)
        transcript.properties = props
        transcript.save(update_fields=['duration_seconds', 'duration_display', 'properties'])
    except Exception:
        return


@method_decorator(login_required, name='dispatch')
class IndexView(View):
    def get(self, request):
        transcripts = Transcript.objects.filter(user=request.user).order_by('-id')
        return render(request, 'transcriber/index.html', { 'transcripts': transcripts })


class AboutView(TemplateView):
    template_name = 'transcriber/about.html'


class HelpView(TemplateView):
    template_name = 'transcriber/help.html'


@require_POST
@login_required
def upload(request):
    file = request.FILES.get('file')
    if not file:
        return HttpResponseBadRequest('Missing file')
    t = Transcript.objects.create(user=request.user, audio=file)
    _describe_audio(t)
    return JsonResponse({
        'id': t.id,
        'audio_url': t.audio.url,
        'audio_label': os.path.basename(smart_str(t.audio.name)),
        'status': t.status,
        'properties': t.properties,
        'duration_display': t.duration_display,
    })


@login_required
def start(request, pk: int):
    t = get_object_or_404(Transcript, pk=pk, user=request.user)
    from .workers import transcribe
    task = transcribe.delay(t.id)
    t.task_id = task.id
    t.status = 'RUNNING'
    t.progress = 5
    cache.set(f"transcriber_progress_{t.id}", 5, timeout=3600)
    t.save(update_fields=['task_id', 'status', 'progress'])
    return JsonResponse({ 'task_id': task.id })


@login_required
def progress(request, pk: int):
    t = get_object_or_404(Transcript, pk=pk, user=request.user)
    p = int(cache.get(f"transcriber_progress_{t.id}", t.progress or 0))
    return JsonResponse({ 'progress': p, 'status': t.status })


@login_required
def download(request, pk: int):
    t = get_object_or_404(Transcript, pk=pk, user=request.user)
    if not t.text:
        return HttpResponseBadRequest('No transcript yet')
    content = t.text.encode('utf-8')
    return FileResponse(
        content,
        as_attachment=True,
        filename=f"transcript_{t.id}.txt",
        content_type='text/plain; charset=utf-8'
    )


@require_POST
@login_required
def delete(request, pk: int):
    t = get_object_or_404(Transcript, pk=pk, user=request.user)
    audio_path = t.audio.path
    t.audio.delete(save=False)
    t.delete()
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except OSError:
            pass
    cache.delete(f"transcriber_progress_{pk}")
    return JsonResponse({ 'deleted': pk })


@login_required
def console_content(request):
    user = request.user
    lines = get_console_lines(user.id, limit=100)
    celery_lines = get_celery_worker_logs(limit=100)
    combined = (celery_lines + lines)[-200:]
    return JsonResponse({ 'output': combined })


@require_POST
@login_required
def start_all(request):
    from .workers import transcribe
    qs = Transcript.objects.filter(user=request.user).exclude(status='SUCCESS')
    started = []
    for transcript in qs:
        if transcript.status == 'RUNNING':
            continue
        task = transcribe.delay(transcript.id)
        transcript.task_id = task.id
        transcript.status = 'RUNNING'
        transcript.progress = 5
        cache.set(f"transcriber_progress_{transcript.id}", 5, timeout=3600)
        transcript.save(update_fields=['task_id', 'status', 'progress'])
        started.append(transcript.id)
    return JsonResponse({ 'started_ids': started, 'count': len(started) })


@require_POST
@login_required
def clear_all(request):
    transcripts = Transcript.objects.filter(user=request.user)
    cleared = []
    for transcript in transcripts:
        cleared.append(transcript.id)
        audio_path = transcript.audio.path
        transcript.audio.delete(save=False)
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        cache.delete(f"transcriber_progress_{transcript.id}")
    transcripts.delete()
    return JsonResponse({ 'cleared_ids': cleared, 'count': len(cleared) })


@login_required
def download_all(request):
    transcripts = Transcript.objects.filter(user=request.user).exclude(text='')
    if not transcripts.exists():
        return HttpResponseBadRequest('No transcripts ready')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for transcript in transcripts:
            filename = f"transcript_{transcript.id}.txt"
            archive.writestr(filename, transcript.text or '')
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="transcripts.zip")
