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
                # Catégorie (APP_CATEGORIES) : la nav / le studio peuvent grouper (2026-07-05).
                'category':       spec.get('category', ''),
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

    return {
        'is_admin': is_admin(user),
        'is_dev': is_dev(user),
        'user_role': get_user_role(user),
        'preferred_language': preferred_language,
        'ui_mode': ui_mode,
        'card_layout': card_layout,
        'app_catalog_json': app_catalog_json,
        'converter_output_formats_json': converter_output_formats_json,
        'account_tier': account_tier,
        'user_roles_set': roles_set,
        'accessible_apps': accessible_apps,
    }
