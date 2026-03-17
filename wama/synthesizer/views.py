"""
WAMA Synthesizer - Views
Interface de synthèse vocale
"""

import os
import io
import zipfile
import logging
from pathlib import Path
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.views.generic import TemplateView
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str, iri_to_uri
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

import requests as http_requests

from .models import VoiceSynthesis, VoicePreset, CustomVoice, BatchSynthesis, BatchSynthesisItem
from wama.common.utils.console_utils import get_console_lines
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance

logger = logging.getLogger(__name__)

# TTS microservice URL
TTS_SERVICE_URL = getattr(settings, 'TTS_SERVICE_URL', 'http://localhost:8001')

# Lazy import for Celery task (avoids importing heavy TTS libs at Gunicorn startup)
synthesize_voice = None

def _ensure_workers_imported():
    """Lazy import of synthesize_voice Celery task."""
    global synthesize_voice
    if synthesize_voice is None:
        from .workers import synthesize_voice as sv
        synthesize_voice = sv


def _wrap_synthesis_in_batch(synthesis):
    """Wrap a standalone VoiceSynthesis in a new BatchSynthesis-of-1."""
    stem = os.path.splitext(os.path.basename(synthesis.text_file.name))[0] if synthesis.text_file else f'synthesis_{synthesis.id}'
    output_filename = stem + '.wav'
    batch = BatchSynthesis.objects.create(user=synthesis.user, total=1)
    BatchSynthesisItem.objects.create(
        batch=batch,
        synthesis=synthesis,
        output_filename=output_filename,
        row_index=0,
    )
    return batch


def _auto_wrap_orphans(user):
    """Lazily wrap any VoiceSynthesis not yet in a batch into a batch-of-1 (on page load)."""
    existing_batch_ids = set(
        BatchSynthesisItem.objects.filter(batch__user=user)
        .values_list('synthesis_id', flat=True)
    )
    orphans = VoiceSynthesis.objects.filter(user=user).exclude(id__in=existing_batch_ids)
    for orphan in orphans:
        try:
            _wrap_synthesis_in_batch(orphan)
        except Exception:
            pass


