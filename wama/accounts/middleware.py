"""
AppAccessMiddleware — défense en profondeur des permissions d'app (phase 2).

Bloque l'accès direct (URL devinée) aux apps métier non autorisées, pour TOUTES leurs vues
(FBV/CBV), sans décorer chaque vue. Garde-fous :
  - ne concerne QUE les apps de APP_CATALOG (préfixe de 1er segment d'URL) ;
  - **admin/développeur** bypassent (via `accessible()`) ;
  - API/AJAX → 403 JSON ; navigation → redirect home + message ;
  - **le VISITEUR sans session VOIT les pages et ne peut RIEN FAIRE** (2026-10-03, ci-dessous).

LE VISITEUR GUIDÉ (décision de Fabien du 2026-08-30, garde posée le 2026-10-03).
`PROFILES_PERMISSIONS §1.4` : un visiteur non connecté parcourt les apps (les pages se voient),
mais aucun GESTE ne passe — sauf sur une app déclarée `public`. Jusqu'ici cette ligne disait
« anonymous laissé au `login_required` des vues » : or la plupart des vues n'en portent pas, et
retombent sur le compte `anonymous` de la base (`get_or_create_anonymous_user`). Mesuré le
2026-10-03 sur le serveur en service : une requête SANS session créait puis LANÇAIT un job
d'avatar (synthèse vocale + rendu GPU, job #591), et le scénario `common.rights_anonymous`
comptait 9 apps dont la vue d'ajout était atteinte.

La garde est ICI, et pas vue par vue : c'est le seul point par lequel passent toutes les routes
de toutes les apps, y compris celles d'une app générée demain. Elle lit la MÊME décision que le
reste (`accessible()` : pour un anonyme, la politique `public` de l'app) — une app ouverte au
visiteur se DÉCLARE, elle ne s'exempte pas ici.
  - méthodes de LECTURE (GET, HEAD, OPTIONS) : laissées — les pages se voient ;
  - toute autre méthode sur une app non publique : 403 JSON, ou retour à l'accueil avec le
    rappel « connectez-vous ».
⚠ Ce que la garde ne couvre PAS : une route en GET qui AGIRAIT (aucune connue — `start` est en
POST depuis le 2026-09-22), et les chemins hors apps (`/common/…`, `/filemanager/…`), gardés
chez eux.
"""
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages

#: Méthodes qui ne font que LIRE : un visiteur sans session y a droit sur toute app.
READ_METHODS = ('GET', 'HEAD', 'OPTIONS')

VISITOR_REFUSAL = "Connectez-vous pour utiliser l'application « {app} » : sans compte, les pages se consultent mais rien ne se lance."


class AppAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        from wama.accounts.permissions import app_id_for_path, accessible
        if user is not None and user.is_authenticated:
            app_id = app_id_for_path(request.path)
            if app_id and not accessible(user, 'app', app_id):
                return self._deny(request, app_id)
        elif request.method not in READ_METHODS:
            app_id = app_id_for_path(request.path)
            if app_id and not accessible(user, 'app', app_id):
                return self._deny(request, app_id, visitor=True)
        return self.get_response(request)

    @staticmethod
    def _deny(request, app_id, visitor=False):
        detail = (VISITOR_REFUSAL.format(app=app_id) if visitor
                  else f"Accès non autorisé à l'application « {app_id} ».")
        wants_json = (
            '/api/' in request.path
            or request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('accept', '')
            # Un geste de visiteur est presque toujours un `fetch` de la page (ajout, lancement) :
            # lui rendre une redirection ferait lire du HTML à du code qui attend du JSON.
            or visitor
        )
        if wants_json:
            return JsonResponse(
                # `error` porte le motif LISIBLE pour un visiteur : les pages affichent ce champ
                # dans leur toast. Pour un compte connecté, le contrat d'origine est inchangé.
                {'error': detail if visitor else 'forbidden', 'detail': detail,
                 **({'login_required': True} if visitor else {})},
                status=403,
            )
        try:
            messages.warning(request, detail)
        except Exception:
            pass
        return redirect('home')
