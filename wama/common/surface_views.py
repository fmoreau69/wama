"""Les vues COMMUNES des surfaces (`common/surfaces.py`) — une app DÉCLARE une surface, elle
n'écrit ni page, ni lecture, ni enregistrement (2026-10-10, chantier SURFACES).

  page    GET   /common/surface/<app>/<clé>/<pk>/        la page : grille des briques
  data    GET   …/data/                                  ce que les briques lisent (JSON)
                …/data/?only=rhythm&role=<rôle>          la grille des temps d'un audio lu
                …/data/?only=peaks&role=<rôle>[&source=<process>][&poll=1]
                                                         les pics fins d'un média lu (état ou pics) —
                                                         de l'une de ses versions (`sources_of`)
  save    POST  …/save/                                  le champ édité, validé par la surface
          data/save/revisions acceptent `field` (2026-10-22) : un champ des `Surface.also_edits`
          édité à la place du principal (la partition complète du composer)
  layout  POST  /common/surface/<app>/<clé>/layout/      la disposition de l'UTILISATEUR (places,
                                                         figée ou non) — un réglage par compte

Droits : LIRE = voir la card (la règle de l'aperçu, `PreviewRegistry.check_permission`, cards
partagées comprises) ; ÉCRIRE = l'éditer (`scoping.editable_or_404` : le propriétaire ou un
collaborateur nommé, dont le geste est tracé `corrige`).

CONFLIT (2026-10-13 — la règle de la page de correction du Transcriber, `WAMA_COLLABORATION
§2.4`, portée ici pour TOUTES les surfaces) : la page reçoit l'empreinte de l'état édité
(`edit_lock.state_token`) et la renvoie ; un enregistrement préparé sur un état PÉRIMÉ est refusé
(409), la ligne verrouillée le temps de comparer et d'écrire.
"""
from __future__ import annotations

import json
import os

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET, require_POST

from wama.common.surfaces import surface as find_surface


def _surface_or_404(app: str, key: str):
    found = find_surface(app, key)
    if found is None:
        raise Http404(f"surface inconnue : {app}.{key}")
    return found


def _readable_or_404(found, user, pk):
    from wama.common.utils.scoping import listable_by
    model = found.model_class()
    item = listable_by(model.objects.all(), user).filter(pk=pk).first()
    if item is None:
        raise Http404("élément introuvable")
    return item


def _can_edit(user, item) -> bool:
    from wama.common.utils.scoping import can_edit
    return can_edit(user, item)


def _url(name: str, *args) -> str:
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _settings_url(app: str, pk: int) -> str:
    """La route des réglages d'UN élément que l'app sert (`update_settings` et ses orthographes
    admises — `urls_gen.served_route`, le résolveur unique), '' si elle n'en sert pas."""
    from wama.common.manifests.codegen.urls_gen import served_route
    name = served_route(app, 'update_settings', args=[pk])
    return _url(f'{app}:{name}', pk) if name else ''


def _settings_of(found, item) -> dict:
    """Les réglages que la page lit (`Surface.settings`) : leur schéma — celui de l'app, réduit aux
    noms déclarés — et leurs valeurs sur l'élément."""
    from wama.common.utils.param_schema import schema_for_app
    names = set(found.settings)
    schema = [p for p in schema_for_app(found.app) if p.get('name') in names]
    values = {}
    for name in found.settings:
        value = getattr(item, name, None)
        values[name] = value.isoformat() if hasattr(value, 'isoformat') else value
    return {'schema': schema, 'values': values}


def _layout_setting(found) -> str:
    """Le nom du réglage utilisateur (`UserAppSetting`, app de la surface) qui garde sa disposition."""
    return f'surface_layout.{found.key}'


def _layout_of(found, user) -> dict:
    """La disposition que `user` a gardée pour la surface (`clean_layout`), `stored` à vrai ; à
    défaut la disposition déclarée, FIGÉE — pour tous depuis le 2026-10-21 (décision de Fabien :
    la mise en page d'origine verrouillée, le cadenas la rend modifiable) ; seul le mode Simplifié
    l'était jusque-là."""
    from wama.common.utils.user_settings import get_user_app_setting
    stored = get_user_app_setting(user, found.app, _layout_setting(found))
    if isinstance(stored, dict):
        return {'slots': stored.get('slots') or None, 'frozen': stored.get('frozen') is True,
                'docked': stored.get('docked') or {}, 'stacks': stored.get('stacks') or {},
                'stored': True}
    return {'slots': None, 'frozen': True, 'docked': {}, 'stacks': {}, 'stored': False}


