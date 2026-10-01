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
                     ASSET_TYPE_CATEGORY, ASSET_TYPES, ALLOWED_EXTENSIONS, TYPE_GROUPS)
from .natures import natures_as_json
from .providers.registry import ensure_provider_rows, get_provider, provider_row
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


#: La BARRE COMMUNE de la page (2026-10-01, demande de Fabien : « on n'a que la recherche ;
#: réutiliser la barre de filtrage/tri/recherche commune ») — mode `remote` de `wama-filter-bar.js` :
#: la page charge sa liste elle-même, la barre lui dit QUOI charger. Les TRIS se déclarent ici une
#: fois : la barre les propose (outil `sort_by`), les deux vues de liste les appliquent. Sans `sort`
#: demandé, l'ordre reste celui d'avant (la fenêtre de sélection des apps ne le passe pas).
LIST_SORTS = {
    'recent': ('↓ Plus récent', ('-created_at', '-pk')),
    'oldest': ('↑ Plus ancien', ('created_at', 'pk')),
    'name':   ('Nom', ('name', 'pk')),
    'size':   ('Taille', ('-file_size', 'pk')),
}

#: Au-delà de ce nombre de valeurs DIFFÉRENTES, un attribut libre n'est pas proposé en filtre : un
#: menu de deux cents entrées n'aide plus à trouver, la recherche le fait mieux.
FREE_FACET_MAX = 30

ORIGIN_FACET = {'cle': 'origin', 'label': 'Origine', 'tous': 'Toutes',
                'options': {'mine': 'Les miens', 'shared': 'Partagés avec moi',
                            'system': 'Système'}}


def _attribute_facets(user) -> list:
    """Les filtres d'ATTRIBUTS, par nature — DÉRIVÉS de la déclaration (`natures.py`), jamais
    écrits par onglet : un vocabulaire déclaré (`choices`, au moins deux valeurs) donne ses
    valeurs ; un texte libre (la langue d'une voix) donne les valeurs PRÉSENTES dans ce que
    l'utilisateur peut lire, système compris. Chaque filtre porte sa `nature` : la page ne montre
    que ceux de l'onglet ouvert."""
    from wama.common.utils.scoping import listable_by
    from .natures import ASSET_NATURES
    facets = []
    for key, nature in ASSET_NATURES.items():
        for attr, spec in nature.attributes.items():
            if len(spec.choices) >= 2:
                labels = dict(spec.labels)
                options = {c: labels.get(c, c) for c in spec.choices}
            elif spec.kind == 'str' and not spec.choices:
                values = set()
                for qs in (listable_by(UserAsset.objects.filter(asset_type=key), user),
                           SystemAsset.objects.filter(is_active=True, asset_type=key)):
                    values |= {v for v in qs.values_list(f'attributes__{attr}', flat=True)
                               if isinstance(v, str) and v}
                if not values or len(values) > FREE_FACET_MAX:
                    continue
                options = {v: v for v in sorted(values)}
            else:
                continue
            facets.append({'cle': f'attr__{key}__{attr}', 'label': spec.label or attr,
                           'tous': 'Tous', 'options': options, 'nature': key})
    return facets


