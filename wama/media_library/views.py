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

from wama.common.utils.volet import VOLET_AUCUN

from .models import (UserAsset, SystemAsset, MediaProvider, UserProviderConfig, PromptKeyword,
                     ASSET_TYPES, ALLOWED_EXTENSIONS, TYPE_GROUPS)
from .natures import natures_as_json
from .providers.registry import get_provider
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)

PAGE_SIZE = 48


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


#: Portée d'une LECTURE de la médiathèque.
#:   `mine`    — mes assets. Défaut, et contrat du SÉLECTEUR de médias des apps.
#:   `visible` — les miens ET ce qui m'est partagé (unité, projet, public) : la page médiathèque.
#: Le défaut reste `mine` parce que `api_list` sert AUSSI `media-picker.js` (imager, imager_01,
#: avatarizer) : élargir sans le dire ferait entrer l'asset d'autrui dans leur sélecteur de
#: fichier, en silence. La portée se DEMANDE, elle ne se devine pas.
SCOPE_MINE, SCOPE_VISIBLE = 'mine', 'visible'


def _readable_assets(request, user):
    """Queryset des assets LISIBLES selon la portée demandée (`?scope=`).

    La garde du compte de service anonyme vit dans `common/utils/scoping.listable_by` depuis le
    2026-09-22 : elle était recopiée ici et dans les voix de clonage.
    """
    from wama.common.utils.scoping import listable_by
    scope = request.GET.get('scope') or SCOPE_MINE
    if scope == SCOPE_VISIBLE:
        return listable_by(UserAsset.objects.all(), user)
    return UserAsset.objects.owned_by(user)


def _serialize_user_asset(a, user=None):
    """⚠ `is_mine` et `owner` ne sont pas décoratifs : depuis qu'une lecture peut rendre l'asset
    d'un autre, une card sans eux serait indiscernable de la mienne — et l'interface offrirait
    « Modifier » et « Supprimer » sur un objet que le serveur refusera (404)."""
    return {
        'id':          a.id,
        'name':        a.name,
        'asset_type':  a.asset_type,
        'visibility':  a.visibility,
        'is_mine':     bool(user is not None and a.user_id == getattr(user, 'id', None)),
        'owner':       a.user.username if a.user_id else '',
        'file_url':    a.file.url if a.file else '',
        'file_size':   a.file_size_display,
        'duration':    a.duration_display,
        'mime_type':   a.mime_type,
        'description': a.description,
        'tags':        a.tags,
        'attributes':  a.attributes or {},
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
        'attributes':  a.attributes or {},
        'license':     a.license,
    }


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

def index(request):
    tab = request.GET.get('tab', 'voice')
    # Compteur de mots-clés visibles (tronc commun partagé + perso de l'utilisateur).
    kw_filter = Q(user__isnull=True)
    if request.user.is_authenticated:
        kw_filter |= Q(user=request.user)
    keyword_count = PromptKeyword.objects.filter(kw_filter).count()
    context = {
        'asset_types':   ASSET_TYPES,
        'active_tab':    tab,
        'keyword_count': keyword_count,
        # Source unique du regroupement « audio » (voice/audio_music/audio_sfx) — consommée ici
        # par le JS de la page (affichage lecteur audio) ET par le picker (`TYPE_GROUPS` dans
        # `models.py`, filtrage serveur). Avant 2026-07-09 : dupliqué en dur (`AUDIO_TYPES` codé
        # dans media-library.js) — retiré, ne reste que cette source.
        'audio_types_json': json.dumps(TYPE_GROUPS['audio']),
        # La DÉCLARATION des natures (libellé, icône, formats admis, schéma d'attributs) : le JS
        # de la page en dérive ses trois tables au lieu de les recopier (A′, 2026-09-13).
        'natures_json': json.dumps(natures_as_json()),
        # La médiathèque a sa PROPRE mise en page (grille + onglets) et son propre aperçu :
        # le volet n'y portait que 3 cadres vides (WAMA_VOLETS §2). ⚠ Elle expose un index,
        # donc `discoverable_apps()` la voit — mais ce n'est PAS une app du catalogue, d'où
        # son absence du test de non-régression des 10 apps (`tests_volet.PagesDAppTest`).
        'volet': VOLET_AUCUN,
    }
    return render(request, 'media_library/index.html', context)


# ---------------------------------------------------------------------------
# API — Compteurs par type (badges sur les onglets)
# ---------------------------------------------------------------------------

