"""Les vues COMMUNES des surfaces (`common/surfaces.py`) — une app DÉCLARE une surface, elle
n'écrit ni page, ni lecture, ni enregistrement (2026-10-10, chantier SURFACES).

  page    GET   /common/surface/<app>/<clé>/<pk>/        la page : grille des briques
  data    GET   …/data/                                  ce que les briques lisent (JSON)
  save    POST  …/save/                                  le champ édité, validé par la surface

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


@login_required
@require_GET
def surface_page(request, app: str, key: str, pk: int):
    found = _surface_or_404(app, key)
    item = _readable_or_404(found, request.user, pk)
    ok, reason = found.can_open(item)
    base = f'/common/surface/{app}/{key}/{pk}/'
    return render(request, 'common/surface.html', {
        'surface': found,
        'item': item,
        'available': ok,
        'reason': reason,
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
            'layout_key': f'wama.surface.{found.id}',
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
    from wama.common.services.edit_lock import state_token
    reads = {}
    for role, field_name in found.reads.items():
        value = getattr(item, field_name, None)
        if role in found.documents:
            reads[role] = _document(value)
        else:
            reads[role] = value.url if value else ''
    if request.GET.get('only') == 'state':
        # Le SUIVI d'un process rejoué (« Appliquer ») : ce que les briques relisent, sans la
        # valeur éditée — que la page tient déjà, et qui peut peser un document entier.
        return JsonResponse({'reads': reads, 'processes': _process_states(item)})
    value = _value_of(found, item)
    return JsonResponse({
        'processes': _process_states(item),
        'reads': reads,
        'value': value,
        'context': found.context_of(item),
        'can_edit': _can_edit(request.user, item),
        'token': state_token(value),
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
            'kept': bool(kept_file(app, item, revision.number, found.edits)),
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
    rel = kept_file(app, item, number, found.edits) if found.text_value else ''
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


def _value_of(found, item):
    """La valeur ÉDITÉE telle que la page la reçoit : le texte du fichier, ou le champ de donnée."""
    if found.text_value:
        field = getattr(item, found.edits, None)
        if not getattr(field, 'name', ''):
            return ''
        try:
            with open(field.path, encoding='utf-8', errors='replace') as source:
                return source.read()
        except OSError:
            return ''
    return getattr(item, found.edits, None) or {}


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


def _document(value):
    """Un document JSON porté par un champ fichier (`detections_file`), lu tel quel."""
    if not value:
        return None
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
    except (ValueError, KeyError, TypeError) as error:
        return JsonResponse({'error': str(error)}, status=400)
    changed = True
    with transaction.atomic():
        item = type(item).objects.select_for_update().get(pk=item.pk)
        conflict = edit_lock.stale_edit(request.user, item, payload.get('base'),
                                        _value_of(found, item))
        if conflict:
            return JsonResponse(conflict, status=409)
        if found.text_value:
            changed = _write_text(item, found.edits, value)
        else:
            setattr(item, found.edits, value)
            item.save(update_fields=[found.edits])
    if found.text_value and changed:
        # Un fichier corrigé à la main est un état de la card : une RÉVISION « corrigé à la
        # main » (marche 8a) — la même trace qu'un résultat produit, jamais un geste ajouté.
        from wama.common.models import ItemRevision
        from wama.common.services.revisions import record_revision
        record_revision(app, item, origin=ItemRevision.ORIGIN_MANUAL, user=request.user,
                        output_fields=[found.edits])
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
    return JsonResponse({'ok': True, 'value': value, 'stale': stale,
                         'token': edit_lock.state_token(value)})
