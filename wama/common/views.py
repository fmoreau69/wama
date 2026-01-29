"""
WAMA Common - Views

Common views for system utilities.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .services.system_monitor import SystemMonitor


@require_GET
def system_stats(request):
    """
    Return current system resource usage for footer display.

    Uses centralized SystemMonitor service.
    """
    return JsonResponse(SystemMonitor.get_footer_stats())


@require_GET
def system_stats_full(request):
    """
    Return full system stats including debug info.
    """
    return JsonResponse(SystemMonitor.get_all_stats())
