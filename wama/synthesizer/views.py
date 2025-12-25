"""
WAMA Synthesizer - Views
Interface de synthèse vocale
"""

import os
import io
import zipfile
import logging
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
from django.core.files.base import ContentFile

from .models import VoiceSynthesis, VoicePreset
from wama.common.utils.console_utils import (
    get_console_lines,
    get_celery_worker_logs,
)
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)

# Don't import TTS worker functions at module level to avoid blocking Gunicorn startup
# Import them lazily when needed
_get_tts_model = None
_get_default_speaker_wav = None
synthesize_voice = None

def _ensure_workers_imported():
    """Lazy import of worker functions to avoid blocking Gunicorn startup."""
    global _get_tts_model, _get_default_speaker_wav, synthesize_voice

    if _get_tts_model is None:
        try:
            from .workers import _get_tts_model as gtm, _get_default_speaker_wav as gds, synthesize_voice as sv
            _get_tts_model = gtm
            _get_default_speaker_wav = gds
            synthesize_voice = sv
            logger.info("TTS worker functions imported successfully")
        except Exception as e:
            logger.error(f"Failed to import TTS worker functions: {e}")
            raise


class IndexView(View):
    """Page principale du synthesizer."""

    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user() if request.user.is_authenticated else get_or_create_anonymous_user()
        syntheses = VoiceSynthesis.objects.filter(user=user).order_by('-id')
        voice_presets = VoicePreset.objects.filter(
            is_public=True
        ) | VoicePreset.objects.filter(created_by=user)

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

        # Récupérer l'utilisateur (authentifié ou anonyme)
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Créer l'objet VoiceSynthesis
        synthesis = VoiceSynthesis.objects.create(
            user=user,
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


@require_POST
def upload_text(request):
    """
    Créer un fichier DOCX à partir du texte saisi et l'ajouter à la file d'attente.
    """
    try:
        text_content = request.POST.get('text_content', '').strip()
        title = request.POST.get('title', '').strip()

        if not text_content:
            return JsonResponse({
                'error': 'Le texte ne peut pas être vide'
            }, status=400)

        # Générer un nom de fichier
        if not title:
            # Utiliser les premiers mots du texte comme titre
            words = text_content.split()[:5]
            title = ' '.join(words)
            if len(text_content.split()) > 5:
                title += '...'

        # Limiter la longueur du titre
        if len(title) > 50:
            title = title[:50] + '...'

        filename = f"{title}.docx"

        # Créer un fichier DOCX avec python-docx
        try:
            from docx import Document
            from docx.shared import Pt

            doc = Document()

            # Note: On n'ajoute PAS le titre au document DOCX
            # Le titre sert uniquement pour le nom du fichier
            # Seul le text_content sera synthétisé vocalement

            # Ajouter uniquement le contenu (sans le titre)
            # Split par paragraphes (double saut de ligne)
            paragraphs = text_content.split('\n\n')
            for para_text in paragraphs:
                if para_text.strip():
                    paragraph = doc.add_paragraph(para_text.strip())
                    # Format basique
                    for run in paragraph.runs:
                        run.font.size = Pt(12)

            # Sauvegarder dans un buffer
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)

            # Créer un ContentFile pour Django
            docx_file = ContentFile(buffer.read(), name=filename)

        except ImportError:
            return JsonResponse({
                'error': 'Le module python-docx n\'est pas installé. Veuillez l\'installer avec: pip install python-docx'
            }, status=500)
        except Exception as e:
            return JsonResponse({
                'error': f'Erreur lors de la création du fichier DOCX: {str(e)}'
            }, status=500)

        # Récupérer les options (utiliser les valeurs par défaut si non fournies)
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

        # Récupérer l'utilisateur
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Créer l'objet VoiceSynthesis
        synthesis = VoiceSynthesis.objects.create(
            user=user,
            text_file=docx_file,
            tts_model=tts_model,
            language=language,
            voice_preset=voice_preset,
            speed=speed,
            pitch=pitch,
            emotion_intensity=emotion_intensity,
            voice_reference=voice_reference
        )

        # Mettre à jour les métadonnées
        try:
            from .utils.text_extractor import extract_text_from_file, clean_text_for_tts
            extracted_text = extract_text_from_file(synthesis.text_file.path)
            synthesis.text_content = clean_text_for_tts(extracted_text)
            synthesis.update_metadata()
        except ImportError:
            # Si le module d'extraction n'existe pas, utiliser le texte brut
            synthesis.text_content = text_content
            synthesis.word_count = len(text_content.split())
            synthesis.save()
        except Exception as e:
            synthesis.status = 'FAILURE'
            synthesis.error_message = f"Erreur d'extraction: {str(e)}"
            synthesis.save()
            return JsonResponse({
                'error': f"Impossible d'extraire le texte: {str(e)}"
            }, status=400)

        return JsonResponse({
            'success': True,
            'id': synthesis.id,
            'text_file_url': synthesis.text_file.url,
            'text_file_label': filename,
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
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in upload_text view: {error_details}")

        return JsonResponse({
            'error': f'Erreur serveur: {str(e)}'
        }, status=500)


def text_preview(request, pk: int):
    """
    Récupère le contenu texte d'une synthèse pour prévisualisation.
    """
    try:
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)

        # Si le contenu texte est déjà extrait, l'utiliser
        if synthesis.text_content:
            text_content = synthesis.text_content
        else:
            # Sinon, extraire depuis le fichier
            try:
                from .utils.text_extractor import extract_text_from_file
                text_content = extract_text_from_file(synthesis.text_file.path)
            except ImportError:
                # Fallback: lire le fichier brut
                try:
                    with open(synthesis.text_file.path, 'r', encoding='utf-8') as f:
                        text_content = f.read()
                except Exception as e:
                    text_content = f"Impossible de lire le fichier: {str(e)}"

        return JsonResponse({
            'success': True,
            'filename': synthesis.filename,
            'text_content': text_content,
            'word_count': synthesis.word_count,
            'duration_display': synthesis.duration_display,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Erreur lors de la récupération du texte: {str(e)}'
        }, status=500)


def start(request, pk: int):
    """
    Démarre la synthèse vocale pour un fichier.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)

    if synthesis.status == 'RUNNING':
        return JsonResponse({
            'error': 'La synthèse est déjà en cours'
        }, status=400)

    # Réinitialiser complètement la synthèse
    synthesis.status = 'PENDING'
    synthesis.progress = 0
    synthesis.error_message = ''

    # Supprimer l'ancien audio si présent
    if synthesis.audio_output:
        try:
            synthesis.audio_output.delete(save=False)
        except:
            pass

    synthesis.save(update_fields=['status', 'progress', 'error_message', 'audio_output'])
    cache.set(f"synthesizer_progress_{synthesis.id}", 0, timeout=3600)

    _ensure_workers_imported()

    task = synthesize_voice.delay(synthesis.id)

    synthesis.task_id = task.id
    synthesis.status = 'RUNNING'
    synthesis.progress = 0
    cache.set(f"synthesizer_progress_{synthesis.id}", 0, timeout=3600)
    synthesis.save(update_fields=['task_id', 'status', 'progress'])

    return JsonResponse({
        'task_id': task.id,
        'status': 'started'
    })


def progress(request, pk: int):
    """
    Récupère la progression d'une synthèse.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)
    p = int(cache.get(f"synthesizer_progress_{synthesis.id}", synthesis.progress or 0))

    return JsonResponse({
        'progress': p,
        'status': synthesis.status,
        'audio_url': synthesis.audio_output.url if synthesis.audio_output else None,
        'duration_display': synthesis.duration_display,
        'error': synthesis.error_message if synthesis.status == 'FAILURE' else None,
    })


def global_progress(request):
    """
    Récupère la progression globale de toutes les synthèses de l'utilisateur.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    syntheses = VoiceSynthesis.objects.filter(user=user)

    if not syntheses.exists():
        return JsonResponse({
            'global_progress': 0,
            'total': 0,
            'completed': 0,
            'running': 0,
            'pending': 0,
            'failed': 0
        })

    total = syntheses.count()
    completed = syntheses.filter(status='SUCCESS').count()
    running = syntheses.filter(status='RUNNING').count()
    pending = syntheses.filter(status='PENDING').count()
    failed = syntheses.filter(status='FAILURE').count()

    # Calculer la progression globale
    # Les synthèses SUCCESS comptent pour 100%
    # Les synthèses RUNNING comptent selon leur progression
    # Les synthèses PENDING comptent pour 0%
    # Les synthèses FAILURE comptent pour 0%
    total_progress = 0

    for synthesis in syntheses:
        if synthesis.status == 'SUCCESS':
            total_progress += 100
        elif synthesis.status == 'RUNNING':
            p = int(cache.get(f"synthesizer_progress_{synthesis.id}", synthesis.progress or 0))
            total_progress += p
        # PENDING et FAILURE comptent pour 0

    global_progress = int(total_progress / total) if total > 0 else 0

    return JsonResponse({
        'global_progress': global_progress,
        'total': total,
        'completed': completed,
        'running': running,
        'pending': pending,
        'failed': failed
    })


def download(request, pk: int):
    """
    Télécharge le fichier audio généré.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)

    if not synthesis.audio_output:
        return HttpResponseBadRequest('Aucun audio généré')

    return FileResponse(
        synthesis.audio_output.open('rb'),
        as_attachment=True,
        filename=f"voice_synthesis_{synthesis.id}.wav"
    )