@login_required
@require_POST
def surface_layout(request, app: str, key: str):
    """Garde la disposition de l'utilisateur : une préférence de LECTURE, pas une édition — qui
    ouvre la page en lecture seule dispose et fige aussi la sienne. Rien ne touche l'élément."""
    from wama.common.surfaces import clean_layout
    from wama.common.utils.user_settings import save_user_app_settings
    found = _surface_or_404(app, key)
    try:
        layout = clean_layout(found, json.loads(request.body or b'{}'))
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    save_user_app_settings(request.user, found.app, {_layout_setting(found): layout})
    return JsonResponse({'ok': True, 'layout': layout})


@login_required
@require_GET
def surface_page(request, app: str, key: str, pk: int):
    found = _surface_or_404(app, key)
    item = _readable_or_404(found, request.user, pk)
    ok, reason = found.can_open(item)
    base = f'/common/surface/{app}/{key}/{pk}/'
    from wama.common.utils.volet import volet
    return render(request, 'common/surface.html', {
        'surface': found,
        'item': item,
        'available': ok,
        'reason': reason,
        # Le volet d'une surface (2026-10-21) : l'assistant en tête, puis la COLONNE de briques de
        # la surface (`zone='panel'`) — plus les sections par défaut, qui n'y montraient rien
        # (« Sélectionnez un fichier pour l'aperçu », « Aucun paramètre disponible »).
        'volet': volet(tete=True, medias=False, parametres=False, actions=False),
        'config': {
            'surface': found.to_dict(),
            'pk': pk,
            'title': f"{found.label} — #{pk}",
            'data_url': base + 'data/',
            'save_url': base + 'save/',
            'run_url': _url(f'{app}:start_process', pk, found.reruns) if found.reruns else '',
            'revisions_url': base + 'revisions/',
            'back_url': _url(f'{app}:index'),
            'can_edit': _can_edit(request.user, item),
            # La disposition se garde PAR COMPTE (`surface_layout`) ; la clé du navigateur ne sert
            # plus qu'à reprendre une disposition gardée avant le 2026-10-21, et en secours.
            'layout_key': f'wama.surface.{found.id}',
            'layout': _layout_of(found, request.user),
            'layout_url': reverse('common:surface_layout', args=[app, key]),
            # Les routes de geste de l'app (`Surface.routes`) et celle de ses réglages.
            'routes': {gesture: _url(f'{app}:{name}', pk) for gesture, name in found.routes.items()},
            'settings_url': _settings_url(app, pk) if found.settings else '',
        },
        'scripts': found.scripts(),
    })