def api_counts(request):
    """GET /media-library/api/counts/"""
    user = _get_user(request)
    # Même portée que la grille : un badge qui compte autre chose que ce que la page affiche
    # est un mensonge silencieux (`?scope=` est donc lu ici AUSSI).
    user_counts = dict(
        _readable_assets(request, user)
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

    # `select_related('user')` : le sérialiseur nomme le propriétaire d'un asset partagé — sans
    # lui, une page de 48 cards ferait 48 requêtes de plus.
    qs = _readable_assets(request, user).select_related('user')
    if asset_type:
        if asset_type in TYPE_GROUPS:
            group = TYPE_GROUPS[asset_type]      # None ('all') → pas de filtre
            if group is not None:
                qs = qs.filter(asset_type__in=group)
        else:
            qs = qs.filter(asset_type=asset_type)  # valeur exacte (ex. 'voice') passée directement
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(tags__icontains=q) | Q(description__icontains=q))

    total  = qs.count()
    offset = (page - 1) * PAGE_SIZE
    assets = [_serialize_user_asset(a, user) for a in qs[offset:offset + PAGE_SIZE]]

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
    # MIME, taille et `attributes` lus du FICHIER (sonde commune) — même geste que le rangement
    # d'une sortie d'app (`export_item_to_library`) : un objet 3D arrive avec ses faces et son rig.
    from .services import enrich_asset_from_file
    enrich_asset_from_file(asset)
    asset.save(update_fields=['mime_type', 'file_size', 'attributes', 'duration'])

    return JsonResponse(_serialize_user_asset(asset, user))


@require_POST
def api_edit(request, pk: int):
    """POST /media-library/api/assets/<pk>/edit/  — mise à jour nom/description/tags"""
    user = _get_user(request)
    try:
        # MUTATION → accesseur POSSÉDÉ. Une card partagée n'est jamais modifiable par son
        # destinataire : le partage est en lecture seule PAR CONSTRUCTION (`scoping.py`).
        asset = UserAsset.objects.owned_by(user).get(pk=pk)
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

    # Attributs déclarés par la nature (A′) : FUSION clé à clé (une clé absente du payload
    # n'est pas effacée ; `null`/`''` la retire — c'est `normalize_attributes` qui l'applique).
    if isinstance(data.get('attributes'), dict):
        asset.attributes = {**(asset.attributes or {}), **data['attributes']}
        updated.append('attributes')

    if updated:
        try:
            asset.save(update_fields=updated)
        except ValueError as exc:            # valeur hors du vocabulaire de la nature
            return JsonResponse({'error': str(exc)}, status=400)

    return JsonResponse(_serialize_user_asset(asset, user))


@require_POST
def api_delete(request, pk: int):
    """POST /media-library/api/assets/<pk>/delete/"""
    user = _get_user(request)
    try:
        # MUTATION → accesseur POSSÉDÉ (voir `api_edit`).
        asset = UserAsset.objects.owned_by(user).get(pk=pk)
    except UserAsset.DoesNotExist:
        return JsonResponse({'error': 'Asset introuvable'}, status=404)

    from .services import delete_asset
    delete_asset(asset)          # même brique que le retrait depuis le menu « … » d'une card
    return JsonResponse({'deleted': pk})


