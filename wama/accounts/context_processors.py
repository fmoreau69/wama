"""
Context processors for the accounts app.
"""
import json as _json


def user_role(request):
    """Add user role and preferences to template context."""
    from .views import is_admin, is_dev, get_user_role

    user = request.user

    # Preferred language + UI mode (defaults for unauthenticated users)
    preferred_language = 'fr'
    ui_mode = 'advanced'
    card_layout = 'list'
    if user.is_authenticated:
        try:
            preferred_language = user.profile.preferred_language
            ui_mode = user.profile.ui_mode
            card_layout = user.profile.card_layout
        except Exception:
            pass

    # App catalog JSON — injected into base.html for FileManager JS
    # Computed once per request; small enough that caching isn't necessary
    try:
        from wama.common.app_registry import get_app_extensions_for_filemanager, APP_CATALOG
        _ext = get_app_extensions_for_filemanager()
        _catalog_for_js = {
            name: {
                'label': spec['label'],
                'icon':  spec['icon'],
                'color': spec.get('color', ''),
                'input_extensions': _ext[name],
                'has_batch':      spec['has_batch'],
                'has_url_import': spec['has_url_import'],
                # Catégorie + couleur d'identité dérivée (APP_CATEGORIES / CARD_DESIGN §9) :
                # la nav, le studio et le filemanager peuvent grouper/teinter (2026-07-05).
                'category':       spec.get('category', ''),
                'color':          spec.get('color', ''),
            }
            for name, spec in APP_CATALOG.items()
        }
        app_catalog_json = _json.dumps(_catalog_for_js)
    except Exception:
        app_catalog_json = '{}'

    try:
        from wama.converter.utils.format_router import CONVERTER_OUTPUT_FORMATS
        converter_output_formats_json = _json.dumps(CONVERTER_OUTPUT_FORMATS)
    except Exception:
        converter_output_formats_json = '{}'

    # Accès par profil/rôles (axe A tier + axe B rôles métier) — exposé pour filtrer la nav.
    # Non bloquant ici : c'est la nav/les vues qui décideront d'utiliser `accessible_apps`.
    try:
        from wama.accounts.permissions import user_tier, user_roles as _roles, accessible, all_gated_apps
        account_tier = user_tier(user)
        roles_set = sorted(_roles(user))
        accessible_apps = {a for a in all_gated_apps() if accessible(user, a)}
    except Exception:
        account_tier, roles_set, accessible_apps = 'utilisateur', [], set()

    # Menu « Applications » GROUPÉ par catégorie (APP_CATEGORIES) — GÉNÉRÉ du catalogue,
    # filtré par accessible_apps ; les extra_links portent gate/nav_hide (décision 2026-07-05).
    try:
        from django.urls import reverse as _reverse
        from wama.common.app_registry import get_apps_by_category
        nav_apps_grouped = []
        for _cid, _meta, _apps in get_apps_by_category():
            _entries = []
            for _name, _spec in _apps:
                if _name not in accessible_apps:
                    continue
                try:
                    _entries.append({'name': _name, 'label': _spec['label'], 'icon': _spec['icon'],
                                     'color': _spec.get('color', ''), 'url': _reverse(_spec['url_name']),
                                     'description': _spec.get('description', '')})
                except Exception:
                    continue
            _links = []
            for _link in _meta.get('extra_links', []):
                if _link.get('nav_hide'):
                    continue
                _gate = _link.get('gate')
                if _gate and _gate not in accessible_apps:
                    continue
                try:
                    _links.append({**_link, 'url': _reverse(_link['url_name'])})
                except Exception:
                    # JAMAIS d'omission silencieuse (leçon WAMA Lab disparu, 2026-07-05) :
                    # un lien déclaré qui ne résout pas = un warning visible dans les logs.
                    import logging
                    logging.getLogger('wama.nav').warning(
                        "Menu : lien '%s' (%s) omis — URL irrésolvable",
                        _link.get('label'), _link.get('url_name'))
                    continue
            if _entries or _links:
                nav_apps_grouped.append({'id': _cid, 'meta': _meta, 'apps': _entries, 'links': _links})
    except Exception:
        nav_apps_grouped = []

    # Couleur d'IDENTITÉ de l'app courante (liseré des cards — CARD_DESIGN §9) : dérivée du
    # 1er segment du path si c'est une app du catalogue. Identité ≠ état (jamais sur les barres).
    current_app_color = ''
    try:
        from wama.common.app_registry import APP_CATALOG as _AC
        _seg = (request.path.split('/') + [''])[1]
        if _seg in _AC:
            current_app_color = _AC[_seg].get('color', '')
    except Exception:
        pass

    return {
        'is_admin': is_admin(user),
        'is_dev': is_dev(user),
        'user_role': get_user_role(user),
        'preferred_language': preferred_language,
        'ui_mode': ui_mode,
        'card_layout': card_layout,
        'app_catalog_json': app_catalog_json,
        'nav_apps_grouped': nav_apps_grouped,
        'current_app_color': current_app_color,
        'converter_output_formats_json': converter_output_formats_json,
        'account_tier': account_tier,
        'user_roles_set': roles_set,
        'accessible_apps': accessible_apps,
    }
