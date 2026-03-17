"""
WAMA Media Library — Views
Gestion centralisée des assets réutilisables (voix, images, vidéos, documents, avatars).
"""

import json
import mimetypes
import logging
import urllib.error
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import UserAsset, SystemAsset, MediaProvider, UserProviderConfig, ASSET_TYPES, ALLOWED_EXTENSIONS
from .providers.registry import get_provider
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)

PAGE_SIZE = 48


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _serialize_user_asset(a):
    return {
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


def _serialize_system_asset(a):
    return {
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


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

def index(request):
    tab = request.GET.get('tab', 'voice')
    context = {
        'asset_types': ASSET_TYPES,
        'active_tab':  tab,
    }
    return render(request, 'media_library/index.html', context)


# ---------------------------------------------------------------------------
# API — Compteurs par type (badges sur les onglets)
# ---------------------------------------------------------------------------

def api_counts(request):
    """GET /media-library/api/counts/"""
    user = _get_user(request)
    user_counts = dict(
        UserAsset.objects.filter(user=user)
        .values('asset_type')
        .annotate(n=Count('id'))
        .values_list('asset_type', 'n')
    )
    sys_counts = dict(
        SystemAsset.objects.filter(is_active=True)
        .values('asset_type')
        .annotate(n=Count('id'))
        .values_list('asset_type', 'n')
    )
    counts = {}
    for t, _ in ASSET_TYPES:
        counts[t] = user_counts.get(t, 0) + sys_counts.get(t, 0)
    return JsonResponse({'counts': counts})


# ---------------------------------------------------------------------------
# API — Assets utilisateur
# ---------------------------------------------------------------------------

def api_list(request):
    """GET /media-library/api/assets/?type=voice&q=fab&page=1"""
    user       = _get_user(request)
    asset_type = request.GET.get('type', '')
    q          = request.GET.get('q', '').strip()
    page       = max(1, int(request.GET.get('page', 1)))

    qs = UserAsset.objects.filter(user=user)
    if asset_type:
        qs = qs.filter(asset_type=asset_type)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(tags__icontains=q) | Q(description__icontains=q))

    total  = qs.count()
    offset = (page - 1) * PAGE_SIZE
    assets = [_serialize_user_asset(a) for a in qs[offset:offset + PAGE_SIZE]]

    return JsonResponse({
        'assets':    assets,
        'total':     total,
        'page':      page,
        'page_size': PAGE_SIZE,
        'has_more':  offset + PAGE_SIZE < total,
    })


@require_POST
def api_upload(request):
    """POST /media-library/api/assets/upload/"""
    user = _get_user(request)

    name        = request.POST.get('name', '').strip()
    asset_type  = request.POST.get('asset_type', '').strip()
    description = request.POST.get('description', '').strip()
    tags        = request.POST.get('tags', '').strip()
    file        = request.FILES.get('file')

    if not name:
        return JsonResponse({'error': 'Le nom est requis'}, status=400)
    if asset_type not in dict(ASSET_TYPES):
        return JsonResponse({'error': "Type d'asset invalide"}, status=400)
    if not file:
        return JsonResponse({'error': 'Fichier requis'}, status=400)

    ext     = Path(file.name).suffix.lstrip('.').lower()
    allowed = ALLOWED_EXTENSIONS.get(asset_type, [])
    if ext not in allowed:
        return JsonResponse({
            'error': f'Extension .{ext} non autorisée. Formats : {", ".join(allowed)}'
        }, status=400)

    if UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        return JsonResponse({'error': f'Un asset "{name}" de ce type existe déjà'}, status=409)

    asset = UserAsset.objects.create(
        user=user, name=name, asset_type=asset_type,
        file=file, description=description, tags=tags,
    )
    asset.mime_type = mimetypes.guess_type(file.name)[0] or ''
    asset.file_size = file.size
    asset.save(update_fields=['mime_type', 'file_size'])

    return JsonResponse(_serialize_user_asset(asset))


@require_POST
def api_edit(request, pk: int):
    """POST /media-library/api/assets/<pk>/edit/  — mise à jour nom/description/tags"""
    user = _get_user(request)
    try:
        asset = UserAsset.objects.get(pk=pk, user=user)
    except UserAsset.DoesNotExist:
        return JsonResponse({'error': 'Asset introuvable'}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    updated = []
    name = data.get('name', '').strip()
    if name and name != asset.name:
        if UserAsset.objects.filter(user=user, name=name, asset_type=asset.asset_type).exclude(pk=pk).exists():
            return JsonResponse({'error': f'Un asset "{name}" de ce type existe déjà'}, status=409)
        asset.name = name
        updated.append('name')

    if 'description' in data:
        asset.description = data['description'].strip()
        updated.append('description')

    if 'tags' in data:
        asset.tags = data['tags'].strip()
        updated.append('tags')

    if updated:
        asset.save(update_fields=updated)

    return JsonResponse(_serialize_user_asset(asset))


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
    """GET /media-library/api/system/?type=voice&q=homme"""
    asset_type = request.GET.get('type', '')
    q          = request.GET.get('q', '').strip()
    page       = max(1, int(request.GET.get('page', 1)))

    qs = SystemAsset.objects.filter(is_active=True)
    if asset_type:
        qs = qs.filter(asset_type=asset_type)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(tags__icontains=q) | Q(description__icontains=q))

    total  = qs.count()
    offset = (page - 1) * PAGE_SIZE
    assets = [_serialize_system_asset(a) for a in qs[offset:offset + PAGE_SIZE]]

    return JsonResponse({
        'assets':    assets,
        'total':     total,
        'page':      page,
        'has_more':  offset + PAGE_SIZE < total,
    })


# ---------------------------------------------------------------------------
# API — Providers (Phase 3)
# ---------------------------------------------------------------------------

def api_providers_list(request):
    """GET /media-library/api/providers/?type=image
    Retourne les providers actifs supportant le type donné.
    Indique si l'utilisateur a configuré une clé pour chaque provider.
    """
    asset_type = request.GET.get('type', '')
    user       = _get_user(request)

    qs = MediaProvider.objects.filter(is_active=True)
    if asset_type:
        # providers whose supported_types JSON array contains this type
        qs = [p for p in qs if asset_type in (p.supported_types or [])]
    else:
        qs = list(qs)

    # Which providers does this user have a key for?
    configured = set()
    if user.is_authenticated:
        configured = set(
            UserProviderConfig.objects.filter(user=user, is_active=True)
            .exclude(api_key='')
            .values_list('provider_id', flat=True)
        )

    result = []
    for p in qs:
        result.append({
            'slug':             p.slug,
            'name':             p.name,
            'description':      p.description,
            'supported_types':  p.supported_types,
            'requires_api_key': p.requires_api_key,
            'api_key_help_url': p.api_key_help_url,
            'api_key_label':    p.api_key_label,
            'has_key':          (not p.requires_api_key) or (p.id in configured),
        })

    return JsonResponse({'providers': result})


def api_provider_search(request):
    """GET /media-library/api/search/?provider=wikimedia&type=image&q=paris&page=1
    Appelle le provider côté serveur et retourne des SearchResult normalisés.
    Les clés API ne transitent jamais vers le navigateur.
    """
    slug       = request.GET.get('provider', '').strip()
    asset_type = request.GET.get('type', '').strip()
    q          = request.GET.get('q', '').strip()
    page       = max(1, int(request.GET.get('page', 1)))

    if not slug or not asset_type or not q:
        return JsonResponse({'error': 'provider, type et q sont requis'}, status=400)

    try:
        provider_obj = MediaProvider.objects.get(slug=slug, is_active=True)
    except MediaProvider.DoesNotExist:
        return JsonResponse({'error': f'Provider inconnu : {slug}'}, status=404)

    # Résoudre la clé API : clé user en priorité, sinon pas de clé
    api_key = ''
    if provider_obj.requires_api_key:
        user = _get_user(request)
        if user.is_authenticated:
            try:
                cfg = UserProviderConfig.objects.get(user=user, provider=provider_obj)
                api_key = cfg.api_key or ''
            except UserProviderConfig.DoesNotExist:
                pass

    provider = get_provider(slug, api_key=api_key)
    if provider is None:
        return JsonResponse({'error': f'Provider non implémenté : {slug}'}, status=501)

    data = provider.search(q, asset_type, page=page)
    results = [r.to_dict() for r in data.get('results', [])]

    return JsonResponse({
        'results':  results,
        'total':    data.get('total', 0),
        'has_more': data.get('has_more', False),
        'error':    data.get('error'),
    })


@login_required
@require_POST
def api_provider_download(request):
    """POST /media-library/api/search/download/
    Télécharge un résultat de recherche côté serveur et le sauvegarde en UserAsset.
    Body JSON:
        provider, provider_id, title, asset_type, license, author, tags
    """
    user = request.user

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    slug       = body.get('provider', '').strip()
    provider_id = body.get('provider_id', '').strip()
    title      = body.get('title', '').strip()
    asset_type = body.get('asset_type', '').strip()
    license_   = body.get('license', '')
    author     = body.get('author', '')
    tags       = body.get('tags', '')

    if not all([slug, provider_id, title, asset_type]):
        return JsonResponse({'error': 'Champs manquants : provider, provider_id, title, asset_type'}, status=400)

    if asset_type not in dict(ASSET_TYPES):
        return JsonResponse({'error': f"Type invalide : {asset_type}"}, status=400)

    try:
        provider_obj = MediaProvider.objects.get(slug=slug, is_active=True)
    except MediaProvider.DoesNotExist:
        return JsonResponse({'error': f'Provider inconnu : {slug}'}, status=404)

    # Récupérer la clé API
    api_key = ''
    if provider_obj.requires_api_key:
        try:
            cfg = UserProviderConfig.objects.get(user=user, provider=provider_obj)
            api_key = cfg.api_key or ''
        except UserProviderConfig.DoesNotExist:
            pass

    provider = get_provider(slug, api_key=api_key)
    if provider is None:
        return JsonResponse({'error': f'Provider non implémenté : {slug}'}, status=501)

    # Pour télécharger, on a besoin du download_url — on refait une recherche ciblée
    # ou on accepte que le client nous passe directement le download_url via un champ distinct.
    # Sécurité : on vérifie que l'URL provient bien d'un domaine autorisé.
    download_url = body.get('_download_url', '').strip()
    if not download_url:
        return JsonResponse({'error': '_download_url manquant'}, status=400)

    # Whitelist de domaines autorisés selon le provider
    _DOMAIN_WHITELIST = {
        'wikimedia': ['upload.wikimedia.org', 'commons.wikimedia.org'],
        'pixabay':   ['cdn.pixabay.com', 'i.vimeocdn.com', 'player.vimeo.com'],
        'freesound': ['cdn.freesound.org'],
    }
    from urllib.parse import urlparse
    parsed_domain = urlparse(download_url).netloc
    allowed_domains = _DOMAIN_WHITELIST.get(slug, [])
    if allowed_domains and not any(parsed_domain.endswith(d) for d in allowed_domains):
        return JsonResponse({'error': f'Domaine non autorisé : {parsed_domain}'}, status=403)

    # Nom unique : "titre — auteur (provider)"
    asset_name = f"{title[:150]}"
    if UserAsset.objects.filter(user=user, name=asset_name, asset_type=asset_type).exists():
        return JsonResponse({'error': f'Un asset "{asset_name}" de ce type existe déjà'}, status=409)

    # Téléchargement serveur-side
    try:
        file_bytes = provider.download_bytes(download_url)
    except urllib.error.HTTPError as e:
        return JsonResponse({'error': f'Erreur HTTP {e.code} lors du téléchargement'}, status=502)
    except Exception as e:
        return JsonResponse({'error': f'Téléchargement échoué : {e}'}, status=502)

    # Extension depuis l'URL
    url_path = urlparse(download_url).path
    ext = Path(url_path).suffix.lstrip('.').lower() or ALLOWED_EXTENSIONS.get(asset_type, ['bin'])[0]

    file_name = f"{asset_name[:100]}.{ext}"
    content   = ContentFile(file_bytes, name=file_name)
    mime_type = mimetypes.guess_type(file_name)[0] or ''

    # Enrichir les tags avec licence et auteur
    extra_tags = [t for t in [license_, author, slug] if t]
    full_tags  = ', '.join(filter(None, [tags] + extra_tags))[:500]

    asset = UserAsset.objects.create(
        user=user, name=asset_name, asset_type=asset_type,
        file=content, description=f'Source : {slug} (CC : {license_})',
        tags=full_tags,
    )
    asset.mime_type = mime_type
    asset.file_size = len(file_bytes)
    asset.save(update_fields=['mime_type', 'file_size'])

    return JsonResponse(_serialize_user_asset(asset))


# ---------------------------------------------------------------------------
# API — Gestion des clés provider (profil utilisateur)
# ---------------------------------------------------------------------------

@login_required
def api_provider_keys(request):
    """GET /media-library/api/providers/keys/
    Retourne la liste des providers avec indication si une clé est configurée.
    (Jamais la clé elle-même.)
    """
    providers = MediaProvider.objects.filter(is_active=True, requires_api_key=True)
    configured = {
        cfg.provider_id: True
        for cfg in UserProviderConfig.objects.filter(
            user=request.user, is_active=True
        ).exclude(api_key='')
    }
    result = []
    for p in providers:
        result.append({
            'slug':             p.slug,
            'name':             p.name,
            'api_key_label':    p.api_key_label,
            'api_key_help_url': p.api_key_help_url,
            'has_key':          p.id in configured,
        })
    return JsonResponse({'providers': result})


@login_required
@require_POST
def api_provider_key_save(request, slug: str):
    """POST /media-library/api/providers/<slug>/key/
    Sauvegarde ou efface la clé API d'un provider pour l'utilisateur courant.
    Body JSON: {api_key: '...'} — vide = supprime la clé
    """
    try:
        provider_obj = MediaProvider.objects.get(slug=slug, is_active=True)
    except MediaProvider.DoesNotExist:
        return JsonResponse({'error': 'Provider introuvable'}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    api_key = data.get('api_key', '').strip()
    cfg, _ = UserProviderConfig.objects.get_or_create(
        user=request.user, provider=provider_obj,
    )
    cfg.api_key  = api_key
    cfg.is_active = True
    cfg.save(update_fields=['api_key', 'is_active', 'updated_at'])

    return JsonResponse({'success': True, 'has_key': bool(api_key)})
