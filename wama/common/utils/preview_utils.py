"""
WAMA Common - Preview Utilities

Unified preview functionality for all WAMA applications.
Uses the PreviewRegistry to handle different model types.
"""

import os
import mimetypes
import logging

from django.http import HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.encoding import iri_to_uri
from django.contrib.auth.models import User

from .preview_registry import PreviewRegistry

logger = logging.getLogger(__name__)


def get_or_create_anonymous_user():
    """Get or create the anonymous user."""
    user, _ = User.objects.get_or_create(
        username='anonymous',
        defaults={'is_active': True}
    )
    return user


def _mime_category(mime):
    return (mime or '').split('/')[0]


def _output_preview_data(app_name, instance, request):
    """Payload preview du RÉSULTAT, dérivé des clés CANONIQUES du detail (`result_file`
    de build_detail — INSPECTOR_DETAIL_FIELDS.md). Zéro code par app : si l'app a un
    adapter detail avec un résultat, la preview de sortie existe. None sinon."""
    try:
        from .detail_registry import DetailRegistry
        entry = DetailRegistry.get(app_name)
        adapter = entry.get('adapter') if entry else None
        if not adapter:
            return None
        d = adapter(instance)
        url = (d or {}).get('result_file')
        if not url:
            return None
        from .mime_utils import guess_mime_type
        clean = url.split('?')[0]
        return {
            'name': os.path.basename(clean),
            'url': request.build_absolute_uri(url),
            'mime_type': guess_mime_type(clean) or 'application/octet-stream',
        }
    except Exception:
        return None


def _input_port_group(app_name):
    """Groupe du port d'ENTRÉE de l'app, lu par l'UNIQUE accesseur de ports `studio_node_ports`.

    Contrat de jonction avec le manifeste (WAMA_MANIFEST_SPEC §preview) : on ne lit JAMAIS
    `app_modes`/`app_registry` directement ici — uniquement `studio_node_ports(app_id)`. Quand le
    manifeste deviendra autoritaire, `studio_node_ports` en sera la projection et cette logique
    héritera sans changer. Règle : l'entrée bind sur le port de TRAVAIL, sinon le PROMPT —
    JAMAIS un port `reference` (la référence conditionne le traitement, elle n'EST pas l'entrée).
    """
    try:
        from wama.common.app_registry import studio_node_ports
        ports = studio_node_ports(app_name) or {}
    except Exception:
        return None
    groups = [p.get('group') for p in (ports.get('inputs') or [])]
    if 'travail' in groups:
        return 'travail'
    if 'prompt' in groups:
        return 'prompt'
    return None


def _input_preview(app_name, instance, request):
    """Face ENTRÉE de la preview, dérivée du port de travail/prompt (jamais reference).

    - port `prompt` (texte, ex. composer/synthesizer) → le PROMPT en texte inline (`content`) ;
    - port `travail` (média, ex. transcriber/imager) → l'adaptateur enregistré (fichier de travail).
    """
    if _input_port_group(app_name) == 'prompt':
        txt = (getattr(instance, 'prompt', '') or '').strip()
        return {'name': 'Prompt', 'mime_type': 'text/plain', 'content': txt} if txt else None
    return PreviewRegistry.get_preview_data(app_name, instance, request)


# ── Phase PENDANT (chantier 2) : preview progressive/temporaire pendant le traitement ──────────
# Contrat de jonction : gâté par la capacité déclarée `during_preview`/`streaming`, lue via
# l'accesseur UNIQUE `app_supports_during_preview` (comme la preview d'entrée lit les ports par
# `studio_node_ports`). Le worker de l'app publie un aperçu partiel courant via `publish_partial`
# (mécanisme = moi ; déclaration du flag + production du partiel = l'app). Dormant tant qu'aucune
# app ne déclare la capacité ET ne publie de partiel.

def _partial_key(app_name, pk):
    return f'wama_partial_preview_{app_name}_{pk}'


def _partial_peaks_key(app_name, pk):
    return f'wama_partial_peaks_{app_name}_{pk}'


def publish_partial(app_name, pk, url_or_path):
    """Worker : publie l'URL (média) d'un aperçu PARTIEL courant, servi par `?side=during`.
    TTL court (le partiel est éphémère). Appeler `clear_partial` à la fin du traitement."""
    from django.core.cache import cache
    cache.set(_partial_key(app_name, pk), str(url_or_path), 900)