def _apply_list_filters(qs, request, natures):
    """Recherche, filtres d'attributs et tri demandés par la barre — UNE fois, pour les assets de
    l'utilisateur comme pour ceux du système. Un filtre d'une AUTRE nature que celles affichées est
    ignoré (onglet changé), un attribut non déclaré aussi : on ne filtre jamais sur une clé libre."""
    from .natures import is_canonical_attribute
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(tags__icontains=q) | Q(description__icontains=q))
    for param, value in request.GET.items():
        if not param.startswith('attr__') or not value or value == 'all':
            continue
        parts = param.split('__')
        if len(parts) != 3:
            continue
        nature, attr = parts[1], parts[2]
        if (natures is not None and nature not in natures) or not is_canonical_attribute(nature, attr):
            continue
        qs = qs.filter(asset_type=nature, **{f'attributes__{attr}': value})
    sort = LIST_SORTS.get(request.GET.get('sort') or '')
    return qs.order_by(*sort[1]) if sort else qs


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
        # La PROVENANCE, dite une fois pour toutes les surfaces (fenêtre de sélection, page) :
        # `mine` ou `shared` ici, `system` pour un asset système.
        'origin':      'mine' if (user is not None and a.user_id == getattr(user, 'id', None))
                       else 'shared',
        'owner':       a.user.username if a.user_id else '',
        'file_url':    a.file.url if a.file else '',
        # Le chemin (relatif à MEDIA_ROOT) : ce qu'une card DÉSIGNE pour pointer l'asset au lieu
        # de le re-téléverser (`media_paths.designation_field`, 2026-09-28).
        'path':        a.file.name if a.file else '',
        'file_size':   a.file_size_display,
        'duration':    a.duration_display,
        'mime_type':   a.mime_type,
        'preview_mime': _preview_mime(a),
        'description': a.description,
        'tags':        a.tags,
        'attributes':  a.attributes or {},
        'created_at':  a.created_at.strftime('%d/%m/%Y'),
    }


def _preview_mime(a):
    """Le type pour l'APERÇU : celui stocké, sinon celui du FICHIER (`guess_mime_type`).

    Un asset ancien ou importé sans sonde a un `mime_type` vide ou générique ; la fenêtre de
    sélection n'aurait rien su montrer (2026-09-29). `mime_type` reste la donnée STOCKÉE."""
    stored = a.mime_type or ''
    if stored and stored != 'application/octet-stream':
        return stored
    from wama.common.utils.mime_utils import guess_mime_type
    return guess_mime_type(a.file.name) if a.file else stored


def _serialize_system_asset(a):
    return {
        'id':          a.id,
        'name':        a.name,
        'asset_type':  a.asset_type,
        'origin':      'system',
        'file_url':    a.file.url if a.file else '',
        'path':        a.file.name if a.file else '',   # cf. _serialize_user_asset
        'file_size':   a.file_size_display,
        'duration':    a.duration_display,
        'mime_type':   a.mime_type,
        'preview_mime': _preview_mime(a),
        'description': a.description,
        'tags':        a.tags,
        'attributes':  a.attributes or {},
        'license':     a.license,
    }


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

@login_required
def index(request):
    tab = request.GET.get('tab', 'voice')
    # Compteur de mots-clés visibles (tronc commun partagé + perso de l'utilisateur).
    kw_filter = Q(user__isnull=True)
    if request.user.is_authenticated:
        kw_filter |= Q(user=request.user)
    keyword_count = PromptKeyword.objects.filter(kw_filter).count()
    from .natures import ASSET_NATURES
    context = {
        'asset_types':   ASSET_TYPES,
        # Les ONGLETS : clé, libellé et icône DÉCLARÉS par la nature (`natures.py`). Les icônes
        # étaient écrites dans le gabarit, nature par nature — la dernière arrivée (« Parole
        # enregistrée ») s'affichait donc sans icône (2026-09-29).
        'asset_tabs':    [(k, n.label, n.icon) for k, n in ASSET_NATURES.items()],
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
        # La barre commune (mode `remote`) : origine + attributs DÉRIVÉS des natures, tris déclarés.
        'library_facets': [ORIGIN_FACET, *_attribute_facets(_get_user(request))],
        'library_sorts': [(k, label) for k, (label, _order) in LIST_SORTS.items()],
    }
    return render(request, 'media_library/index.html', context)


# ---------------------------------------------------------------------------
# API — Compteurs par type (badges sur les onglets)
# ---------------------------------------------------------------------------

@login_required
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

def _natures_for(asset_type: str, exact: bool = False):
    """Les natures que filtre `?type=` : une catégorie (ou `all` → toutes), sinon la valeur exacte.

    `exact` force la NATURE : trois natures portent le nom de leur catégorie (`image`, `video`,
    `document`) — sans lui, l'onglet « Image » montrerait aussi les avatars."""
    if not asset_type:
        return None
    if asset_type in TYPE_GROUPS and not exact:
        return TYPE_GROUPS[asset_type]          # None pour 'all' : pas de filtre
    return [asset_type]