def preview(request, pk: int):
    """
    Retourne l'URL de l'audio pour la prévisualisation.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)

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
def delete(request, pk: int):
    """
    Supprime une synthèse vocale.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)

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


def console_content(request):
    """
    Récupère le contenu de la console.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    lines = get_console_lines(user.id, limit=100)
    celery_lines = get_celery_worker_logs(limit=100)
    combined = (celery_lines + lines)[-200:]
    return JsonResponse({'output': combined})


@require_POST
def start_all(request):
    """
    Démarre toutes les synthèses en attente.
    Met à jour les options de synthèse pour toutes les files avant de les lancer.
    """
    try:
        _ensure_workers_imported()
    except Exception as e:
        return JsonResponse({'error': f'TTS worker functions not available: {str(e)}'}, status=500)

    # Récupérer les nouvelles options depuis le formulaire
    try:
        tts_model = request.POST.get('tts_model')
        language = request.POST.get('language')
        voice_preset = request.POST.get('voice_preset')
        speed = request.POST.get('speed')
        pitch = request.POST.get('pitch')
        voice_reference = request.FILES.get('voice_reference')
    except Exception as e:
        return JsonResponse({
            'error': f'Erreur lors de la récupération des options: {str(e)}'
        }, status=400)

    # Récupérer toutes les synthèses (sauf celles en cours)
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    qs = VoiceSynthesis.objects.filter(user=user).exclude(status='RUNNING')
    started = []
    updated_options = []

    for synthesis in qs:
        # Mettre à jour les options si fournies
        options_changed = False
        if tts_model and synthesis.tts_model != tts_model:
            synthesis.tts_model = tts_model
            options_changed = True
        if language and synthesis.language != language:
            synthesis.language = language
            options_changed = True
        if voice_preset and synthesis.voice_preset != voice_preset:
            synthesis.voice_preset = voice_preset
            options_changed = True
        if speed and float(speed) != synthesis.speed:
            synthesis.speed = float(speed)
            options_changed = True
        if pitch and float(pitch) != synthesis.pitch:
            synthesis.pitch = float(pitch)
            options_changed = True
        if voice_reference:
            # Supprimer l'ancienne référence si elle existe
            if synthesis.voice_reference:
                try:
                    synthesis.voice_reference.delete(save=False)
                except:
                    pass
            synthesis.voice_reference = voice_reference
            options_changed = True

        if options_changed:
            updated_options.append(synthesis.id)

        # Réinitialiser la synthèse
        synthesis.status = 'PENDING'
        synthesis.progress = 0
        synthesis.error_message = ''

        # Supprimer l'ancien audio si présent
        if synthesis.audio_output:
            try:
                synthesis.audio_output.delete(save=False)
            except:
                pass

        synthesis.save()
        cache.set(f"synthesizer_progress_{synthesis.id}", 0, timeout=3600)

        # Lancer la tâche
        task = synthesize_voice.delay(synthesis.id)
        synthesis.task_id = task.id
        synthesis.status = 'RUNNING'
        synthesis.progress = 0
        cache.set(f"synthesizer_progress_{synthesis.id}", 0, timeout=3600)
        synthesis.save(update_fields=['task_id', 'status', 'progress'])
        started.append(synthesis.id)

    return JsonResponse({
        'started_ids': started,
        'updated_options': updated_options,
        'count': len(started)
    })


@require_POST
def clear_all(request):
    """
    Supprime toutes les synthèses de l'utilisateur.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    syntheses = VoiceSynthesis.objects.filter(user=user)
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