class IndexView(View):
    """Page principale du synthesizer."""

    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily migrate any orphan VoiceSynthesis into a batch-of-1
        _auto_wrap_orphans(user)

        # All batches with prefetched items+synthesis
        batches_qs = BatchSynthesis.objects.filter(user=user).prefetch_related(
            'items__synthesis'
        ).order_by('-id')

        batches_list = []
        for batch in batches_qs:
            items = list(batch.items.all())
            success_count = sum(1 for i in items if i.synthesis and i.synthesis.status == 'SUCCESS')
            first_s = items[0].synthesis if items else None
            batches_list.append({
                'obj': batch,
                'items': items,
                'success_count': success_count,
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'has_success': success_count > 0,
                'first_tts_model': first_s.tts_model if first_s else 'xtts_v2',
                'first_language': first_s.language if first_s else 'fr',
                'first_voice_preset': first_s.voice_preset if first_s else 'default',
                'first_speed': first_s.speed if first_s else 1.0,
                'first_pitch': first_s.pitch if first_s else 1.0,
            })

        queue_count = sum(len(b['items']) for b in batches_list)

        voice_presets = VoicePreset.objects.filter(
            is_public=True
        ) | VoicePreset.objects.filter(created_by=user)
        from wama.media_library.models import UserAsset
        custom_voices = UserAsset.objects.filter(user=user, asset_type='voice')

        # Scan voice references folder for dynamic dropdown
        from wama.synthesizer.utils.voice_utils import scan_voice_refs, needs_voice_download
        voice_refs_groups = scan_voice_refs()

        # Téléchargement automatique en fond si des voix manquent (une seule fois par heure)
        if needs_voice_download():
            _dl_flag = 'voice_refs_download_triggered'
            if not cache.get(_dl_flag):
                cache.set(_dl_flag, True, timeout=3600)
                try:
                    from .workers import download_voice_refs_task
                    download_voice_refs_task.delay()
                    logger.info("[Synthesizer] Téléchargement des voix de référence lancé en arrière-plan")
                except Exception as exc:
                    logger.warning(f"[Synthesizer] Impossible de lancer le téléchargement des voix : {exc}")

        context = {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'voice_presets': voice_presets,
            'custom_voices': custom_voices,
            'tts_models': VoiceSynthesis.TTS_MODEL_CHOICES,
            'languages': VoiceSynthesis.LANGUAGE_CHOICES,
            'voice_presets_choices': VoiceSynthesis.VOICE_PRESET_CHOICES,
            'voice_refs_groups': voice_refs_groups,
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
            # Higgs Audio specific options
            multi_speaker = request.POST.get('multi_speaker', '0') == '1'
            scene_description = request.POST.get('scene_description', '')
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
            voice_reference=voice_reference,
            multi_speaker=multi_speaker,
            scene_description=scene_description,
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

        _wrap_synthesis_in_batch(synthesis)

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
            # Higgs Audio specific options
            multi_speaker = request.POST.get('multi_speaker', '0') == '1'
            scene_description = request.POST.get('scene_description', '')
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
            voice_reference=voice_reference,
            multi_speaker=multi_speaker,
            scene_description=scene_description,
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

        _wrap_synthesis_in_batch(synthesis)

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


def synthesis_card_html(request, pk: int):
    """
    Renders a single synthesis card as HTML fragment.
    Used by the polling loop to update a card in-place on completion (no full page reload).
    """
    from django.template.loader import render_to_string
    from django.http import HttpResponse
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)
    html = render_to_string('synthesizer/_synthesis_card.html', {'synthesis': synthesis}, request=request)
    return HttpResponse(html)


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
        'audio_url': iri_to_uri(synthesis.audio_output.url) if synthesis.audio_output else None,
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
        filename=os.path.basename(synthesis.audio_output.name)
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
        'audio_url': iri_to_uri(synthesis.audio_output.url),
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

    # Capture parent batch before deletion (cascade will remove the BatchSynthesisItem)
    parent_batch = None
    try:
        parent_batch = synthesis.batch_item.batch
    except Exception:
        pass

    # Révoquer la tâche Celery si elle est en file ou en cours (libère le worker GPU)
    if synthesis.task_id:
        try:
            from celery.result import AsyncResult
            AsyncResult(synthesis.task_id).revoke(terminate=False)
        except Exception:
            pass

    # Input files may be shared with duplicates — only delete if no other row references them
    safe_delete_file(synthesis, 'text_file')
    safe_delete_file(synthesis, 'voice_reference')

    # Output file is always unique to this synthesis — delete unconditionally
    if synthesis.audio_output:
        try:
            synthesis.audio_output.delete(save=False)
        except Exception:
            pass

    synthesis.delete()
    cache.delete(f"synthesizer_progress_{pk}")

    # Clean up empty parent batch (cascade deleted its BatchSynthesisItem above)
    if parent_batch:
        try:
            if not parent_batch.items.exists():
                parent_batch.delete()
        except Exception:
            pass

    return JsonResponse({'deleted': pk})


@require_POST
def duplicate(request, pk: int):
    """Duplicate a VoiceSynthesis sharing the same text_file, resetting all results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    synthesis = get_object_or_404(VoiceSynthesis, pk=pk, user=user)
    new_s = duplicate_instance(
        synthesis,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'properties': '',
            'error_message': '',
        },
        clear_fields=['audio_output'],
    )
    _wrap_synthesis_in_batch(new_s)
    return JsonResponse({'duplicated': new_s.id})


# ============================================================================
# Custom Voices — délégué à media_library.UserAsset (type='voice')
# Les routes /custom-voices/ sont conservées pour la compat avec le JS existant.
# ============================================================================

def list_custom_voices(request):
    """Liste les voix personnalisées de l'utilisateur (via UserAsset)."""
    from wama.media_library.models import UserAsset
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    assets = UserAsset.objects.filter(user=user, asset_type='voice').values('id', 'name', 'created_at')
    return JsonResponse({'voices': [
        {'id': a['id'], 'name': a['name'], 'created_at': a['created_at'].strftime('%d/%m/%Y')}
        for a in assets
    ]})


