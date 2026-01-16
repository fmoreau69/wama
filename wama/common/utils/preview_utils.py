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
        preview_data = PreviewRegistry.get_preview_data(app_name, instance, request)
        return JsonResponse(preview_data)
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
    if not synthesis.audio_output:
        return {'error': 'No audio available'}

    audio_url = request.build_absolute_uri(synthesis.audio_output.url)

    return {
        "name": os.path.basename(synthesis.audio_output.name),
        "url": audio_url,
        "mime_type": "audio/wav",
        "duration": synthesis.duration_display if hasattr(synthesis, 'duration_display') else "",
        "properties": synthesis.properties if hasattr(synthesis, 'properties') else "",
    }


def transcriber_preview_adapter(transcript, request):
    """Custom adapter for Transcriber Transcript model."""
    if not transcript.audio_file:
        return {'error': 'No audio file available'}

    audio_url = request.build_absolute_uri(transcript.audio_file.url)
    mime_type, _ = mimetypes.guess_type(transcript.audio_file.path)

    data = {
        "name": os.path.basename(transcript.audio_file.name),
        "url": audio_url,
        "mime_type": mime_type or "audio/wav",
    }

    if hasattr(transcript, 'duration') and transcript.duration:
        data["duration"] = transcript.duration

    return data
