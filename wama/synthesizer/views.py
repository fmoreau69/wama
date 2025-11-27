"""
WAMA Synthesizer - Views
Interface de synthèse vocale
"""

import os
import io
import zipfile
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.views.generic import TemplateView
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

from .models import VoiceSynthesis, VoicePreset
from wama.medias.utils.console_utils import (
    get_console_lines,
    get_celery_worker_logs,
)


@method_decorator(login_required, name='dispatch')
class IndexView(View):
    """Page principale du synthesizer."""

    def get(self, request):
        syntheses = VoiceSynthesis.objects.filter(user=request.user).order_by('-id')
        voice_presets = VoicePreset.objects.filter(
            is_public=True
        ) | VoicePreset.objects.filter(created_by=request.user)

        context = {
            'syntheses': syntheses,
            'voice_presets': voice_presets,
            'tts_models': VoiceSynthesis.TTS_MODEL_CHOICES,
            'languages': VoiceSynthesis.LANGUAGE_CHOICES,
            'voice_presets_choices': VoiceSynthesis.VOICE_PRESET_CHOICES,
        }
        return render(request, 'synthesizer/index.html', context)


class AboutView(TemplateView):
    """Page À propos."""
    template_name = 'synthesizer/about.html'


class HelpView(TemplateView):
    """Page Aide."""
    template_name = 'synthesizer/help.html'


@require_POST
@login_required
def upload(request):
    """
    Upload d'un fichier texte à synthétiser.
    """
    try:
        text_file = request.FILES.get('file')
        if not text_file:
            return JsonResponse({
                'error': 'Aucun fichier fourni'
            }, status=400)

        # Valider l'extension
        allowed_extensions = ['txt', 'pdf', 'docx', 'csv', 'md']
        ext = os.path.splitext(text_file.name)[1][1:].lower()
        if ext not in allowed_extensions:
            return JsonResponse({
                'error': f'Format non supporté. Formats acceptés: {", ".join(allowed_extensions)}'
            }, status=400)

        # Récupérer les options avec gestion d'erreur
        try:
            tts_model = request.POST.get('tts_model', 'xtts_v2')
            language = request.POST.get('language', 'fr')
            voice_preset = request.POST.get('voice_preset', 'default')
            speed = float(request.POST.get('speed', 1.0))
            pitch = float(request.POST.get('pitch', 1.0))
            emotion_intensity = float(request.POST.get('emotion_intensity', 1.0))
        except (ValueError, TypeError) as e:
            return JsonResponse({
                'error': f'Paramètres invalides: {str(e)}'
            }, status=400)

        # Voice reference (optionnel)
        voice_reference = request.FILES.get('voice_reference')

        # Créer l'objet VoiceSynthesis
        synthesis = VoiceSynthesis.objects.create(
            user=request.user,
            text_file=text_file,
            tts_model=tts_model,
            language=language,
            voice_preset=voice_preset,
            speed=speed,
            pitch=pitch,
            emotion_intensity=emotion_intensity,
            voice_reference=voice_reference
        )

        # Extraire le texte et mettre à jour les métadonnées
        try:
            from .utils.text_extractor import extract_text_from_file, clean_text_for_tts
            text_content = extract_text_from_file(synthesis.text_file.path)
            synthesis.text_content = clean_text_for_tts(text_content)
            synthesis.update_metadata()
        except ImportError as e:
            # Module d'extraction pas encore créé
            synthesis.text_content = "Extraction en attente"
            synthesis.word_count = 0
            synthesis.save()
            return JsonResponse({
                'error': f"Module d'extraction non disponible: {str(e)}"
            }, status=500)
        except Exception as e:
            synthesis.status = 'FAILURE'
            synthesis.error_message = f"Erreur d'extraction: {str(e)}"
            synthesis.save()
            return JsonResponse({
                'error': f"Impossible d'extraire le texte: {str(e)}"
            }, status=400)

        return JsonResponse({
            'id': synthesis.id,
            'text_file_url': synthesis.text_file.url,
            'text_file_label': os.path.basename(smart_str(synthesis.text_file.name)),
            'status': synthesis.status,
            'word_count': synthesis.word_count,
            'duration_display': synthesis.duration_display,
            'properties': synthesis.properties or 'En attente',
            'options': {
                'model': synthesis.get_tts_model_display(),
                'language': synthesis.get_language_display(),
                'voice': synthesis.get_voice_preset_display(),
            }
        })

    except Exception as e:
        # Capturer toute erreur non gérée
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in upload view: {error_details}")

        return JsonResponse({
            'error': f'Erreur serveur: {str(e)}'
        }, status=500)


