"""La route du VOLET en briques (2026-10-28, `WAMA_VOLETS §3-ter` étape ②) — la disposition que
chacun donne aux sections du volet d'une page, gardée par compte comme celle d'une surface
(`surface_views.surface_layout`) et validée par la même règle (`surfaces.clean_layout`).

  layout  POST  /common/panel/layout/<page>/     places, piles, épinglage, figé ou non
"""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST


@login_required
@require_POST
def panel_layout(request, page: str):
    """Garde la disposition du volet de la page `page` pour ce compte : une préférence de
    LECTURE, comme la disposition d'une surface — rien d'autre ne change."""
    from wama.common.surfaces import clean_layout
    from wama.common.utils.user_settings import save_user_app_settings
    from wama.common.utils.volet import LAYOUT_SETTING, PAGE_KEY, declaration
    if not PAGE_KEY.match(page):
        raise Http404('page inconnue')
    try:
        layout = clean_layout(declaration(page), json.loads(request.body or b'{}'))
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    save_user_app_settings(request.user, page, {LAYOUT_SETTING: layout})
    return JsonResponse({'ok': True, 'layout': layout})
