"""
WAMA Common - Views

Common views for system utilities.
"""

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import RedirectView

from .services.system_monitor import SystemMonitor
from .utils.console_utils import get_console_lines

_STATS_CACHE_KEY = 'wama_footer_stats'
_STATS_CACHE_TTL = 8  # secondes — subprocess wmic/nvidia-smi trop lents pour appel à chaque requête


@require_GET
def api_voices(request):
    """
    Options de voix COMMUNES (optgroups) pour l'utilisateur courant — source unique consommée par
    WamaParams (options_source='voices'). Centralise les voix (cf. common/utils/voice_options.py).
    """
    from wama.common.utils.voice_options import get_voice_groups
    from wama.accounts.views import get_or_create_anonymous_user
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    return JsonResponse({'groups': get_voice_groups(user)})


@require_POST
def api_enrich_prompt(request):
    """Enrichissement de prompt À LA DEMANDE (bouton ✨ des apps, éditeur de nœud du studio) —
    endpoint GÉNÉRIQUE : {prompt, app, domain} → skill d'app ([[prompt_skills]]) + LLM local.
    `domain` explicite car avant exécution il n'y a pas d'instance (pas de domain_field) ;
    l'appelant (app ou nœud studio) connaît son app/mode par construction. Émission dans la
    langue de l'utilisateur (il doit pouvoir relire/éditer) — la traduction reste l'affaire de
    la pipeline au lancement de la tâche."""
    import json
    from .utils.prompt_enrichment import enrich_on_demand

    try:
        body = json.loads(request.body)
        prompt = (body.get('prompt') or '').strip()
        app = (body.get('app') or '').strip() or None
        # `mode` accepté en alias (vocabulaire des switch de mode côté apps)
        domain = (body.get('domain') or body.get('mode') or '').strip() or None
        # Mots-clés cliqués par l'utilisateur ([[wama-prompt-chips]]) : ce sont des termes
        # CHOISIS, pas de la prose — ils partent en glossaire pour être préservés VERBATIM par
        # l'enrichissement. Sans ça le LLM les reformule/absorbe et le chip s'éteint tout seul.
        keywords = [str(k).strip() for k in (body.get('keywords') or []) if str(k).strip()]
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not prompt:
        return JsonResponse({'error': 'Prompt vide'}, status=400)
    if len(prompt) > 2000:
        return JsonResponse({'error': 'Prompt trop long (max 2000 caractères)'}, status=400)

    lang = (getattr(getattr(request.user, 'profile', None), 'preferred_language', None) or 'en')
    try:
        enhanced = enrich_on_demand(prompt, app=app, domain=domain, language=lang,
                                    glossary=keywords or None)
        return JsonResponse({'original': prompt, 'enhanced': enhanced,
                             'keywords': keywords})
    except RuntimeError as e:
        return JsonResponse({'error': str(e)})


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


def api_app_modes(request, app):
    """
    Schéma déclaratif domaines→modes d'une app (clé de voûte UX, consommé par WamaModes JS).
    Retourne {app, has_domain_tabs, domains:[…], input_types:{…}}.
    """
    from wama.common.utils import app_modes as M
    return JsonResponse({
        'app': app,
        'has_domain_tabs': M.has_domain_tabs(app),
        'domains': M.get_domains(app),
        'input_types': M.INPUT_TYPES,
    })


def modes_demo(request):
    """Page de prévisualisation isolée du générateur WamaModes (outil de dev)."""
    return render(request, 'common/modes_demo.html')


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
            # Jumelle bac à sable : présente au catalogue (estampillée) mais JAMAIS notée
            # (comparée à sa source) → conformity = None, marqueurs sandbox exposés.
            'conformity':       conformity.get(name),
            'sandbox':          bool(spec.get('sandbox')),
            'generated_from':   spec.get('generated_from', ''),
        }
    return JsonResponse({'apps': apps})


@require_POST
def conformity_refresh(request):
    """Re-mesure la grille de conformité (bouton « Re-mesurer » de /apps/).

    Même mécanique que `manage.py check_app_conformity` — brique commune
    measure_and_write_conformity (domicile unique). Staff uniquement : la mesure
    est peu coûteuse (~1 s, greps de code) mais écrit le rapport global.
    """
    if not (request.user.is_authenticated and request.user.is_staff):
        return JsonResponse({'error': 'Réservé au staff'}, status=403)
    from wama.common.app_registry import measure_and_write_conformity
    report = measure_and_write_conformity()
    return JsonResponse({
        'success': True,
        'generated_at': report['generated_at'],
        'scores': {a: d['pct'] for a, d in report['apps'].items()},
    })


