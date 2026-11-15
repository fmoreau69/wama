"""La route du VOLET en briques (2026-10-28, `WAMA_VOLETS §3-ter` étape ②) — la disposition que
chacun donne aux sections du volet d'une page, gardée par compte comme celle d'une surface
(`surface_views.surface_layout`) et validée par la même règle (`surfaces.clean_layout`).

  layout  POST  /common/panel/layout/<page>/     places, piles, épinglage, figé ou non
  hint    POST  /common/panel/hint/              la bulle du premier passage a été montrée
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


@login_required
@require_POST
def brick_keys(request):
    """Les touches qu'un compte donne aux actions d'UNE brique (`WAMA_VOLETS §3-ter`, 2026-11-15) :
    `{brick, keys: {action: [touches]}}` — la surcharge entière de la brique, vide pour tout
    rétablir. Refusée (400) avec ce qui la rend inapplicable ; sinon rend les raccourcis de la
    brique tels qu'ils se lisent désormais."""
    import json

    from wama.common.utils.user_keys import key_rows, save_user_keys, user_keymap
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'problems': ['requête illisible']}, status=400)
    brick = str(payload.get('brick') or '')
    problems = save_user_keys(request.user, brick, payload.get('keys') or {})
    if problems:
        return JsonResponse({'ok': False, 'problems': problems}, status=400)
    account_keys = user_keymap(request.user)
    return JsonResponse({'ok': True, 'keys': account_keys.get(brick, {}),
                         'rows': key_rows(brick, account_keys)})


@login_required
@require_POST
def page_hint_seen(request):
    """La bulle du premier passage (« cette page se réorganise ») a été MONTRÉE à ce compte : elle
    ne revient plus (2026-10-29, décision de Fabien : une fois par compte, gardé au serveur)."""
    from wama.common.utils.user_settings import save_user_app_settings
    from wama.common.utils.volet import HINT_APP, HINT_SETTING
    save_user_app_settings(request.user, HINT_APP, {HINT_SETTING: True})
    return JsonResponse({'ok': True})
