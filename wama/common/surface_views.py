"""Les vues COMMUNES des surfaces (`common/surfaces.py`) — une app DÉCLARE une surface, elle
n'écrit ni page, ni lecture, ni enregistrement (2026-10-10, chantier SURFACES).

  page    GET   /common/surface/<app>/<clé>/<pk>/        la page : grille des briques
  data    GET   …/data/                                  ce que les briques lisent (JSON)
  save    POST  …/save/                                  le champ édité, validé par la surface

Droits : LIRE = voir la card (la règle de l'aperçu, `PreviewRegistry.check_permission`, cards
partagées comprises) ; ÉCRIRE = l'éditer (`scoping.editable_or_404` : le propriétaire ou un
collaborateur nommé, dont le geste est tracé `corrige`).
"""
from __future__ import annotations

import json

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
    reads = {}
    for role, field_name in found.reads.items():
        value = getattr(item, field_name, None)
        if role in found.documents:
            reads[role] = _document(value)
        else:
            reads[role] = value.url if value else ''
    return JsonResponse({
        'reads': reads,
        'value': getattr(item, found.edits, None) or {},
        'context': found.context_of(item),
        'can_edit': _can_edit(request.user, item),
    })


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
    from wama.common.utils.scoping import editable_or_404
    found = _surface_or_404(app, key)
    item = editable_or_404(found.model_class(), request.user, trace='corrige', pk=pk)
    try:
        payload = json.loads(request.body or b'{}')
        value = found.validate(payload.get('value'))
    except (ValueError, KeyError, TypeError) as error:
        return JsonResponse({'error': str(error)}, status=400)
    setattr(item, found.edits, value)
    item.save(update_fields=[found.edits])
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
    return JsonResponse({'ok': True, 'value': value, 'stale': stale})