def _tabs_for(asset_type: str, user_qs, system_qs) -> list:
    """Les ONGLETS d'une fenêtre de sélection : la catégorie de `asset_type` puis chacune de ses
    natures, dans l'ordre DÉCLARÉ (`natures.py`), avec leur compte. Une nature exacte ouvre les
    onglets de SA catégorie : on la choisit parmi ses sœurs, jamais seule."""
    from .natures import ASSET_NATURES
    category = asset_type if asset_type in TYPE_GROUPS else ASSET_TYPE_CATEGORY.get(asset_type, 'all')
    members = TYPE_GROUPS.get(category) or list(ASSET_NATURES)
    counts = dict(user_qs.filter(asset_type__in=members).values('asset_type')
                  .annotate(n=Count('id')).values_list('asset_type', 'n'))
    if system_qs is not None:
        for key, n in (system_qs.filter(asset_type__in=members).values('asset_type')
                       .annotate(n=Count('id')).values_list('asset_type', 'n')):
            counts[key] = counts.get(key, 0) + n
    tabs = [{'key': category, 'exact': False, 'label': 'Tous', 'icon': 'fa-layer-group',
             'count': sum(counts.values())}]
    # Un onglet de NATURE dit aussi ce que la card d'ajout de la fenêtre accepte (2026-09-30) :
    # formats admis (conversion vers le pivot comprise) et « Enregistrer » — la déclaration de
    # `natures_as_json`, jamais recopiée côté JS.
    declared = natures_as_json()
    tabs += [{'key': k, 'exact': True, 'label': ASSET_NATURES[k].label,
              'icon': ASSET_NATURES[k].icon, 'count': counts.get(k, 0),
              'extensions': declared[k]['extensions'], 'recordable': declared[k]['recordable'],
              'attributes': declared[k]['attributes']}
             for k in ASSET_NATURES if k in members]
    return tabs


@login_required
def api_list(request):
    """GET /media-library/api/assets/?type=voice&q=fab&page=1

    Options (2026-09-29, fenêtre de sélection universelle — `CARD_DESIGN §11.11` étape 3 (d)) :
      • `with_system=1` : ajoute les assets SYSTÈME actifs (la galerie d'avatars, les voix…),
        après les assets de l'utilisateur ;
      • `tabs=1` : rend aussi les onglets de la catégorie (`_tabs_for`), comptes compris ;
      • `exact=1` : `type` est une NATURE, même quand elle porte le nom de sa catégorie ;
      • chaque asset porte son `origin` — `mine`, `shared` (partagé avec moi) ou `system`.
    Sans ces options, la réponse est celle d'avant : la portée se DEMANDE (`?scope=`)."""
    user       = _get_user(request)
    asset_type = request.GET.get('type', '')
    page       = max(1, int(request.GET.get('page', 1)))
    natures    = _natures_for(asset_type, exact=request.GET.get('exact') == '1')
    origin     = request.GET.get('origin') or 'all'

    # `select_related('user')` : le sérialiseur nomme le propriétaire d'un asset partagé — sans
    # lui, une page de 48 cards ferait 48 requêtes de plus.
    readable = _readable_assets(request, user).select_related('user')
    qs = readable.filter(asset_type__in=natures) if natures is not None else readable
    qs = _apply_list_filters(qs, request, natures)
    # ORIGINE (filtre de la barre) : les miens, ceux qu'on me partage, ou ceux du système seuls.
    if origin == 'mine':
        qs = qs.filter(user=user)
    elif origin == 'shared':
        qs = qs.exclude(user=user)
    elif origin == 'system':
        qs = qs.none()

    system_all = SystemAsset.objects.filter(is_active=True) \
        if request.GET.get('with_system') == '1' else None
    offset = (page - 1) * PAGE_SIZE
    if system_all is None:
        total  = qs.count()
        assets = [_serialize_user_asset(a, user) for a in qs[offset:offset + PAGE_SIZE]]
    else:
        system = system_all.filter(asset_type__in=natures) if natures is not None else system_all
        system = _apply_list_filters(system, request, natures)
        if origin in ('mine', 'shared'):
            system = system.none()
        if not request.GET.get('sort'):
            system = system.order_by('asset_type', 'name')
        # Les miens, puis ceux qu'on me partage, puis ceux du système — l'ordre de la confiance.
        mine = [_serialize_user_asset(a, user) for a in qs]
        rows = ([a for a in mine if a['is_mine']] + [a for a in mine if not a['is_mine']]
                + [_serialize_system_asset(a) for a in system])
        total  = len(rows)
        assets = rows[offset:offset + PAGE_SIZE]

    data = {
        'assets':    assets,
        'total':     total,
        'page':      page,
        'page_size': PAGE_SIZE,
        'has_more':  offset + PAGE_SIZE < total,
    }
    if request.GET.get('tabs') == '1':
        data['tabs'] = _tabs_for(asset_type or 'all', readable, system_all)
    return JsonResponse(data)