def download_all(request):
    """
    Télécharge toutes les synthèses terminées dans un ZIP.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    syntheses = VoiceSynthesis.objects.filter(
        user=user,
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
def update_options(request, pk: int):
    """
    Met à jour les options d'une synthèse.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)

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

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    preset = VoicePreset.objects.create(
        name=name,
        description=description,
        reference_audio=reference_audio,
        language=language,
        gender=gender,
        is_public=is_public,
        created_by=user
    )

    return JsonResponse({
        'success': True,
        'preset_id': preset.id,
        'name': preset.name,
        'description': preset.description,
    })


@require_POST
def voice_preview(request):
    """
    Prépare un aperçu vocal et retourne un preview_id pour le streaming.
    """
    try:
        text_content = request.POST.get('text_content', '').strip()
        tts_model = request.POST.get('tts_model', 'xtts_v2')
        language = request.POST.get('language', 'fr')
        voice_preset = request.POST.get('voice_preset', 'male_1')
        speed = float(request.POST.get('speed', 1.0))
        pitch = float(request.POST.get('pitch', 1.0))

        if not text_content:
            return JsonResponse({
                'error': 'Le texte ne peut pas être vide'
            }, status=400)

        # Limiter le texte à environ 50 mots pour un aperçu rapide
        words = text_content.split()
        preview_words = words[:50]
        preview_text = ' '.join(preview_words)

        if len(words) > 50:
            preview_text += '...'

        # Créer un identifiant unique pour ce preview
        import hashlib
        import time
        preview_id = hashlib.md5(f"{text_content}{time.time()}".encode()).hexdigest()[:8]

        # Stocker les paramètres dans le cache pour le traitement
        cache.set(f'voice_preview_{preview_id}', {
            'text': preview_text,
            'tts_model': tts_model,
            'language': language,
            'voice_preset': voice_preset,
            'speed': speed,
            'pitch': pitch,
            'status': 'pending',
        }, timeout=300)  # 5 minutes

        from django.urls import reverse

        stream_url = reverse('synthesizer:voice_preview_stream', kwargs={'preview_id': preview_id})

        return JsonResponse({
            'status': 'ready',
            'preview_id': preview_id,
            'preview_text': preview_text,
            'word_count': len(preview_words),
            'stream_url': stream_url
        })

    except Exception as e:
        return JsonResponse({
            'error': f'Erreur lors de la génération de l\'aperçu: {str(e)}'
        }, status=500)