@login_required
def start(request, pk: int):
    """
    Démarre la synthèse vocale pour un fichier.
    """
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=request.user)

    if synthesis.status == 'RUNNING':
        return JsonResponse({
            'error': 'La synthèse est déjà en cours'
        }, status=400)

    from .workers import synthesize_voice
    task = synthesize_voice.delay(synthesis.id)

    synthesis.task_id = task.id
    synthesis.status = 'RUNNING'
    synthesis.progress = 5
    cache.set(f"synthesizer_progress_{synthesis.id}", 5, timeout=3600)
    synthesis.save(update_fields=['task_id', 'status', 'progress'])

    return JsonResponse({
        'task_id': task.id,
        'status': 'started'
    })


@login_required
def progress(request, pk: int):
    """
    Récupère la progression d'une synthèse.
    """
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=request.user)
    p = int(cache.get(f"synthesizer_progress_{synthesis.id}", synthesis.progress or 0))

    return JsonResponse({
        'progress': p,
        'status': synthesis.status,
        'audio_url': synthesis.audio_output.url if synthesis.audio_output else None,
        'duration_display': synthesis.duration_display,
        'error': synthesis.error_message if synthesis.status == 'FAILURE' else None,
    })


@login_required
def download(request, pk: int):
    """
    Télécharge le fichier audio généré.
    """
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=request.user)

    if not synthesis.audio_output:
        return HttpResponseBadRequest('Aucun audio généré')

    return FileResponse(
        synthesis.audio_output.open('rb'),
        as_attachment=True,
        filename=f"voice_synthesis_{synthesis.id}.wav"
    )


@login_required
def preview(request, pk: int):
    """
    Retourne l'URL de l'audio pour la prévisualisation.
    """
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=request.user)

    if not synthesis.audio_output:
        return JsonResponse({
            'error': 'Aucun audio disponible'
        }, status=404)

    return JsonResponse({
        'audio_url': synthesis.audio_output.url,
        'duration': synthesis.duration_display,
        'properties': synthesis.properties,
    })


@require_POST
@login_required
def delete(request, pk: int):
    """
    Supprime une synthèse vocale.
    """
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=request.user)

    # Supprimer les fichiers
    if synthesis.text_file:
        try:
            synthesis.text_file.delete(save=False)
        except:
            pass

    if synthesis.audio_output:
        try:
            synthesis.audio_output.delete(save=False)
        except:
            pass

    if synthesis.voice_reference:
        try:
            synthesis.voice_reference.delete(save=False)
        except:
            pass

    synthesis.delete()
    cache.delete(f"synthesizer_progress_{pk}")

    return JsonResponse({'deleted': pk})


@login_required
def console_content(request):
    """
    Récupère le contenu de la console.
    """
    user = request.user
    lines = get_console_lines(user.id, limit=100)
    celery_lines = get_celery_worker_logs(limit=100)
    combined = (celery_lines + lines)[-200:]
    return JsonResponse({'output': combined})


@require_POST
@login_required
def start_all(request):
    """
    Démarre toutes les synthèses en attente.
    """
    from .workers import synthesize_voice

    qs = VoiceSynthesis.objects.filter(user=request.user).exclude(status='SUCCESS')
    started = []

    for synthesis in qs:
        if synthesis.status == 'RUNNING':
            continue

        task = synthesize_voice.delay(synthesis.id)
        synthesis.task_id = task.id
        synthesis.status = 'RUNNING'
        synthesis.progress = 5
        cache.set(f"synthesizer_progress_{synthesis.id}", 5, timeout=3600)
        synthesis.save(update_fields=['task_id', 'status', 'progress'])
        started.append(synthesis.id)

    return JsonResponse({
        'started_ids': started,
        'count': len(started)
    })


@require_POST
@login_required
def clear_all(request):
    """
    Supprime toutes les synthèses de l'utilisateur.
    """
    syntheses = VoiceSynthesis.objects.filter(user=request.user)
    cleared = []

    for synthesis in syntheses:
        cleared.append(synthesis.id)

        # Supprimer les fichiers
        if synthesis.text_file:
            try:
                synthesis.text_file.delete(save=False)
            except:
                pass

        if synthesis.audio_output:
            try:
                synthesis.audio_output.delete(save=False)
            except:
                pass

        if synthesis.voice_reference:
            try:
                synthesis.voice_reference.delete(save=False)
            except:
                pass

        cache.delete(f"synthesizer_progress_{synthesis.id}")

    syntheses.delete()

    return JsonResponse({
        'cleared_ids': cleared,
        'count': len(cleared)
    })