@login_required
@require_POST
def api_upload(request):
    """POST /media-library/api/assets/upload/ — la vue d'ajout de la CARD D'ENTRÉE commune.

    Reçoit un fichier TÉLÉVERSÉ (`file`) ou DÉSIGNÉ (`file__designated` : glissé depuis l'arbre,
    même contrat que les vues d'upload des apps). La nature est celle de l'onglet ouvert
    (`asset_type`), jamais devinée ; le nom est facultatif — celui du fichier par défaut, il se
    corrige ensuite (« on ajoute, puis on règle », comme une card de file). Le geste est LA brique
    `services.add_file_to_library` (2026-09-29) : un fichier désigné est DÉPLACÉ dans la
    médiathèque (D24), ce qui n'a de sens que pour un fichier de l'espace de l'utilisateur."""
    from wama.common.utils.media_paths import (OutsideMediaRoot, designation_field, in_user_home,
                                               resolve_under_media_root)
    from .services import LibraryAddRefused, add_file_to_library

    user = _get_user(request)
    asset_type = request.POST.get('asset_type', '').strip()
    uploaded = request.FILES.get('file')
    source = None
    designated = request.POST.get(designation_field('file'), '').strip()
    if uploaded is None and designated:
        try:
            source, rel = resolve_under_media_root(designated)
        except (OutsideMediaRoot, FileNotFoundError):
            return JsonResponse({'error': 'Fichier introuvable'}, status=400)
        if not in_user_home(rel, user.id):
            return JsonResponse({'error': "Seul un fichier de votre espace rejoint votre médiathèque ; "
                                          "un asset partagé ou système se désigne depuis une card."},
                                status=400)
        if UserAsset.objects.filter(file=rel).exists():
            return JsonResponse({'error': 'Ce fichier est déjà dans la médiathèque.'}, status=409)
    if uploaded is None and source is None:
        return JsonResponse({'error': 'Fichier requis'}, status=400)

    # Ce que la card d'ajout fait DIRE à la personne (2026-09-30) : les attributs que la nature
    # demande (`attributes`, JSON) et la provenance d'un extrait qui n'est pas d'elle.
    try:
        attributes = json.loads(request.POST.get('attributes') or '{}')
        if not isinstance(attributes, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({'error': 'Attributs illisibles.'}, status=400)
    try:
        asset = add_file_to_library(
            user, asset_type, uploaded=uploaded, source=source,
            name=request.POST.get('name', ''), description=request.POST.get('description', '').strip(),
            tags=request.POST.get('tags', '').strip(), attributes=attributes,
            license=request.POST.get('license', ''), author=request.POST.get('author', ''),
            source_url=request.POST.get('source_url', ''))
    except LibraryAddRefused as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)
    return JsonResponse(_serialize_user_asset(asset, user))