@require_POST
def upload_custom_voice(request):
    """Upload d'une voix personnalisée (crée un UserAsset de type voice)."""
    import mimetypes as _mime
    from wama.media_library.models import UserAsset
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    name  = request.POST.get('name', '').strip()
    audio = request.FILES.get('audio')

    if not name:
        return JsonResponse({'error': 'Le nom est requis'}, status=400)
    if not audio:
        return JsonResponse({'error': 'Le fichier audio est requis'}, status=400)

    ext = os.path.splitext(audio.name)[1][1:].lower()
    if ext not in ('wav', 'mp3', 'flac', 'ogg'):
        return JsonResponse({'error': 'Format non supporté (wav, mp3, flac, ogg)'}, status=400)

    if UserAsset.objects.filter(user=user, name=name, asset_type='voice').exists():
        return JsonResponse({'error': f'Une voix "{name}" existe déjà'}, status=409)

    asset = UserAsset.objects.create(user=user, name=name, asset_type='voice', file=audio)
    asset.mime_type = _mime.guess_type(audio.name)[0] or ''
    asset.file_size = audio.size
    asset.save(update_fields=['mime_type', 'file_size'])
    return JsonResponse({'id': asset.id, 'name': asset.name})


@require_POST
def delete_custom_voice(request, pk: int):
    """Supprime une voix personnalisée (UserAsset)."""
    from wama.media_library.models import UserAsset
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    asset = get_object_or_404(UserAsset, pk=pk, user=user, asset_type='voice')
    asset.file.delete(save=False)
    asset.delete()
    return JsonResponse({'deleted': pk})


def console_content(request):
    """
    Récupère le contenu de la console.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


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
        multi_speaker_raw = request.POST.get('multi_speaker')
        scene_description_raw = request.POST.get('scene_description')
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
        if multi_speaker_raw is not None:
            new_ms = multi_speaker_raw == '1'
            if synthesis.multi_speaker != new_ms:
                synthesis.multi_speaker = new_ms
                options_changed = True
        if scene_description_raw is not None and synthesis.scene_description != scene_description_raw:
            synthesis.scene_description = scene_description_raw
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

        # Révoquer la tâche Celery si présente
        if synthesis.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(synthesis.task_id).revoke(terminate=False)
            except Exception:
                pass

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

    # Also remove all batch containers (BatchSynthesisItems cascade-deleted with syntheses above)
    BatchSynthesis.objects.filter(user=user).delete()

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
    if 'multi_speaker' in request.POST:
        synthesis.multi_speaker = request.POST['multi_speaker'] == '1'
    if 'scene_description' in request.POST:
        synthesis.scene_description = request.POST['scene_description']

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


@require_POST
def import_individual_from_path(request):
    """
    Create a single VoiceSynthesis from a file already on the server (server_path relative to MEDIA_ROOT).
    Used when a batch file from FileManager is chosen for individual synthesis instead.
    """
    from django.conf import settings as django_settings

    server_path = request.POST.get('server_path', '').strip()
    if not server_path:
        return JsonResponse({'error': 'server_path requis'}, status=400)

    abs_path = Path(django_settings.MEDIA_ROOT) / server_path
    if not abs_path.exists():
        return JsonResponse({'error': 'Fichier introuvable'}, status=404)

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    synthesis = VoiceSynthesis.objects.create(
        user=user,
        tts_model=request.POST.get('tts_model', 'xtts_v2'),
        language=request.POST.get('language', 'fr'),
        voice_preset=request.POST.get('voice_preset', 'default'),
        speed=float(request.POST.get('speed', 1.0)),
        pitch=float(request.POST.get('pitch', 1.0)),
        emotion_intensity=1.0,
    )
    synthesis.text_file.name = server_path
    synthesis.save()

    try:
        from .utils.text_extractor import extract_text_from_file, clean_text_for_tts
        text_content = extract_text_from_file(str(abs_path))
        synthesis.text_content = clean_text_for_tts(text_content)
        synthesis.update_metadata()
    except Exception:
        synthesis.text_content = ''
        synthesis.word_count = 0
        synthesis.save()

    _wrap_synthesis_in_batch(synthesis)

    return JsonResponse({'success': True, 'id': synthesis.id})


# ============= BATCH SYNTHESIS =============

def batch_template(request):
    """Download a batch file template (.txt)."""
    template = """# WAMA Synthesizer - Batch Synthesis