@login_required
def download_all(request):
    """
    Télécharge toutes les synthèses terminées dans un ZIP.
    """
    syntheses = VoiceSynthesis.objects.filter(
        user=request.user,
        status='SUCCESS'
    ).exclude(audio_output='')

    if not syntheses.exists():
        return HttpResponseBadRequest('Aucune synthèse prête')

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for synthesis in syntheses:
            if synthesis.audio_output:
                filename = f"synthesis_{synthesis.id}_{synthesis.filename}"
                filename = filename.replace('.txt', '.wav').replace('.pdf', '.wav')

                with synthesis.audio_output.open('rb') as audio_file:
                    archive.writestr(filename, audio_file.read())

    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename="voice_syntheses.zip"
    )


@require_POST
@login_required
def update_options(request, pk: int):
    """
    Met à jour les options d'une synthèse.
    """
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=request.user)

    if synthesis.status == 'RUNNING':
        return JsonResponse({
            'error': 'Impossible de modifier une synthèse en cours'
        }, status=400)

    # Mettre à jour les champs
    if 'tts_model' in request.POST:
        synthesis.tts_model = request.POST['tts_model']
    if 'language' in request.POST:
        synthesis.language = request.POST['language']
    if 'voice_preset' in request.POST:
        synthesis.voice_preset = request.POST['voice_preset']
    if 'speed' in request.POST:
        synthesis.speed = float(request.POST['speed'])
    if 'pitch' in request.POST:
        synthesis.pitch = float(request.POST['pitch'])
    if 'emotion_intensity' in request.POST:
        synthesis.emotion_intensity = float(request.POST['emotion_intensity'])

    # Voice reference
    if 'voice_reference' in request.FILES:
        synthesis.voice_reference = request.FILES['voice_reference']

    synthesis.update_metadata()
    synthesis.save()

    return JsonResponse({
        'success': True,
        'options': {
            'model': synthesis.get_tts_model_display(),
            'language': synthesis.get_language_display(),
            'voice': synthesis.get_voice_preset_display(),
            'speed': synthesis.speed,
            'pitch': synthesis.pitch,
        }
    })


# ============= VOICE PRESETS =============

@require_POST
@login_required
def create_voice_preset(request):
    """
    Crée un preset de voix personnalisé.
    """
    name = request.POST.get('name')
    description = request.POST.get('description', '')
    reference_audio = request.FILES.get('reference_audio')
    language = request.POST.get('language', 'en')
    gender = request.POST.get('gender', 'neutral')
    is_public = request.POST.get('is_public', 'false').lower() == 'true'

    if not name or not reference_audio:
        return JsonResponse({
            'error': 'Nom et fichier audio requis'
        }, status=400)

    # Vérifier si le nom existe déjà
    if VoicePreset.objects.filter(name=name).exists():
        return JsonResponse({
            'error': 'Ce nom de preset existe déjà'
        }, status=400)

    preset = VoicePreset.objects.create(
        name=name,
        description=description,
        reference_audio=reference_audio,
        language=language,
        gender=gender,
        is_public=is_public,
        created_by=request.user
    )

    return JsonResponse({
        'success': True,
        'preset_id': preset.id,
        'name': preset.name,
        'description': preset.description,
    })


@login_required
def list_voice_presets(request):
    """
    Liste les presets de voix disponibles.
    """
    presets = VoicePreset.objects.filter(
        is_public=True
    ) | VoicePreset.objects.filter(created_by=request.user)

    data = [{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'language': p.language,
        'gender': p.gender,
        'is_public': p.is_public,
        'audio_url': p.reference_audio.url,
    } for p in presets]

    return JsonResponse({'presets': data})


@require_POST
@login_required
def delete_voice_preset(request, pk: int):
    """
    Supprime un preset de voix.
    """
    preset = get_object_or_404(VoicePreset, pk=pk, created_by=request.user)
    preset.reference_audio.delete(save=False)
    preset.delete()

    return JsonResponse({'deleted': pk})