# `api_promote` RETIRÉ le 2026-09-20 (REMOVAL_LEDGER) : c'était un SECOND chemin d'écriture de
# la visibilité, sans aucun appelant (ni JS, ni gabarit, ni test — mesuré), qui réimplémentait
# les gardes du service commun ET parlait un autre dialecte : il prenait des CODES d'unité et de
# projet là où `sharing.partager()` et `wama-share.js` échangent des IDS. Deux vocabulaires pour
# un seul geste, c'est exactement la divergence que le partage unifié supprime.
# Le geste vit désormais dans le commun : `common:api_partage` → `media_library/element/<pk>/`.


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

    # Whitelist de domaines autorisés selon le provider.
    # None  = provider inconnu → interdit
    # []    = fichiers provenant de CDNs variés (Openverse) → vérifie HTTPS uniquement
    # [...]  = liste de domaines autorisés explicitement
    _DOMAIN_WHITELIST = {
        'wikimedia': ['upload.wikimedia.org', 'commons.wikimedia.org'],
        'pixabay':   ['cdn.pixabay.com', 'i.vimeocdn.com', 'player.vimeo.com'],
        'freesound': ['cdn.freesound.org'],
        'pexels':    ['images.pexels.com', 'videos.pexels.com',
                      'player.vimeo.com', 'vod-progressive.akamaized.net',
                      'clips.vimeocdn.com'],
        'jamendo':   ['storage.jamendo.com', 'prod-1.storage.jamendo.com',
                      'mp3d.jamendo.com'],
        'openverse': [],   # fichiers hébergés sur CDNs tiers variés — HTTPS suffisant
    }
    from urllib.parse import urlparse
    parsed      = urlparse(download_url)
    allowed_domains = _DOMAIN_WHITELIST.get(slug)   # None si provider inconnu
    if allowed_domains is None:
        return JsonResponse({'error': 'Téléchargement non autorisé pour ce provider'}, status=403)
    if allowed_domains and not any(parsed.netloc.endswith(d) for d in allowed_domains):
        return JsonResponse({'error': f'Domaine non autorisé : {parsed.netloc}'}, status=403)
    if parsed.scheme not in ('http', 'https'):
        return JsonResponse({'error': 'URL de téléchargement invalide'}, status=400)
    parsed_domain = parsed.netloc

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

    # Les tags gardent licence/auteur pour la recherche plein texte, mais ils ne sont plus le
    # SEUL endroit où l'attribution existe : elle est désormais portée par des champs propres
    # (interrogeables, et lisibles par l'audit de licences).
    extra_tags = [t for t in [license_, author, slug] if t]
    full_tags  = ', '.join(filter(None, [tags] + extra_tags))[:500]

    asset = UserAsset.objects.create(
        user=user, name=asset_name, asset_type=asset_type,
        file=content, description=f'Source : {slug} (CC : {license_})',
        tags=full_tags,
        license=(license_ or '')[:100],
        author=(author or '')[:200],
        source_url=(body.get('source_url') or body.get('url') or '')[:1000],
    )
    asset.mime_type = mime_type
    asset.file_size = len(file_bytes)
    asset.save(update_fields=['mime_type', 'file_size'])

    return JsonResponse(_serialize_user_asset(asset, user))


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
    if len(api_key) > 500:
        return JsonResponse({'error': 'Clé trop longue (500 caractères au plus)'}, status=400)
    from wama.common.utils.secret_crypto import SecretStorageUnavailable, storage_available
    if api_key and not storage_available():
        return JsonResponse({'error': "Enregistrement des clés indisponible : DJANGO_SECRET_KEY "
                                      "n'est pas définie sur ce serveur."}, status=503)
    cfg, _ = UserProviderConfig.objects.get_or_create(
        user=request.user, provider=provider_obj,
    )
    cfg.api_key  = api_key
    cfg.is_active = True
    try:
        cfg.save(update_fields=['api_key', 'is_active', 'updated_at'])
    except SecretStorageUnavailable as exc:
        return JsonResponse({'error': str(exc)}, status=503)

    return JsonResponse({'success': True, 'has_key': bool(api_key)})


# ── Mots-clés de prompt (tronc commun partagé + perso) ───────────────────────

@login_required
def api_prompt_keywords(request):
    """Liste les mots-clés (partagés + perso de l'utilisateur), groupés par catégorie."""
    from wama.media_library.models import PromptKeyword
    from django.db.models import Q
    domain = request.GET.get('domain', '')
    qs = PromptKeyword.objects.filter(Q(user__isnull=True) | Q(user=request.user))
    if domain:
        qs = qs.filter(Q(domain='') | Q(domain=domain))
    cats = dict(PromptKeyword.CATEGORY_CHOICES)
    # Pré-ordonner les catégories selon CATEGORY_CHOICES (ordre curé, pas alphabétique).
    grouped = {}
    for code, label in PromptKeyword.CATEGORY_CHOICES:
        grouped[code] = {'label': label, 'items': []}
    for kw in qs:
        g = grouped.setdefault(kw.category, {'label': cats.get(kw.category, kw.category), 'items': []})
        g['items'].append(kw.to_dict())
    # Retirer les catégories vides (ex : filtre domaine).
    grouped = {k: v for k, v in grouped.items() if v['items']}
    return JsonResponse({'categories': grouped})


@login_required
@require_POST
def api_prompt_keyword_add(request):
    """Ajoute un mot-clé PERSO (user-custom)."""
    from wama.media_library.models import PromptKeyword
    text = (request.POST.get('text') or '').strip()
    category = request.POST.get('category') or 'style'
    if not text:
        return JsonResponse({'success': False, 'error': 'Texte vide'}, status=400)
    kw, _ = PromptKeyword.objects.get_or_create(
        user=request.user, category=category, text=text[:120],
    )
    return JsonResponse({'success': True, 'keyword': kw.to_dict()})


@login_required
@require_POST
def api_prompt_keyword_delete(request, pk):
    """Supprime un mot-clé PERSO de l'utilisateur (jamais le tronc commun)."""
    from wama.media_library.models import PromptKeyword
    n, _ = PromptKeyword.objects.filter(pk=pk, user=request.user).delete()
    return JsonResponse({'success': bool(n)})