@login_required
@require_GET
def surface_data(request, app: str, key: str, pk: int):
    found = _surface_or_404(app, key)
    item = _readable_or_404(found, request.user, pk)
    ok, reason = found.can_open(item)
    if not ok:
        return JsonResponse({'error': reason}, status=409)
    if request.GET.get('only') == 'rhythm':
        return JsonResponse({'rhythm': _rhythm_of(found, item, request.GET.get('role') or '')})
    if request.GET.get('only') == 'peaks':
        # Les PICS FINS d'un média lu (service commun `waveform.dense_peaks`) : mis en file s'ils
        # manquent ; un échec se retente à la 1ʳᵉ demande d'une page, pas pendant qu'elle interroge.
        from wama.common.utils.waveform import dense_peaks
        role = request.GET.get('role') or ''
        field_name = found.reads.get(role)
        value = getattr(item, field_name, None) if field_name and field_name not in found.documents else None
        name = getattr(value, 'name', '') or ''
        source = request.GET.get('source') or ''
        if source:
            # Une VERSION du média lu (une sortie de process, `Surface.sources_of`) : seulement
            # l'une de celles que la surface propose — jamais un champ nommé par la page.
            name = next((s['name'] for s in found.sources_of(item, role) if s['key'] == source), '')
        return JsonResponse(dense_peaks(name, retry_failed=not request.GET.get('poll')))
    from wama.common.services.edit_lock import state_token
    reads, media, sources = {}, {}, {}
    for role, field_name in found.reads.items():
        value = getattr(item, field_name, None)
        if role in found.documents:
            reads[role] = _document(value)
        elif role in found.texts:
            from wama.common.surfaces import MAX_TEXT_CHARS
            reads[role] = _text(value, MAX_TEXT_CHARS)
        else:
            reads[role] = value.url if value else ''
            peaks = _server_peaks(reads[role])
            if peaks:
                media[role] = peaks
            versions = _sources(found, item, role)
            if versions:
                sources[role] = versions
    if request.GET.get('only') == 'state':
        # Le SUIVI d'un process rejoué (« Appliquer ») : ce que les briques relisent, sans la
        # valeur éditée — que la page tient déjà, et qui peut peser un document entier.
        return JsonResponse({'reads': reads, 'media': media, 'sources': sources,
                             'processes': _process_states(item)})
    try:
        field = found.target(item, request.GET.get('field') or '')
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    value = _value_of(found, item, field)
    return JsonResponse({
        'processes': _process_states(item),
        'reads': reads,
        'media': media,
        'sources': sources,
        'value': value,
        'context': found.context_of(item),
        'settings': _settings_of(found, item) if found.settings else None,
        'can_edit': _can_edit(request.user, item),
        'token': state_token(value),
        'field': field,
    })


@login_required
@require_GET
def surface_revisions(request, app: str, key: str, pk: int):
    """Les révisions de l'élément, la plus récente d'abord, et pour chacune si le fichier ÉDITÉ
    a été gardé (`revisions.kept_file`) — ce que la brique « Versions » liste. Vide pour une
    surface qui n'édite pas un fichier texte, ou une app qui ne garde pas ses sorties."""
    from wama.common.services.revisions import kept_count, kept_file, revisions_of
    found = _surface_or_404(app, key)
    item = _readable_or_404(found, request.user, pk)
    if not found.text_value or not kept_count(app):
        return JsonResponse({'revisions': [], 'keeps': False})
    from wama.common.models import ItemRevision
    labels = dict(ItemRevision.ORIGIN_CHOICES)
    try:
        edited = found.target(item, request.GET.get('field') or '')
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    out = []
    for revision in revisions_of(app, item).select_related('user')[:200]:
        user = revision.user
        out.append({
            'number': revision.number,
            'origin': revision.origin,
            'origin_label': labels.get(revision.origin, revision.origin),
            'created_at': revision.created_at.isoformat(),
            'user': (user.get_full_name() or user.username) if user else '',
            'models': revision.model_keys or [],
            'published': revision.published_at is not None,
            'kept': bool(kept_file(app, item, revision.number, edited)),
        })
    return JsonResponse({'revisions': out, 'keeps': True, 'keep': kept_count(app)})


@login_required
@require_GET
def surface_revision_value(request, app: str, key: str, pk: int, number: int):
    """Le texte du fichier édité tel que la révision `number` l'a laissé (sa copie gardée) —
    « Reprendre » le charge dans la page, qui l'enregistre comme une correction de plus."""
    from django.conf import settings

    from wama.common.services.revisions import kept_file
    from wama.common.surfaces import validate_text
    found = _surface_or_404(app, key)
    item = _readable_or_404(found, request.user, pk)
    try:
        edited = found.target(item, request.GET.get('field') or '')
    except ValueError:
        raise Http404("champ non édité ici")
    rel = kept_file(app, item, number, edited) if found.text_value else ''
    if not rel:
        raise Http404("aucune version gardée pour cette révision")
    try:
        with open(os.path.join(settings.MEDIA_ROOT, rel), encoding='utf-8', errors='replace') as source:
            value = validate_text(source.read())
    except (OSError, ValueError):
        raise Http404("version illisible")
    return JsonResponse({'number': number, 'value': value})