def publish_partial_peaks(app_name, pk, peaks, duration=None):
    """Worker : publie des PICS d'onde partiels (« waveform par parties », cf. `waveform.compute_peaks`)
    pour le streaming « pendant » — le front dessine l'onde qui se CONSTRUIT sans re-décoder le
    fichier (effet « Suno »). Complémentaire de `publish_partial` (URL jouable). `peaks` = liste [0..1]."""
    from django.core.cache import cache
    cache.set(_partial_peaks_key(app_name, pk),
              {'peaks': list(peaks or []), 'duration': duration}, 900)


def emit_streaming_peaks(app_name, pk, pcm, sr, buckets=800):
    """Worker de streaming (COMMUN, toute app) : calcule les pics uint8 d'une fenêtre PCM courante
    (via la source unique `waveform.compute_peaks`) et les publie pour `?side=during` → l'onde se
    CONSTRUIT au fil de la génération (effet « Suno »). `pcm` = tableau/liste PCM (mono/stéréo),
    `sr` = fréquence d'échantillonnage. Ne lève jamais (best-effort — un tick raté n'arrête rien)."""
    try:
        from .waveform import compute_peaks
        peaks, duration = compute_peaks(pcm, buckets=buckets, sr=sr, dtype='uint8', with_duration=True)
        if peaks:
            publish_partial_peaks(app_name, pk, peaks, duration=duration)
    except Exception:
        pass


def clear_partial(app_name, pk):
    """Worker : retire l'aperçu partiel (fin de traitement — la face SORTIE prend le relais)."""
    from django.core.cache import cache
    cache.delete(_partial_key(app_name, pk))
    cache.delete(_partial_peaks_key(app_name, pk))


def _during_preview_data(app_name, instance, request):
    """Payload preview PENDANT le traitement : aperçu partiel publié par le worker, si l'app
    déclare la capacité. Peut porter une URL jouable (`publish_partial`) ET/OU des pics d'onde
    (`publish_partial_peaks`). None si l'app ne déclare pas la capacité ou n'a rien publié (dormant)."""
    from wama.common.app_registry import app_supports_during_preview
    if not app_supports_during_preview(app_name):
        return None
    from django.core.cache import cache
    pk = getattr(instance, 'pk', None)
    url = cache.get(_partial_key(app_name, pk))
    peaks_entry = cache.get(_partial_peaks_key(app_name, pk))
    if not url and not peaks_entry:
        return None
    data = {'partial': True}
    if url:
        from .mime_utils import guess_mime_type
        clean = str(url).split('?')[0]
        data['name'] = os.path.basename(clean) or 'partiel'
        data['url'] = request.build_absolute_uri(url) if str(url).startswith('/') else str(url)
        data['mime_type'] = guess_mime_type(clean) or 'application/octet-stream'
    else:
        # pics seuls (pas encore de fichier jouable) : onde qui se construit, mime audio générique
        data['name'] = 'partiel'
        data['mime_type'] = 'audio/*'
    if peaks_entry:
        data['peaks'] = peaks_entry.get('peaks') or []
        if peaks_entry.get('duration') is not None:
            data['duration'] = peaks_entry['duration']
    return data