@login_required
def api_export_item(request, app: str, pk: int):
    """
    Le GESTE commun « ranger la sortie de cet élément dans ma médiathèque » (2026-09-11).

    GET  → `{'candidates': [clés], 'labels': {clé: libellé}, 'choices': {clé: {asset_type,
           format, label}}, 'in_library': {clé: {asset_id, name}}}` : les CHOIX offerts pour
           CETTE sortie — des RÔLES pour une app early-binding (extension, puis rôle déclaré
           `result_role`), des FORMATS rendus à la demande pour une app late-binding (ceux du
           bouton ⬇, asset `document`). C'est ce qui remplit le sous-menu « … » — on ne propose
           donc jamais un choix que le serveur refuserait ensuite.
    POST → range (`asset_type`, `output_format`), et rend `{'asset_id', 'name', 'asset_type'}` ;
           `action=remove` retire (mêmes clés).

    ⚠ Une SEULE route pour toutes les apps : la brique lit le résultat au schéma canonique
    (`detail_registry`), jamais un champ propre à une app ; la route d'app du composer, seconde
    porte du même geste, est retirée (`REMOVAL_LEDGER R65`, 2026-09-18).
    """
    from .services import (export_choices, export_item_to_library, in_library_by_choice,
                           remove_item_from_library)

    if request.method == 'POST' and (request.POST.get('action') or '') == 'remove':
        # RETRAIT depuis le menu (2026-09-14) : ne touche QUE les assets de l'utilisateur rangés
        # depuis cet élément — un pk étranger ne peut rien retirer de la médiathèque d'autrui.
        resultat = remove_item_from_library(
            request.user, app, pk,
            asset_type=(request.POST.get('asset_type') or '').strip(),
            output_format=(request.POST.get('output_format') or '').strip())
        if 'error' in resultat:
            return JsonResponse(resultat, status=400)
        return JsonResponse({'success': True, **resultat})

    if request.method == 'POST':
        resultat = export_item_to_library(
            request.user, app, pk,
            asset_type=(request.POST.get('asset_type') or '').strip(),
            name=(request.POST.get('name') or '').strip(),
            output_format=(request.POST.get('output_format') or '').strip(),
        )
        if 'error' in resultat:
            # 403 pour un refus de propriété, 400 pour tout le reste : un menu doit pouvoir
            # distinguer « pas le droit » de « précisez le rôle ».
            code = 403 if resultat.get('error') == 'forbidden' else 400
            return JsonResponse(resultat, status=code)
        return JsonResponse({'success': True, **resultat})

    # GET — les CHOIX possibles, dérivés du RÉSULTAT réel de l'élément.
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.common.utils.export_formats import VOCABULARY, is_late_binding

    entree = DetailRegistry.get(app)
    if not entree:
        return JsonResponse({'error': f"App inconnue : '{app}'."}, status=404)
    instance = entree['model'].objects.filter(pk=pk).first()
    if instance is None:
        return JsonResponse({'error': f"Élément #{pk} introuvable."}, status=404)
    proprietaire = getattr(instance, 'user', None)
    if proprietaire is not None and proprietaire != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'forbidden'}, status=403)
    # ÉTAT PERSISTÉ : sous quelles CLÉS la sortie est DÉJÀ rangée (provenance). Rendu dans les
    # deux réponses — un asset reste retirable même si l'élément n'a plus de résultat lisible.
    libelles = dict(ASSET_TYPES)
    deja = in_library_by_choice(request.user, app, pk)
    try:
        detail = entree['adapter'](instance)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    choix = {c['key']: c for c in export_choices(app, detail)}
    # Une clé DÉJÀ rangée reste retirable même si le résultat a changé de format depuis :
    # elle garde un libellé, dans le vocabulaire de son archétype.
    if is_late_binding(app):
        for cle in deja:
            choix.setdefault(cle, {'key': cle, 'asset_type': 'document', 'format': cle,
                                   'label': f"{libelles.get('document', 'Document')} · "
                                            f"{(VOCABULARY.get(cle) or {}).get('label', cle.upper())}"})
    else:
        for cle in deja:
            choix.setdefault(cle, {'key': cle, 'asset_type': cle, 'format': '',
                                   'label': libelles.get(cle, cle)})
    candidats = [c['key'] for c in export_choices(app, detail)]
    reponse = {'candidates': candidats,
               'labels': {k: c['label'] for k, c in choix.items()},
               'choices': choix,
               'in_library': deja}
    if not candidats and not deja:
        return JsonResponse({'error': "cet élément n'a pas encore de résultat à ranger",
                             **reponse}, status=400)
    return JsonResponse(reponse)
