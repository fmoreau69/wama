import os
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django.conf import settings
from django.views.decorators.http import require_POST

from .models import Transcript


@method_decorator(login_required, name='dispatch')
class IndexView(View):
    def get(self, request):
        transcripts = Transcript.objects.filter(user=request.user).order_by('-id')
        return render(request, 'transcriber/index.html', { 'transcripts': transcripts })


@require_POST
@login_required
def upload(request):
    file = request.FILES.get('file')
    if not file:
        return HttpResponseBadRequest('Missing file')
    t = Transcript.objects.create(user=request.user, audio=file)
    return JsonResponse({ 'id': t.id })


@login_required
def start(request, pk: int):
    t = get_object_or_404(Transcript, pk=pk, user=request.user)
    from .workers import transcribe
    task = transcribe.delay(t.id)
    t.task_id = task.id
    t.status = 'RUNNING'
    t.save(update_fields=['task_id', 'status'])
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