@login_required
@require_POST
def api_estimate(request):
    """POST /media-library/api/assets/estimate/ — ce qu'on peut PROPOSER des attributs demandés à
    l'ajout, en écoutant le fichier AVANT qu'il soit ajouté (2026-09-30).

    Même entrée que `api_upload` (`file` téléversé, ou `file__designated`) et même nature
    (`asset_type`) ; rien n'est enregistré. Un fichier désigné passe les gardes communes
    (confinement, droit de lecture). Rend `{'proposals': {clé: {value, label, confidence}}}`."""
    import os
    import tempfile
    from pathlib import Path

    from wama.common.utils.media_paths import (OutsideMediaRoot, designation_field, readable_by,
                                               resolve_under_media_root)
    from .natures import ASSET_NATURES
    from .services import estimate_attributes

    user = _get_user(request)
    asset_type = request.POST.get('asset_type', '').strip()
    if asset_type not in ASSET_NATURES:
        return JsonResponse({'error': 'Nature inconnue'}, status=400)
    uploaded = request.FILES.get('file')
    designated = request.POST.get(designation_field('file'), '').strip()
    if uploaded is not None:
        suffix = Path(uploaded.name).suffix.lower()[:10]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            for chunk in uploaded.chunks():
                tmp.write(chunk)
        try:
            return JsonResponse({'proposals': estimate_attributes(asset_type, tmp.name)})
        finally:
            os.unlink(tmp.name)
    if designated:
        try:
            source, rel = resolve_under_media_root(designated)
        except (OutsideMediaRoot, FileNotFoundError):
            return JsonResponse({'error': 'Fichier introuvable'}, status=400)
        if not readable_by(rel, user):
            return JsonResponse({'error': 'Fichier non lisible pour vous'}, status=403)
        return JsonResponse({'proposals': estimate_attributes(asset_type, str(source))})
    return JsonResponse({'error': 'Fichier requis'}, status=400)


@login_required
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


@login_required
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

@login_required
def api_system_list(request):
    """GET /media-library/api/system/?type=voice&q=homme — mêmes filtres et tri que `api_list`
    (barre commune) ; `origin=mine|shared` n'en rend aucun."""
    asset_type = request.GET.get('type', '')
    page       = max(1, int(request.GET.get('page', 1)))

    qs = SystemAsset.objects.filter(is_active=True)
    if asset_type:
        qs = qs.filter(asset_type=asset_type)
    qs = _apply_list_filters(qs, request, [asset_type] if asset_type else None)
    if request.GET.get('origin') in ('mine', 'shared'):
        qs = qs.none()

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

@login_required
def api_providers_list(request):
    """GET /media-library/api/providers/?type=image
    Retourne les providers actifs supportant le type donné.
    Indique si l'utilisateur a configuré une clé pour chaque provider.
    """
    asset_type = request.GET.get('type', '')
    user       = _get_user(request)

    ensure_provider_rows()     # un connecteur ENREGISTRÉ a sa ligne, sans migration de données
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


@login_required
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

    provider_row(slug)         # ligne créée si le connecteur est enregistré (sinon : 404 ci-dessous)
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

    provider_row(slug)
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

    # Domaines autorisés : DÉCLARÉS par le connecteur (`download_domains`, 2026-09-30 — c'était
    # un dictionnaire écrit ici, une seconde déclaration à côté de la classe).
    # None = aucun téléchargement ; () = tout domaine en HTTPS ; (...) = ces domaines seuls.
    from urllib.parse import urlparse
    parsed      = urlparse(download_url)
    allowed_domains = provider.download_domains
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
    # Ce que le FICHIER dit de lui (attributs de la nature : un avatar GLB y gagne `rigged`,
    # `face_rig`, `visemes`) — la brique d'ingest commune. Ce chemin la contournait : un asset
    # venu d'un connecteur n'avait aucun attribut, alors que son docstring cite « fournisseur ».
    from .services import enrich_asset_from_file
    enrich_asset_from_file(asset)
    asset.save(update_fields=['mime_type', 'file_size', 'attributes', 'duration'])

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