# Format : nom_fichier|texte à synthétiser|voix|vitesse
# Les colonnes voix et vitesse sont optionnelles.
# Les lignes commençant par # sont des commentaires.

# --- Exemples avec tous les paramètres ---
consigne_1.wav|Bonjour, veuillez vous installer confortablement dans le simulateur.|default|1.0
consigne_2.wav|Ajustez le siège et les rétroviseurs selon vos préférences.|male_1|0.95

# --- Exemples sans voix ni vitesse (valeurs par défaut) ---
consigne_3.wav|L'expérimentation va débuter dans 30 secondes.
pause.wav|Vous pouvez faire une pause de 5 minutes.

# --- Fin ---
fin.wav|L'expérimentation est terminée. Merci de votre participation !|female_1|1.0
"""
    response = HttpResponse(template, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """
    Parse a batch file and return the task list for preview (no DB entries created).
    """
    import tempfile

    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    ext = os.path.splitext(batch_file.name)[1][1:].lower()
    if ext not in ('txt', 'pdf', 'docx', 'csv', 'md'):
        return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)

    default_voice = request.POST.get('default_voice', 'default')
    try:
        default_speed = float(request.POST.get('default_speed', 1.0))
    except (ValueError, TypeError):
        default_speed = 1.0

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in batch_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        from .utils.batch_parser import parse_batch_file
        tasks, warnings = parse_batch_file(
            tmp_path, default_voice=default_voice, default_speed=default_speed
        )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return JsonResponse({
        'tasks': tasks,
        'warnings': warnings,
        'count': len(tasks),
    })


@require_POST
def batch_create(request):
    """
    Parse batch file, create BatchSynthesis + VoiceSynthesis entries.
    Returns batch_id and list of synthesis IDs.
    Accepts either a `batch_file` upload or a `server_path` (relative to MEDIA_ROOT)
    for files already on the server (e.g. imported from FileManager).
    """
    import tempfile
    import datetime
    from django.conf import settings as django_settings

    batch_file = request.FILES.get('batch_file')
    server_path = request.POST.get('server_path', '').strip()

    if not batch_file and not server_path:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    # Global synthesis settings from the right panel
    tts_model = request.POST.get('tts_model', 'xtts_v2')
    language = request.POST.get('language', 'fr')
    default_voice = request.POST.get('voice_preset', 'default')
    try:
        default_speed = float(request.POST.get('speed', 1.0))
        default_pitch = float(request.POST.get('pitch', 1.0))
    except (ValueError, TypeError):
        default_speed = 1.0
        default_pitch = 1.0

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    tmp_path = None
    try:
        if server_path:
            # File already on server (e.g. imported from FileManager) — parse directly
            abs_path = Path(django_settings.MEDIA_ROOT) / server_path
            if not abs_path.exists():
                return JsonResponse({'error': 'Fichier introuvable sur le serveur'}, status=404)
            ext = abs_path.suffix[1:].lower()
            if ext not in ('txt', 'pdf', 'docx', 'csv', 'md'):
                return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)
            from .utils.batch_parser import parse_batch_file
            tasks, warnings = parse_batch_file(
                str(abs_path), default_voice=default_voice, default_speed=default_speed
            )
        else:
            ext = os.path.splitext(batch_file.name)[1][1:].lower()
            if ext not in ('txt', 'pdf', 'docx', 'csv', 'md'):
                return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
                for chunk in batch_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            from .utils.batch_parser import parse_batch_file
            tasks, warnings = parse_batch_file(
                tmp_path, default_voice=default_voice, default_speed=default_speed
            )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not tasks:
        return JsonResponse({'error': 'Aucune tâche valide trouvée dans le fichier'}, status=400)

    # Save the batch file reference
    if batch_file:
        batch_file.seek(0)
    batch = BatchSynthesis.objects.create(
        user=user,
        total=len(tasks),
        batch_file=batch_file if batch_file else None,
    )

    created_ids = []
    for i, task in enumerate(tasks):
        # Create a text ContentFile named after the desired output (with .txt extension)
        stem = os.path.splitext(task['output_filename'])[0]
        text_filename = stem + '.txt'
        text_file_content = ContentFile(
            task['text'].encode('utf-8'), name=text_filename
        )

        synthesis = VoiceSynthesis.objects.create(
            user=user,
            text_file=text_file_content,
            text_content=task['text'],
            tts_model=tts_model,
            language=language,
            voice_preset=task['voice'],
            speed=task['speed'],
            pitch=default_pitch,
        )
        synthesis.update_metadata()

        BatchSynthesisItem.objects.create(
            batch=batch,
            synthesis=synthesis,
            output_filename=task['output_filename'],
            row_index=i,
        )
        created_ids.append(synthesis.id)

    return JsonResponse({
        'batch_id': batch.id,
        'synthesis_ids': created_ids,
        'total': len(tasks),
        'warnings': warnings,
    })


@require_POST
def batch_start(request, pk: int):
    """Start all PENDING syntheses in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchSynthesis, pk=pk, user=user)

    _ensure_workers_imported()

    started = []
    for item in batch.items.select_related('synthesis').all():
        synthesis = item.synthesis
        if not synthesis or synthesis.status == 'RUNNING':
            continue

        synthesis.status = 'PENDING'
        synthesis.progress = 0
        synthesis.error_message = ''
        if synthesis.audio_output:
            try:
                synthesis.audio_output.delete(save=False)
            except Exception:
                pass
        synthesis.save(update_fields=['status', 'progress', 'error_message', 'audio_output'])
        cache.set(f"synthesizer_progress_{synthesis.id}", 0, timeout=3600)

        task = synthesize_voice.delay(synthesis.id)
        synthesis.task_id = task.id
        synthesis.status = 'RUNNING'
        synthesis.save(update_fields=['task_id', 'status'])
        started.append(synthesis.id)

    return JsonResponse({'started': started, 'count': len(started)})


