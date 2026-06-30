"""
AppAccessMiddleware — défense en profondeur des permissions d'app (phase 2).

Bloque l'accès direct (URL devinée) aux apps métier non autorisées, pour TOUTES leurs vues
(FBV/CBV), sans décorer chaque vue. Garde-fous :
  - ne concerne QUE les apps de APP_CATALOG (préfixe de 1er segment d'URL) ;
  - **anonymous** laissé au `login_required` des vues (redirige vers login, UX standard) ;
  - **admin/développeur** bypassent (via `accessible()`) ;
  - API/AJAX → 403 JSON ; navigation → redirect home + message.
"""
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages


class AppAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            from wama.accounts.permissions import app_id_for_path, accessible
            app_id = app_id_for_path(request.path)
            if app_id and not accessible(user, app_id):
                return self._deny(request, app_id)
        return self.get_response(request)

    @staticmethod
    def _deny(request, app_id):
        wants_json = (
            '/api/' in request.path
            or request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('accept', '')
        )
        if wants_json:
            return JsonResponse(
                {'error': 'forbidden', 'detail': f"Accès non autorisé à l'application « {app_id} »."},
                status=403,
            )
        try:
            messages.warning(request, f"Accès non autorisé à l'application « {app_id} ».")
        except Exception:
            pass
        return redirect('home')