def apps_catalog_view(request):
    """Render the WAMA application catalog page."""
    from .app_registry import APP_CATALOG, get_conformity_summary
    conformity = get_conformity_summary()

    from django.urls import reverse, NoReverseMatch

    apps_list = []
    for name, spec in APP_CATALOG.items():
        try:
            url = reverse(spec['url_name']) if spec.get('url_name') else ''
        except NoReverseMatch:
            url = ''
        apps_list.append({
            'name':       name,
            'spec':       spec,
            # None pour une jumelle bac à sable (estampillée, jamais notée) — le
            # template affiche alors le tampon sandbox à la place de la barre.
            'conformity': conformity.get(name),
            'url':        url,
        })

    # ── Groupage par CATÉGORIE (APP_CATEGORIES, déclaratif + dérivable — décision 2026-07-05).
    # apps_list reste passé tel quel pour la table de conformité (ordre alphabétique).
    from .app_registry import APP_CATEGORIES, derive_category
    by_name = {a['name']: a for a in apps_list}
    apps_grouped = []
    for cid, meta in sorted(APP_CATEGORIES.items(), key=lambda kv: kv[1].get('order', 99)):
        items = [by_name[n] for n, s in APP_CATALOG.items()
                 if (s.get('category') or derive_category(s)) == cid]
        links = []
        for link in meta.get('extra_links', []):
            try:
                links.append({**link, 'url': reverse(link['url_name'])})
            except NoReverseMatch:
                continue  # surface pas encore installée → lien omis, pas d'erreur
        if items or links:
            apps_grouped.append({'id': cid, 'meta': meta, 'apps': items, 'links': links})

    # Horodatage de la dernière MESURE (le plus récent des measured_at par app) —
    # affiché à côté du bouton « Re-mesurer » de la grille.
    measured_at = max(((a.get('conformity') or {}).get('measured_at') or ''
                       for a in apps_list), default='') or None
    if measured_at:
        measured_at = measured_at.replace('T', ' ')[:16]

    return render(request, 'common/apps.html',
                  {'apps_list': apps_list, 'apps_grouped': apps_grouped,
                   'conformity_measured_at': measured_at})


def licenses_catalog_view(request):
    """
    Catalogue des LICENCES — vue transversale, sans registre propre.

    Agrège `AIModel`, `Library`, `UserAsset`/`SystemAsset` et recoupe la composition déclarée
    par les `requires` des manifestes d'app. Rien n'est stocké ici : une page qui DÉRIVE ne peut
    pas diverger de ses sources, un cinquième registre l'aurait fait tôt ou tard.

    Les médias utilisateur sont filtrés sur le périmètre visible du demandeur — une page d'audit
    n'a pas à révéler la médiathèque des autres.
    """
    from .services.license_audit import synthese

    return render(request, 'common/licenses.html',
                  {'audit': synthese(request.user if request.user.is_authenticated else None)})


