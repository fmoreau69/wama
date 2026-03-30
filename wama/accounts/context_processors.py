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
    if user.is_authenticated:
        try:
            preferred_language = user.profile.preferred_language
            ui_mode = user.profile.ui_mode
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
            }
            for name, spec in APP_CATALOG.items()
        }
        app_catalog_json = _json.dumps(_catalog_for_js)
    except Exception:
        app_catalog_json = '{}'

    return {
        'is_admin': is_admin(user),
        'is_dev': is_dev(user),
        'user_role': get_user_role(user),
        'preferred_language': preferred_language,
        'ui_mode': ui_mode,
        'app_catalog_json': app_catalog_json,
    }