def unified_preview(request, app_name: str, pk: int):
    """
    Unified preview endpoint for any registered app.

    Args:
        request: HTTP request
        app_name: The app identifier (e.g., 'anonymizer', 'describer')
        pk: Primary key of the instance

    Returns:
        JsonResponse with preview data or error
    """
    # Check if app is registered
    if not PreviewRegistry.is_registered(app_name):
        logger.warning(f"Preview requested for unregistered app: {app_name}")
        return HttpResponseNotFound(f"App '{app_name}' not registered for preview")

    # Get the model class
    model_class = PreviewRegistry.get_model(app_name)
    if not model_class:
        return HttpResponseNotFound(f"Model not found for app '{app_name}'")

    # Get the instance
    try:
        instance = get_object_or_404(model_class, pk=pk)
    except Exception as e:
        logger.error(f"Error fetching {app_name} instance {pk}: {e}")
        return HttpResponseNotFound(f"Instance not found")

    # Check permissions
    viewer = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    if not PreviewRegistry.check_permission(app_name, instance, viewer):
        return HttpResponseForbidden("You do not have access to this file.")

    # Get preview data using the registered adapter
    try:
        preview_data = _input_preview(app_name, instance, request)
        # Preview ENTRÉE/SORTIE (décision 2026-07-12, STUDIO_VISION) : ?side=output sert le
        # RÉSULTAT (clé canonique result_file du detail) ; méta `sides` additive pour que
        # l'inspecteur affiche le toggle [Entrée|Sortie] (+ slider comparatif si comparable).
        output_data = _output_preview_data(app_name, instance, request)
        during_data = _during_preview_data(app_name, instance, request)   # chantier 2 (PENDANT)
        has_input = bool(preview_data and not preview_data.get('error'))
        has_output = bool(output_data)
        cat_in = _mime_category(preview_data.get('mime_type')) if has_input else ''
        cat_out = _mime_category(output_data.get('mime_type')) if has_output else ''
        from wama.common.app_registry import app_supports_during_preview
        sides = {
            'has_input': has_input,
            'has_output': has_output,
            # slider comparatif V1 : images uniquement (vidéos = toggle seulement)
            'comparable': bool(has_input and has_output and cat_in == cat_out and cat_in == 'image'),
            # PENDANT : l'app SAIT-elle streamer (capacité) vs a-t-elle un partiel MAINTENANT
            'during_capable': app_supports_during_preview(app_name),
            'has_during': bool(during_data),
        }
        side = (request.GET.get('side') or 'input').lower()
        if side == 'during' and during_data:
            data = dict(during_data)
            data['side'] = 'during'
        elif side == 'output' and has_output:
            data = dict(output_data)
            data['side'] = 'output'
        else:
            data = dict(preview_data)
            data['side'] = 'input'
        data['sides'] = sides
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error generating preview for {app_name}/{pk}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def register_app_preview(app_name: str, model_class, file_field: str = 'input_file',
                         user_field: str = 'user', duration_field: str = None,
                         width_field: str = None, height_field: str = None,
                         properties_field: str = None):
    """
    Convenience function to register an app with common field patterns.

    This creates a simple adapter based on field names and registers it.

    Args:
        app_name: Unique identifier for the app
        model_class: The Django model class
        file_field: Name of the FileField (default: 'input_file')
        user_field: Name of the user field (default: 'user')
        duration_field: Optional name of duration field
        width_field: Optional name of width field
        height_field: Optional name of height field
        properties_field: Optional name of properties field
    """
    from .preview_registry import create_simple_adapter

    adapter = create_simple_adapter(
        file_field=file_field,
        duration_field=duration_field,
        width_field=width_field,
        height_field=height_field,
        properties_field=properties_field
    )

    PreviewRegistry.register(
        app_name=app_name,
        model_class=model_class,
        adapter=adapter,
        file_field=file_field,
        user_field=user_field
    )


# ============================================================================
# App-specific adapters (for apps that need custom logic)
# ============================================================================

def anonymizer_preview_adapter(media, request):
    """Custom adapter for Anonymizer Media model."""
    from django.utils.encoding import iri_to_uri

    media_url = request.build_absolute_uri(iri_to_uri(media.file.url))
    mime_type, _ = mimetypes.guess_type(media.file.path)

    return {
        "name": os.path.basename(media.file.name),
        "url": media_url,
        "mime_type": mime_type or "video/mp4",
        "duration": media.duration_inMinSec,
        "resolution": f"{media.width}x{media.height}" if media.width and media.height else "",
        "properties": media.properties if hasattr(media, 'properties') else "",
    }


def synthesizer_preview_adapter(synthesis, request):
    """Custom adapter for Synthesizer VoiceSynthesis model - previews audio output."""
    from django.utils.encoding import iri_to_uri

    if not synthesis.audio_output:
        return {'error': 'No audio available'}

    audio_url = request.build_absolute_uri(iri_to_uri(synthesis.audio_output.url))

    return {
        "name": os.path.basename(synthesis.audio_output.name),
        "url": audio_url,
        "mime_type": "audio/wav",
        "duration": synthesis.duration_display if hasattr(synthesis, 'duration_display') else "",
        "properties": synthesis.properties if hasattr(synthesis, 'properties') else "",
    }


def transcriber_preview_adapter(transcript, request):
    """Custom adapter for Transcriber Transcript model."""
    from django.utils.encoding import iri_to_uri

    if not transcript.audio:
        return {'error': 'No audio file available'}

    audio_url = request.build_absolute_uri(iri_to_uri(transcript.audio.url))
    mime_type, _ = mimetypes.guess_type(transcript.audio.path)

    data = {
        "name": os.path.basename(transcript.audio.name),
        "url": audio_url,
        "mime_type": mime_type or "audio/wav",
    }

    if hasattr(transcript, 'duration_display') and transcript.duration_display:
        data["duration"] = transcript.duration_display

    return data