def _process_states(item) -> dict:
    """`{process: état}` des lignes d'exécution de l'élément (`STALE` compris : le moteur l'a
    posé à l'enregistrement) — ce qu'une brique lit pour dire qu'un rendu est périmé, en cours ou
    refait. `{}` sans pipeline."""
    try:
        from wama.common.services.process_pipeline import pipeline_of
        pipeline = pipeline_of(item)
        if pipeline is None:
            return {}
        return {key: row.status for key, row in pipeline.rows(item).items()}
    except Exception:
        return {}


def _sources(found, item, role: str) -> list:
    """Les versions du média lu sous `role` (`Surface.sources_of`), servies : `[{key, label, url,
    peaks?}]` — les pics serveur d'un long audio, comme ceux du rôle (`media`)."""
    from django.core.files.storage import default_storage
    out = []
    for version in found.sources_of(item, role):
        url = default_storage.url(version['name'])
        entry = {'key': version['key'], 'label': version['label'], 'url': url}
        peaks = _server_peaks(url)
        if peaks:
            entry['peaks'] = peaks
        out.append(entry)
    return out


def _server_peaks(url: str):
    """`{peaks, duration}` d'un AUDIO trop lourd pour être décodé par le navigateur — la brique de
    l'aperçu (`preview_utils.server_peaks`, calcul ffmpeg mis en cache) ; None sinon."""
    if not url:
        return None
    try:
        from wama.common.utils.preview_utils import server_peaks
        return server_peaks(url)
    except Exception:
        return None


def _rhythm_of(found, item, role: str):
    """La grille des temps (`audio_rhythm.beat_grid`) de l'AUDIO lu sous `role` — demandée à part
    (`?only=rhythm`) par une brique qui cale une partition dessus : quelques secondes au premier
    appel, la page ne l'attend pas. None pour un rôle inconnu, un document ou un non-audio."""
    field_name = found.reads.get(role)
    if not field_name or role in found.documents or role in found.texts:
        return None
    value = getattr(item, field_name, None)
    if not getattr(value, 'name', ''):
        return None
    from wama.common.utils.mime_utils import guess_mime_type
    if not guess_mime_type(value.name).startswith('audio/'):
        return None
    from wama.common.utils.audio_rhythm import beat_grid
    try:
        return beat_grid(value.path)
    except Exception:
        return None


def _value_of(found, item, field: str = ''):
    """La valeur ÉDITÉE telle que la page la reçoit : celle que la surface déclare (`value`), sinon
    le texte du fichier, ou le champ de donnée. `field` : un champ des `also_edits` (son texte)."""
    if field and field in found.also_edits:
        return _text(getattr(item, field, None))
    if found.value is not None:
        return found.value(item)
    edited = found.edited(item)
    if found.text_value:
        return _text(getattr(item, edited, None))
    return getattr(item, edited, None) or {}


def _write_text(item, field_name: str, text: str) -> bool:
    """Écrit le texte édité dans le fichier du champ ; rend `False` si rien n'a changé.

    EN PLACE quand le fichier est à la card et à elle seule (`owns_file`, `is_shared_elsewhere` —
    les deux règles de `safe_delete_file`) : le chemin ne bouge pas, la ligne d'exécution du
    process qui l'a produit le désigne toujours, et son empreinte change — l'aval passe périmé.
    Écrit à côté puis remplacé (`os.replace`, même dossier : jamais à travers deux systèmes de
    fichiers), une coupure ne laisse pas un fichier à moitié écrit.
    Sinon (un fichier qu'elle ne fait que désigner, ou qu'une autre ligne désigne aussi) : jamais
    réécrit — un NOUVEAU fichier chez l'app de la card, que ses lignes d'exécution désignent
    désormais à la place de l'ancien, qui reste intact pour ses autres porteurs."""
    from django.core.files.base import ContentFile

    from wama.common.services import process_runs
    from wama.common.utils.queue_duplication import is_shared_elsewhere, owns_file
    field = getattr(item, field_name)
    old = field.name
    data = text.encode('utf-8')
    if old and owns_file(item, old) and not is_shared_elsewhere(item, field_name, old):
        path = field.path
        try:
            with open(path, 'rb') as current:
                if current.read() == data:
                    return False
        except OSError:
            pass
        partial = path + '.part'
        with open(partial, 'wb') as out:
            out.write(data)
        os.replace(partial, path)
        return True
    field.save(os.path.basename(old) if old else f'{field_name}.md', ContentFile(data), save=False)
    item.save(update_fields=[field_name])
    if old:
        process_runs.lines(item).filter(output_ref=old).update(output_ref=field.name)
    return True