@login_required
def journal_view(request):
    """
    Journal de l'utilisateur — tout ce qu'il a lancé dans WAMA, toutes apps confondues.
    Doc : `WAMA_MEMORY.md §9bis`.

    Vue TRANSVERSALE qui DÉRIVE, comme le catalogue des licences : aucune table propre, aucune
    ligne dans les apps. Les sources viennent de `detail_registry` (que chaque app alimente déjà
    pour l'inspecteur), le tri/la pagination du service, les chips du schéma params.

    `@login_required` n'est pas décoratif : le journal est personnel par définition, et une page
    qui filtre sur `request.user` sans exiger l'authentification rendrait une page vide et
    trompeuse à un anonyme au lieu de l'envoyer se connecter.
    """
    from django.urls import reverse

    from .services.journal import STATUTS, TRIS, compter_par_app, entrees

    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    limite = 25
    app = (request.GET.get('app') or '').strip() or None

    # Préférences persistées en session, comme la barre d'outils des files. ⚠ Clés PROPRES au
    # journal (`journal_*`) et NON les `q_sort`/`q_filter` partagés : le vocabulaire diffère
    # (pas de batchs ici, donc pas de `batches_first` ni de `draft`), et écrire dans les clés
    # communes changerait silencieusement l'ordre des files de toutes les apps depuis une page
    # qui n'en est pas une.
    tri = request.GET.get('tri') or request.session.get('journal_tri') or 'recent'
    statut = request.GET.get('statut') or request.session.get('journal_statut') or 'all'
    # La barre commune envoie `all` pour son option « tout » ; côté tri, « tout » n'a pas de sens
    # — c'est le tri PAR DÉFAUT. On traduit ici plutôt que d'inventer une option `all` dans TRIS,
    # qui obligerait chaque appelant du service à connaître une valeur qui ne trie rien.
    if tri == 'all':
        tri = 'recent'
    tri = tri if tri in TRIS else 'recent'
    statut = statut if statut in STATUTS else 'all'
    request.session['journal_tri'] = tri
    request.session['journal_statut'] = statut
    # La recherche n'est PAS persistée : une recherche oubliée en session ferait revenir sur une
    # page filtrée sans qu'on comprenne pourquoi elle semble vide.
    q = (request.GET.get('q') or '').strip()

    page, total = entrees(request.user, apps=[app] if app else None,
                          limite=limite, offset=offset, tri=tri, statut=statut, q=q)

    # Facettes de la barre commune (`common/_filter_bar.html`). En mode `server` les options
    # DOIVENT être déclarées : le DOM ne porte qu'une page, la brique ne peut donc pas les
    # dériver comme elle le fait sur les catalogues.
    facettes = [
        {'cle': 'tri', 'label': 'Trier', 'tous': 'Plus récent',
         'options': {c: l for c, l in TRIS.items() if c != 'recent'}, 'valeur': tri},
        {'cle': 'statut', 'label': 'État', 'tous': STATUTS['all'],
         'options': {c: l for c, l in STATUTS.items() if c != 'all'}, 'valeur': statut},
    ]

    return render(request, 'common/journal.html', {
        'page': page,
        'total': total,
        'app_active': app,
        'tri': tri,
        'statut': statut,
        'q': q,
        'facettes': facettes,
        'url_reset': f"{reverse('common:journal')}{'?app=' + app if app else ''}",
        'repartition': compter_par_app(request.user),
        'debut': offset + 1 if page else 0,
        'fin': offset + len(page),
        'precedent': max(0, offset - limite) if offset else None,
        'suivant': offset + limite if offset + limite < total else None,
    })


# ── Brique À-propos / Aide (2026-08-11) ──────────────────────────────────────────
# L'À-propos et l'Aide sont des ONGLETS du gabarit commun (`app_modern_base.html`,
# blocs `about_content`/`help_content` auto-remplis d'APP_CATALOG via le context
# processor). Les routes `/about/` et `/help/` de chaque app REDIRIGENT vers l'onglet
# (ancre ouverte par `wama-app-base.js`) : une page à part dupliquerait la page d'app.
# Avant cette brique, 12 CBV locales pointaient des templates INEXISTANTS (500 mesuré
# sur 9 apps / 10 le 2026-08-11 — seul converter, qui re-rendait sa base, répondait).
class AppTabRedirectView(RedirectView):
    """Redirige `/<app>/about|help/` vers l'index de l'app, ancré sur l'onglet.

    `app_id` : explicite via `as_view(app_id='imager')`, sinon dérivé du 1er segment
    du path (même convention que `app_id_for_path` / le context processor).
    """
    permanent = False
    tab_anchor = ''          # posé par les sous-classes
    app_id = None

    def get_redirect_url(self, *args, **kwargs):
        from django.urls import reverse
        from .app_registry import APP_CATALOG
        app_id = self.app_id or (self.request.path.split('/') + [''])[1]
        spec = APP_CATALOG.get(app_id)
        if not spec or not spec.get('url_name'):
            return '/'
        return reverse(spec['url_name']) + f'#{self.tab_anchor}'


class AppAboutView(AppTabRedirectView):
    tab_anchor = 'about-pane'


class AppHelpView(AppTabRedirectView):
    tab_anchor = 'help-pane'
