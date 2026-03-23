"""
WAMA Common - Views

Common views for system utilities.
"""

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .services.system_monitor import SystemMonitor
from .utils.console_utils import get_console_lines

_STATS_CACHE_KEY = 'wama_footer_stats'
_STATS_CACHE_TTL = 8  # secondes — subprocess wmic/nvidia-smi trop lents pour appel à chaque requête


@require_GET
def system_stats(request):
    """
    Return current system resource usage for footer display.

    Cached 8s in Redis — évite de lancer wmic/nvidia-smi subprocess à chaque poll JS.
    """
    stats = cache.get(_STATS_CACHE_KEY)
    if stats is None:
        stats = SystemMonitor.get_footer_stats()
        cache.set(_STATS_CACHE_KEY, stats, _STATS_CACHE_TTL)
    return JsonResponse(stats)


@require_GET
def system_stats_full(request):
    """
    Return full system stats including debug info.
    Also includes WSL detection info and which data source was used.
    """
    from .services.system_monitor import IS_WSL
    data = SystemMonitor.get_all_stats()
    data['_meta'] = {
        'is_wsl': IS_WSL,
        'wmic': bool(SystemMonitor._find_win_exe(SystemMonitor._WMIC_PATHS)),
        'powershell': bool(SystemMonitor._find_win_exe(SystemMonitor._PS_PATHS)),
    }
    return JsonResponse(data)


@require_GET
def console_content(request):
    """
    Centralized console endpoint with role-based filtering.

    Query params:
        levels: comma-separated log levels (info,warning,error,debug)
        app: app name to filter, or 'all' (admin only)

    Role-based access control:
        user  → forced levels=['info'], app= requested (never 'all')
        dev   → any levels, app= requested (never 'all')
        admin → any levels, any app including 'all'
    """
    from wama.accounts.views import get_user_role, get_or_create_anonymous_user

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    role = get_user_role(user)

    # Parse query params
    levels_raw = request.GET.get('levels', '')
    app = request.GET.get('app', '')

    # Parse levels
    if levels_raw:
        levels = [l.strip() for l in levels_raw.split(',') if l.strip()]
    else:
        levels = None  # all levels

    # Role-based enforcement
    if role == 'user' or role == 'anonymous':
        levels = ['info']
        if app == 'all':
            app = ''
    elif role == 'dev':
        if app == 'all':
            app = ''
    # admin: no restrictions

    lines = get_console_lines(
        user_id=user.id,
        levels=levels,
        app=app if app else None,
        limit=200,
    )

    return JsonResponse({
        'output': lines,
        'role': role,
    })


# ---------------------------------------------------------------------------
# App Registry
# ---------------------------------------------------------------------------

@require_GET
def api_apps(request):
    """
    Return the WAMA application catalog as JSON.
    Used by FileManager JS (APP_EXTENSIONS) and any external consumer.
    """
    from .app_registry import APP_CATALOG, get_app_extensions_for_filemanager, get_conformity_summary
    extensions = get_app_extensions_for_filemanager()
    conformity = get_conformity_summary()

    apps = {}
    for name, spec in APP_CATALOG.items():
        apps[name] = {
            'label':            spec['label'],
            'icon':             spec['icon'],
            'color':            spec.get('color', ''),
            'input_extensions': extensions[name],
            'input_types':      list(spec['input_types']),
            'batch_type':       spec['batch_type'],
            'has_batch':        spec['has_batch'],
            'has_url_import':   spec['has_url_import'],
            'has_youtube':      spec['has_youtube'],
            'output_types':     list(spec['output_types']),
            'conformity':       conformity[name],
        }
    return JsonResponse({'apps': apps})


def apps_catalog_view(request):
    """Render the WAMA application catalog page."""
    from .app_registry import APP_CATALOG, get_conformity_summary
    conformity = get_conformity_summary()

    apps_list = []
    for name, spec in APP_CATALOG.items():
        apps_list.append({
            'name':       name,
            'spec':       spec,
            'conformity': conformity[name],
        })

    return render(request, 'common/apps.html', {'apps_list': apps_list})