def batch_status(request, pk: int):
    """Return status of all items in a batch."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchSynthesis, pk=pk, user=user)

    counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
    items_data = []

    for item in batch.items.select_related('synthesis').all():
        s = item.synthesis
        if not s:
            continue
        key = s.status.lower()
        counts[key] = counts.get(key, 0) + 1
        p = int(cache.get(f"synthesizer_progress_{s.id}", s.progress or 0))
        items_data.append({
            'id': s.id,
            'output_filename': item.output_filename,
            'status': s.status,
            'progress': p,
            'audio_url': iri_to_uri(s.audio_output.url) if s.audio_output else None,
            'error': s.error_message if s.status == 'FAILURE' else None,
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


def batch_download(request, pk: int):
    """Download a ZIP of all completed syntheses in a batch, with the original filenames."""
    import datetime
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchSynthesis, pk=pk, user=user)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in batch.items.select_related('synthesis').order_by('row_index'):
            s = item.synthesis
            if s and s.status == 'SUCCESS' and s.audio_output:
                with s.audio_output.open('rb') as audio_file:
                    archive.writestr(item.output_filename, audio_file.read())

    buffer.seek(0)
    zip_name = f"batch_{pk}_{datetime.date.today()}.zip"
    return FileResponse(buffer, as_attachment=True, filename=zip_name)


def batch_list(request):
    """List the current user's batches with status counts."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchSynthesis.objects.filter(user=user).prefetch_related('items__synthesis')

    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for item in batch.items.all():
            if item.synthesis:
                k = item.synthesis.status.lower()
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
def batch_delete(request, pk: int):
    """Delete an entire batch: revoke tasks, delete files, cascade-delete."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchSynthesis, pk=pk, user=user)

    # Collect synthesis objects and revoke tasks before cascade delete
    syntheses_to_delete = []
    for item in batch.items.select_related('synthesis').all():
        s = item.synthesis
        if not s:
            continue
        if s.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(s.task_id).revoke(terminate=False)
            except Exception:
                pass
        syntheses_to_delete.append(s)

    # batch_file may be shared with a duplicate batch — check refs before deleting
    safe_delete_file(batch, 'batch_file')

    batch.delete()  # CASCADE deletes BatchSynthesisItems (not VoiceSynthesis)

    for s in syntheses_to_delete:
        # Input files may be shared with duplicate items — check refs before deleting
        safe_delete_file(s, 'text_file')
        safe_delete_file(s, 'voice_reference')
        # Output file is always unique to this item
        if s.audio_output:
            try:
                s.audio_output.delete(save=False)
            except Exception:
                pass
        cache.delete(f"synthesizer_progress_{s.id}")
        s.delete()

    return JsonResponse({'success': True, 'batch_id': pk})


@require_POST
def batch_duplicate(request, pk: int):
    """Duplicate an entire batch (shares source files, results cleared)."""
    from wama.common.utils.batch_utils import duplicate_synthesizer_batch
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchSynthesis, pk=pk, user=user)
    new_batch = duplicate_synthesizer_batch(batch)
    return JsonResponse({'success': True, 'batch_id': new_batch.id})


@require_POST
def batch_update_settings(request, pk: int):
    """Update TTS settings for all non-running items in a batch."""
    import json as _json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = get_object_or_404(BatchSynthesis, pk=pk, user=user)

    data = _json.loads(request.body)
    tts_model = data.get('tts_model', '').strip()
    language = data.get('language', '').strip()
    voice_preset = data.get('voice_preset', '').strip()
    try:
        speed = float(data.get('speed', 1.0))
        pitch = float(data.get('pitch', 1.0))
    except (ValueError, TypeError):
        speed = 1.0
        pitch = 1.0

    updated = 0
    for item in batch.items.select_related('synthesis').all():
        s = item.synthesis
        if not s or s.status == 'RUNNING':
            continue
        update_fields = []
        if tts_model:
            s.tts_model = tts_model
            update_fields.append('tts_model')
        if language:
            s.language = language
            update_fields.append('language')
        if voice_preset:
            s.voice_preset = voice_preset
            update_fields.append('voice_preset')
        s.speed = speed
        s.pitch = pitch
        update_fields.extend(['speed', 'pitch'])
        if update_fields:
            s.save(update_fields=update_fields)
            updated += 1

    return JsonResponse({'success': True, 'updated': updated})


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
    Uses the TTS microservice for instant generation (model already preloaded).
    """
    from django.http import StreamingHttpResponse
    import json
    import base64
    import re

    logger.info(f"voice_preview_stream called with preview_id: {preview_id}")

    # Récupérer les paramètres depuis le cache
    preview_data = cache.get(f'voice_preview_{preview_id}')

    if not preview_data:
        logger.error(f"Preview data not found for id: {preview_id}")
        return JsonResponse({'error': 'Preview not found or expired'}, status=404)

    def generate_audio_stream():
        """
        Générateur qui produit l'audio par chunks via le TTS microservice.
        Format SSE: data: {json}\n\n
        """
        try:
            # Marquer comme en cours
            preview_data['status'] = 'generating'
            cache.set(f'voice_preview_{preview_id}', preview_data, timeout=300)

            # Envoyer un événement de début
            yield f"data: {json.dumps({'event': 'start', 'message': 'Génération audio...'})}\n\n"

            tts_model_name = preview_data.get('tts_model', 'xtts_v2')
            language = preview_data.get('language', 'fr')
            voice_preset = preview_data.get('voice_preset', 'default')
            speed = preview_data.get('speed', 1.0)
            pitch = preview_data.get('pitch', 1.0)

            yield f"data: {json.dumps({'event': 'progress', 'progress': 10, 'sentence': f'Modèle {tts_model_name} (service TTS)'})}\n\n"

            # Diviser le texte en phrases
            text = preview_data['text']
            sentences = re.split(r'(?<=[.!?])\s+', text)
            sentences = [s.strip() for s in sentences if s.strip()]

            # Générer l'audio phrase par phrase via le TTS service
            for i, sentence in enumerate(sentences):
                progress = int(10 + ((i + 1) / len(sentences)) * 80)
                yield f"data: {json.dumps({'event': 'progress', 'progress': progress, 'sentence': sentence[:80]})}\n\n"

                try:
                    # Call TTS microservice
                    resp = http_requests.post(
                        f"{TTS_SERVICE_URL}/tts",
                        json={
                            'text': sentence,
                            'model': tts_model_name,
                            'language': language,
                            'voice_preset': voice_preset,
                        },
                        timeout=60,
                    )
                    resp.raise_for_status()
                    wav_bytes = resp.content

                    # Apply speed/pitch post-processing if needed
                    if speed != 1.0 or pitch != 1.0:
                        import tempfile
                        from .utils.audio_processor import process_audio_output
                        tmp_in = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                        tmp_in.write(wav_bytes)
                        tmp_in.close()
                        processed_path = process_audio_output(tmp_in.name, speed=speed, pitch=pitch)
                        with open(processed_path, 'rb') as pf:
                            wav_bytes = pf.read()
                        # Cleanup
                        for p in [tmp_in.name, processed_path]:
                            try:
                                os.remove(p)
                            except OSError:
                                pass

                    audio_base64 = base64.b64encode(wav_bytes).decode('utf-8')
                    yield f"data: {json.dumps({'event': 'audio', 'data': audio_base64, 'format': 'wav', 'index': i})}\n\n"

                except http_requests.ConnectionError:
                    yield f"data: {json.dumps({'event': 'error', 'message': f'Service TTS indisponible ({TTS_SERVICE_URL}). Vérifiez que le service est démarré.'})}\n\n"
                    return
                except http_requests.HTTPError as e:
                    detail = ""
                    try:
                        detail = e.response.json().get("detail", "")
                    except Exception:
                        detail = str(e)
                    yield f"data: {json.dumps({'event': 'error', 'message': f'Erreur TTS: {detail}'})}\n\n"
                    return
                except Exception as tts_error:
                    yield f"data: {json.dumps({'event': 'error', 'message': f'Erreur génération phrase {i+1}: {str(tts_error)}'})}\n\n"
                    return

            yield f"data: {json.dumps({'event': 'progress', 'progress': 95, 'sentence': 'Finalisation...'})}\n\n"
            yield f"data: {json.dumps({'event': 'end', 'message': f'Génération terminée: {len(sentences)} phrases'})}\n\n"

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error in voice_preview_stream: {error_details}")
            yield f"data: {json.dumps({'event': 'error', 'message': f'Erreur: {str(e)}'})}\n\n"
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