def _text(value, limit: int = -1) -> str:
    """Le texte du fichier d'un champ — l'édité entier (`_value_of`), un rôle lu en lecture seule
    plafonné (`Surface.texts`, `MAX_TEXT_CHARS`) ; '' sans fichier ou illisible."""
    if not getattr(value, 'name', ''):
        return ''
    try:
        with open(value.path, encoding='utf-8', errors='replace') as source:
            return source.read(limit)
    except OSError:
        return ''


def _document(value):
    """Un document JSON porté par un champ fichier (`detections_file`), lu tel quel — ou par un
    champ JSON (`segments_json`, 2026-10-21), rendu tel quel : la nature se DÉDUIT de la valeur."""
    if not value:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        with open(value.path, encoding='utf-8') as source:
            return json.load(source)
    except (OSError, ValueError):
        return None


@login_required
@require_POST
def surface_save(request, app: str, key: str, pk: int):
    from django.db import transaction

    from wama.common.services import edit_lock
    from wama.common.utils.scoping import editable_or_404
    found = _surface_or_404(app, key)
    item = editable_or_404(found.model_class(), request.user, trace='corrige', pk=pk)
    try:
        payload = json.loads(request.body or b'{}')
        value = found.clean(payload.get('value'))
        # Un champ des `also_edits` (la partition complète du composer) : seulement s'il existe
        # déjà — un fichier vide ne se crée pas d'ici, il est le résultat de son process.
        field = found.target(item, payload.get('field') or '')
        if field in found.also_edits and not getattr(getattr(item, field, None), 'name', ''):
            raise ValueError(f"« {field} » : rien à éditer, son process ne l'a pas encore écrit")
    except (ValueError, KeyError, TypeError) as error:
        return JsonResponse({'error': str(error)}, status=400)
    # « Terminer » (`Surface.finish`) : le même enregistrement, marqué fini.
    finished = bool(found.finish and payload.get('finished') is True)
    changed = True
    edited = field
    with transaction.atomic():
        item = type(item).objects.select_for_update().get(pk=item.pk)
        conflict = edit_lock.stale_edit(request.user, item, payload.get('base'),
                                        _value_of(found, item, field))
        if conflict:
            return JsonResponse(conflict, status=409)
        if found.text_value:
            # L'état présent d'abord, s'il n'est encore gardé par aucune révision (produit avant
            # que l'app ne garde ses sorties) : réécrit en place, il serait perdu sans retour.
            from wama.common.services.revisions import ensure_kept
            if value != _value_of(found, item, field):
                ensure_kept(app, item, edited)
            changed = _write_text(item, edited, value)
        else:
            setattr(item, edited, value)
            item.save(update_fields=[edited])
    if found.text_value and changed:
        # Un fichier corrigé à la main est un état de la card : une RÉVISION « corrigé à la
        # main » (marche 8a) — la même trace qu'un résultat produit, jamais un geste ajouté.
        from wama.common.models import ItemRevision
        from wama.common.services.revisions import record_revision
        record_revision(app, item, origin=ItemRevision.ORIGIN_MANUAL, user=request.user,
                        output_fields=[edited])
    if found.saved is not None and field not in found.also_edits:
        # Les conséquences propres à l'app, sur la valeur ÉCRITE (`Surface.saved`) — celle du
        # champ principal : un champ des `also_edits` n'en déclare aucune.
        found.saved(item, value, request.user, finished)
    stale = []
    if found.reruns:
        # La péremption suit le champ SURVEILLÉ — on la recalcule ici pour la dire à la page.
        try:
            from wama.common.services.process_pipeline import pipeline_of
            pipeline = pipeline_of(item)
            if pipeline is not None:
                stale = sorted(pipeline.refresh(item))
        except Exception:
            stale = []
    return JsonResponse({'ok': True, 'value': value, 'stale': stale, 'finished': finished,
                         'token': edit_lock.state_token(value), 'field': field})