def voice_preview_stream(request, preview_id):
    """
    Génère et stream l'audio en temps réel via SSE (Server-Sent Events).
    """
    from django.http import StreamingHttpResponse
    import json
    import base64
    import tempfile
    import os
    import re

    logger.info(f"voice_preview_stream called with preview_id: {preview_id}")

    # Récupérer les paramètres depuis le cache
    preview_data = cache.get(f'voice_preview_{preview_id}')

    logger.info(f"Preview data from cache: {preview_data is not None}")

    if not preview_data:
        logger.error(f"Preview data not found for id: {preview_id}")
        return JsonResponse({'error': 'Preview not found or expired'}, status=404)

    def generate_audio_stream():
        """
        Générateur qui produit l'audio par chunks avec le vrai moteur TTS.
        Format SSE: data: {json}\n\n
        """
        try:
            print(f"[VOICE_PREVIEW] Starting audio stream generation for preview_id: {preview_id}", flush=True)

            # Import TTS worker functions lazily
            try:
                _ensure_workers_imported()
                print("[VOICE_PREVIEW] Worker functions imported successfully", flush=True)
            except Exception as import_error:
                error_msg = f"Failed to import TTS worker functions: {str(import_error)}"
                logger.error(error_msg)
                yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
                return

            # Marquer comme en cours
            preview_data['status'] = 'generating'
            cache.set(f'voice_preview_{preview_id}', preview_data, timeout=300)

            # Envoyer un événement de début
            yield f"data: {json.dumps({'event': 'start', 'message': 'Chargement du modèle TTS...'})}\n\n"
            logger.info("Sent start event")

            # Charger le modèle TTS
            tts_model_name = preview_data.get('tts_model', 'xtts_v2')
            logger.info(f"Loading TTS model: {tts_model_name}")

            try:
                tts = _get_tts_model(tts_model_name)
                logger.info(f"TTS model loaded successfully: {tts_model_name}")
            except Exception as model_error:
                error_msg = f"Erreur lors du chargement du modèle {tts_model_name}: {str(model_error)}"
                logger.error(error_msg)
                yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
                return

            yield f"data: {json.dumps({'event': 'progress', 'progress': 10, 'sentence': f'Modèle {tts_model_name} chargé'})}\n\n"

            # Diviser le texte en phrases
            text = preview_data['text']
            sentences = re.split(r'(?<=[.!?])\s+', text)
            sentences = [s.strip() for s in sentences if s.strip()]

            # Créer un dossier temporaire pour les fichiers audio
            temp_dir = tempfile.mkdtemp(prefix='voice_preview_')

            try:
                # Paramètres de base pour TTS
                language = preview_data.get('language', 'fr')
                voice_preset = preview_data.get('voice_preset', 'default')

                # Préparer les kwargs de base selon le modèle
                base_kwargs = {}

                # Configuration spécifique selon le modèle
                if tts_model_name == 'xtts_v2':
                    # XTTS v2 est multilingue et nécessite speaker_wav
                    base_kwargs['language'] = language
                    default_speaker = _get_default_speaker_wav(voice_preset)
                    if default_speaker and os.path.exists(default_speaker):
                        base_kwargs['speaker_wav'] = default_speaker
                        yield f"data: {json.dumps({'event': 'info', 'message': f'Voix de référence: {os.path.basename(default_speaker)}'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'event': 'error', 'message': 'XTTS v2 nécessite une voix de référence.'})}\n\n"
                        return
                else:
                    # Autres modèles (Tacotron2, etc.) : pas de paramètre language
                    # Ils utilisent leur langue par défaut
                    print(f"[VOICE_PREVIEW] Using {tts_model_name} without language parameter", flush=True)

                # Générer l'audio phrase par phrase
                audio_chunks_files = []

                for i, sentence in enumerate(sentences):
                    # Calcul de la progression
                    progress = int(10 + ((i + 1) / len(sentences)) * 80)

                    yield f"data: {json.dumps({'event': 'progress', 'progress': progress, 'sentence': sentence[:80]})}\n\n"

                    # Générer l'audio pour cette phrase
                    chunk_file = os.path.join(temp_dir, f'chunk_{i}.wav')

                    kwargs = base_kwargs.copy()
                    kwargs['text'] = sentence
                    kwargs['file_path'] = chunk_file

                    try:
                        print(f"[VOICE_PREVIEW] Generating audio for sentence {i+1}/{len(sentences)}: {sentence[:50]}...", flush=True)
                        tts.tts_to_file(**kwargs)
                        print(f"[VOICE_PREVIEW] Audio generated successfully for sentence {i+1}", flush=True)
                        audio_chunks_files.append(chunk_file)

                        # Appliquer les transformations speed et pitch
                        speed = preview_data.get('speed', 1.0)
                        pitch = preview_data.get('pitch', 1.0)

                        processed_file = chunk_file
                        if speed != 1.0 or pitch != 1.0:
                            from .utils.audio_processor import process_audio_output
                            print(f"[VOICE_PREVIEW] Applying speed={speed}, pitch={pitch}", flush=True)
                            processed_output = os.path.join(temp_dir, f'chunk_{i}_processed.wav')
                            processed_file = process_audio_output(chunk_file, speed=speed, pitch=pitch, output_path=processed_output)
                            print(f"[VOICE_PREVIEW] Audio processed", flush=True)

                        # Lire le fichier audio et l'encoder en base64
                        with open(processed_file, 'rb') as f:
                            audio_data = f.read()
                            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

                        # Envoyer le chunk audio
                        print(f"[VOICE_PREVIEW] Sending audio chunk {i+1}, size: {len(audio_base64)} bytes", flush=True)
                        yield f"data: {json.dumps({'event': 'audio', 'data': audio_base64, 'format': 'wav', 'index': i})}\n\n"
                        print(f"[VOICE_PREVIEW] Audio chunk {i+1} sent successfully", flush=True)

                    except Exception as tts_error:
                        error_msg = f"Erreur lors de la génération de la phrase {i+1}: {str(tts_error)}"
                        print(f"[VOICE_PREVIEW] ERROR: {error_msg}", flush=True)
                        yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
                        return

                # Tous les chunks sont générés
                yield f"data: {json.dumps({'event': 'progress', 'progress': 95, 'sentence': 'Finalisation...'})}\n\n"

                # Message de fin
                yield f"data: {json.dumps({'event': 'end', 'message': f'Génération terminée: {len(sentences)} phrases'})}\n\n"

            finally:
                # Nettoyage des fichiers temporaires
                import shutil
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

        except ImportError as e:
            error_msg = f"TTS library not available: {str(e)}. Install with: pip install TTS"
            logger.error(f"Import error: {error_msg}")
            yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error in voice_preview_stream: {error_details}")
            yield f"data: {json.dumps({'event': 'error', 'message': f'Erreur TTS: {str(e)}', 'details': error_details.split(chr(10))[-3:]})}\n\n"
        finally:
            logger.info(f"Stream generator completed for preview_id: {preview_id}")

    response = StreamingHttpResponse(
        generate_audio_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # Disable buffering for nginx

    return response


def list_voice_presets(request):
    """
    Liste les presets de voix disponibles.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    presets = VoicePreset.objects.filter(
        is_public=True
    ) | VoicePreset.objects.filter(created_by=user)

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
def delete_voice_preset(request, pk: int):
    """
    Supprime un preset de voix.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    preset = get_object_or_404(VoicePreset, pk=pk, created_by=user)
    preset.reference_audio.delete(save=False)
    preset.delete()

    return JsonResponse({'deleted': pk})