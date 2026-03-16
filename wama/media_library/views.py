"""
WAMA Media Library — Views
Gestion centralisée des assets réutilisables (voix, images, vidéos, documents, avatars).
"""

import mimetypes
import logging
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import UserAsset, SystemAsset, ASSET_TYPES, ALLOWED_EXTENSIONS
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

def index(request):
    user = _get_user(request)
    context = {
        'asset_types': ASSET_TYPES,
        'active_tab': request.GET.get('tab', 'voice'),
    }
    return render(request, 'media_library/index.html', context)


# ---------------------------------------------------------------------------
# API — Assets utilisateur
# ---------------------------------------------------------------------------

def api_list(request):
    """GET /media-library/api/assets/?type=voice"""
    user = _get_user(request)
    asset_type = request.GET.get('type', '')

    qs = UserAsset.objects.filter(user=user)
    if asset_type:
        qs = qs.filter(asset_type=asset_type)

    assets = [
        {
            'id':          a.id,
            'name':        a.name,
            'asset_type':  a.asset_type,
            'file_url':    a.file.url if a.file else '',
            'file_size':   a.file_size_display,
            'duration':    a.duration_display,
            'mime_type':   a.mime_type,
            'description': a.description,
            'tags':        a.tags,
            'created_at':  a.created_at.strftime('%d/%m/%Y'),
        }
        for a in qs
    ]
    return JsonResponse({'assets': assets})


@require_POST
def api_upload(request):
    """POST /media-library/api/assets/upload/"""
    user = _get_user(request)

    name       = request.POST.get('name', '').strip()
    asset_type = request.POST.get('asset_type', '').strip()
    description = request.POST.get('description', '').strip()
    tags       = request.POST.get('tags', '').strip()
    audio_file = request.FILES.get('file')

    if not name:
        return JsonResponse({'error': 'Le nom est requis'}, status=400)
    if asset_type not in dict(ASSET_TYPES):
        return JsonResponse({'error': 'Type d\'asset invalide'}, status=400)
    if not audio_file:
        return JsonResponse({'error': 'Fichier requis'}, status=400)

    # Validation de l'extension
    ext = Path(audio_file.name).suffix.lstrip('.').lower()
    allowed = ALLOWED_EXTENSIONS.get(asset_type, [])
    if ext not in allowed:
        return JsonResponse({
            'error': f'Extension .{ext} non autorisée pour ce type. Formats acceptés : {", ".join(allowed)}'
        }, status=400)

    # Unicité (user, name, asset_type)
    if UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        return JsonResponse({'error': f'Un asset "{name}" de ce type existe déjà'}, status=409)

    # Création
    asset = UserAsset.objects.create(
        user=user,
        name=name,
        asset_type=asset_type,
        file=audio_file,
        description=description,
        tags=tags,
    )

    # Remplir mime_type et file_size
    asset.mime_type = mimetypes.guess_type(audio_file.name)[0] or ''
    asset.file_size = audio_file.size
    asset.save(update_fields=['mime_type', 'file_size'])

    return JsonResponse({
        'id':         asset.id,
        'name':       asset.name,
        'asset_type': asset.asset_type,
        'file_url':   asset.file.url,
        'file_size':  asset.file_size_display,
        'duration':   asset.duration_display,
        'created_at': asset.created_at.strftime('%d/%m/%Y'),
    })


@require_POST
def api_delete(request, pk: int):
    """POST /media-library/api/assets/<pk>/delete/"""
    user = _get_user(request)
    try:
        asset = UserAsset.objects.get(pk=pk, user=user)
    except UserAsset.DoesNotExist:
        return JsonResponse({'error': 'Asset introuvable'}, status=404)

    asset.file.delete(save=False)
    asset.delete()
    return JsonResponse({'deleted': pk})


# ---------------------------------------------------------------------------
# API — Assets système
# ---------------------------------------------------------------------------

def api_system_list(request):
    """GET /media-library/api/system/?type=voice"""
    asset_type = request.GET.get('type', '')
    qs = SystemAsset.objects.filter(is_active=True)
    if asset_type:
        qs = qs.filter(asset_type=asset_type)

    assets = [
        {
            'id':          a.id,
            'name':        a.name,
            'asset_type':  a.asset_type,
            'file_url':    a.file.url if a.file else '',
            'file_size':   a.file_size_display,
            'duration':    a.duration_display,
            'mime_type':   a.mime_type,
            'description': a.description,
            'tags':        a.tags,
            'license':     a.license,
        }
        for a in qs
    ]
    return JsonResponse({'assets': assets})
