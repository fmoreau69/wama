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
from .utils.volet import VOLET_AUCUN

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
def registre_refresh(request, cle):
    """Actualise N'IMPORTE QUEL registre catalogué — endpoint UNIQUE.

    C'est le pendant serveur de `wama-catalog-refresh.js` : la page ne déclare que la CLÉ de son
    registre et hérite de tout le reste (permission, chronométrage, compte-rendu uniforme). Écrire
    un endpoint par catalogue était la dérive à arrêter — il y en avait déjà deux, avec des
    réponses de formes différentes.
    """
    from .registries import execution_of, get, launch
    try:
        registre = get(cle)
    except KeyError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=404)
    charge = launch(cle, user=request.user)
    if not charge.get('ok') and 'réservé' in (charge.get('error') or ''):
        return JsonResponse(charge, status=403)
    charge['registre'] = {'key': registre.key, 'label': registre.label,
                          'nature': registre.nature, 'execution': execution_of(registre)}
    # ⚠ Une actualisation MISE EN FILE est un succès de mise en file, pas un succès d'exécution :
    # elle rend 202, et le client interroge `registre_tache`. Rendre 200 laisserait croire que le
    # travail est fait — or il commence à peine.
    if charge.get('async') and charge.get('ok'):
        return JsonResponse(charge, status=202)
    return JsonResponse(charge, status=200 if charge.get('ok') else 500)


def registre_tache(request, task_id):
    """État d'une actualisation lancée en arrière-plan. Générique, comme le reste."""
    from .registries import task_state
    return JsonResponse(task_state(task_id))


def registres_etat(request):
    """État de tous les registres — ce qui s'actualise, comment, et par quel moyen.

    Sert la page de supervision et rend le mécanisme LISIBLE : sans cette vue, savoir quels
    catalogues se tiennent à jour tout seuls exigeait de lire `CELERY_BEAT_SCHEDULE`.
    """
    from .registries import overview
    return JsonResponse({'registres': overview()})


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

    # ── ABONNEMENT (PROFILES_PERMISSIONS §8) : DROIT d'abord, PRÉFÉRENCE ensuite.
    # Le catalogue montre TOUT — c'est sa raison d'être : masquer ici priverait l'utilisateur du
    # seul endroit où retrouver ce qu'il a lui-même masqué (et, plus tard, où DEMANDER un accès
    # qu'il n'a pas). Chaque card porte donc son état, jamais son absence.
    from wama.accounts.permissions import accessible
    from .services.subscriptions import masques as _masques, resume as _resume_abo
    apps_masquees = _masques(request.user, 'app')

    apps_list = []
    for name, spec in APP_CATALOG.items():
        try:
            url = reverse(spec['url_name']) if spec.get('url_name') else ''
        except NoReverseMatch:
            url = ''
        autorisee = accessible(request.user, 'app', name)
        apps_list.append({
            'name':       name,
            'spec':       spec,
            # None pour une jumelle bac à sable (estampillée, jamais notée) — le
            # template affiche alors le tampon sandbox à la place de la barre.
            'conformity': conformity.get(name),
            'url':        url,
            'autorisee':  autorisee,
            # `abonne` n'a de sens QUE si l'app est autorisée : sur une app fermée, la bascule
            # n'est pas « décochée », elle est absente — sinon elle laisserait croire qu'un clic
            # ouvre un droit (§8.1 : une préférence ne peut jamais élargir).
            'abonne':     autorisee and name not in apps_masquees,
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
                url = reverse(link['url_name'])
            except NoReverseMatch:
                continue  # surface pas encore installée → lien omis, pas d'erreur
            # Les surfaces TRANSVERSALES (studio, médiathèque, model_manager) et Lab sont des
            # extra_links, pas des cards de catalogue — mais elles sont gardées par le MÊME
            # `accessible()` et doivent donc être masquables par le MÊME abonnement. La clé est
            # `gate` (= l'app_id) : c'est déjà celle du droit, en réutiliser une autre ferait
            # deux déclarations pour une seule chose. Sans `gate` → surface publique, ni gardée
            # ni masquable (et le template n'affiche alors ni bascule ni badge).
            #
            # ⚠ `nav_hide` : le lien n'est PAS dans le menu Applications (le model_manager a son
            # entrée dans la section Administration). Masquer une telle surface ne changerait
            # rien nulle part — donc pas de bascule : une bascule sans effet est exactement le
            # mécanisme muet que le dépôt traque. Le contrôle d'ACCÈS, lui, s'affiche quand même.
            gate = link.get('gate')
            autorisee = accessible(request.user, 'app', gate) if gate else True
            abonnable = bool(gate) and not link.get('nav_hide')
            links.append({**link, 'url': url, 'gate': gate,
                          'autorisee': autorisee,
                          'abonnable': abonnable,
                          'abonne': abonnable and autorisee and gate not in apps_masquees})
        if items or links:
            apps_grouped.append({'id': cid, 'meta': meta, 'apps': items, 'links': links})

    # Horodatage de la dernière MESURE (le plus récent des measured_at par app) —
    # affiché à côté du bouton « Re-mesurer » de la grille.
    measured_at = max(((a.get('conformity') or {}).get('measured_at') or ''
                       for a in apps_list), default='') or None
    if measured_at:
        measured_at = measured_at.replace('T', ' ')[:16]

    # Facette « catégorie » SANS options : en mode client la brique les dérive du DOM, et les
    # libellés y sont déjà lisibles (« Comprendre », « Créer »…). Rien à déclarer, donc rien qui
    # puisse diverger des catégories réellement présentes.
    facettes = [{'cle': 'categorie', 'label': 'Catégorie', 'tous': 'Toutes les catégories'}]

    # Facette d'ABONNEMENT — DÉCLARÉE (et non dérivée du DOM) : ses valeurs sont des clés
    # techniques derrière des libellés français, et surtout l'ordre compte (« mes applications »
    # d'abord, c'est la vue par défaut promise à l'utilisateur). Même motif que /licences/.
    facettes.append({'cle': 'abonnement', 'label': 'Abonnement', 'tous': 'Toutes',
                     'options': {'mes': 'Mes applications', 'masquees': 'Masquées',
                                 'fermees': 'Sans accès'}})

    # Périmètre de l'abonnement = TOUT ce qui est gardé ET autorisé ET a une surface sur cette
    # page — cards du catalogue *plus* liens transversaux/Lab. Avant le 27/08 ce périmètre était
    # les seules cards : le bandeau « N sur M » comptait donc autre chose que ce que le sélecteur
    # tout/rien touchait, et les 5 surfaces à extra_links n'étaient masquables par rien.
    autorisees = [a['name'] for a in apps_list if a['autorisee']]
    for groupe in apps_grouped:
        for lien in groupe['links']:
            if lien['abonnable'] and lien['autorisee'] and lien['gate'] not in autorisees:
                autorisees.append(lien['gate'])

    # ── 2ᵉ grille : la FONCTIONNELLE (WAMA_VERIFICATION §2, décidée le 22/08, câblée le
    # 01/09). L'adoption ci-dessus dit « le code contient la brique » ; celle-ci dit « le
    # geste exécuté a produit l'effet » — dernier verdict de CHAQUE scénario nocturne,
    # jamais « le dernier run » (un run est souvent partiel). Les scénarios enregistrés
    # jamais exécutés y figurent : ne montrer que ce qui a tourné surestimerait la couverture.
    grille_droits = []
    try:
        from .nightly_scenarios import register_scenarios
        register_scenarios()
        from .services.nightly_tests import functional_grid
        grille_fonctionnelle = functional_grid()
        # ── 3ᵉ grille : les DROITS (WAMA_VERIFICATION §3ter — branchée le 01/09). Orthogonale
        # aux deux autres, PAS un sous-cas : un geste peut marcher parfaitement pour quelqu'un
        # qui n'aurait pas dû l'atteindre. Les scénarios common.rights_* sont donc EXTRAITS de
        # la grille fonctionnelle (les compter deux fois brouillerait les deux lectures) et
        # rendus dans leur propre section, verdict et détail complets.
        commun = grille_fonctionnelle.get('common')
        if commun:
            grille_droits = [s for s in commun['scenarios'] if s['id'].startswith('common.rights')]
            for s in grille_droits:
                commun['scenarios'].remove(s)
                cle = 'never' if s['never_run'] else ('skip' if s['skipped']
                                                     else ('ok' if s['ok'] else 'ko'))
                commun[cle] -= 1
    except Exception:
        grille_fonctionnelle = {}   # la grille d'adoption reste servie même si celle-ci casse

    return render(request, 'common/apps.html',
                  {'apps_list': apps_list, 'apps_grouped': apps_grouped,
                   'conformity_measured_at': measured_at,
                   'facettes_apps': facettes,
                   'grille_fonctionnelle': grille_fonctionnelle,
                   'grille_droits': grille_droits,
                   'abo': _resume_abo(request.user, 'app', autorisees),
                   'abo_ids': autorisees})


@require_POST
@login_required
def api_subscription(request):
    """Bascule d'ABONNEMENT — la couche PRÉFÉRENCE (PROFILES_PERMISSIONS §8).

    `{kind, element_id, subscribed}` pour un élément, ou `{kind, all: true|false, ids: [...]}`
    pour le sélecteur tout/rien.

    ⚠ Cet endpoint ne peut RIEN OUVRIR : le service ne sait qu'écrire ou effacer un masquage, et
    aucune décision d'accès ne lit cette table. C'est ce qui autorise un simple `@login_required`
    là où un endpoint de DROITS exigerait la modération (§8.1). `@login_required` reste requis :
    sans utilisateur, il n'y a pas de préférence à écrire.
    """
    import json
    from .services.subscriptions import KINDS, definir, definir_lot, masques
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    kind = data.get('kind') or ''
    if kind not in KINDS:
        return JsonResponse({'error': f'nature inconnue : {kind}'}, status=400)

    if 'all' in data:
        n = definir_lot(request.user, kind, data.get('ids') or [], bool(data['all']))
        return JsonResponse({'ok': True, 'kind': kind, 'changed': n,
                             'masques': sorted(masques(request.user, kind))})

    element_id = data.get('element_id') or ''
    if not element_id:
        return JsonResponse({'error': 'element_id manquant'}, status=400)
    etat = definir(request.user, kind, element_id, bool(data.get('subscribed')))
    return JsonResponse({'ok': True, 'kind': kind, 'element_id': element_id, 'subscribed': etat})


def registres_view(request):
    """
    Page des REGISTRES — la carte de ce qui se tient à jour, et comment.

    POURQUOI ELLE MANQUAIT. Le registre des registres a été construit pour que chaque page
    catalogue HÉRITE de son bouton d'actualisation ; l'endpoint `api/registres/` existait
    déjà et son docstring annonçait « sert la page de supervision » — mais aucune page ne le
    rendait. Résultat : savoir quels catalogues se rafraîchissent seuls exigeait de lire
    `CELERY_BEAT_SCHEDULE`, et le mécanisme restait invisible à qui ne lit pas le code.

    Elle DÉRIVE entièrement de `registries.overview()` : aucune donnée propre, donc aucune
    divergence possible avec le registre. Ajouter un registre l'y fait apparaître seul.

    ⚠ La NATURE est ce que la page montre en premier, parce que c'est elle qui dit si un
    bouton a du sens : un « Actualiser » sur un catalogue DÉRIVÉ (recalculé à chaque
    requête) serait un mensonge — il ne ferait rien et laisserait croire que le reste est
    périmé. Les dérivés affichent donc « toujours à jour », pas un bouton inerte.
    """
    from .registries import overview

    # `with_coverage` : la page dit AUSSI ce qui est eprouve. La couverture est MESUREE
    # (lecture des fichiers de test), jamais declaree -- un champ a tenir a jour aurait menti.
    registres = overview(with_coverage=True)

    # Facettes DÉCLARÉES (et non dérivées du DOM) : les valeurs brutes sont des clés
    # techniques (`scan`, `derive`…) alors que la page affiche des libellés français —
    # déclarer prime sur dériver dès que le libellé compte (même motif que /licences/).
    from .registries import NATURES
    facettes = [{
        'cle': 'nature', 'label': 'Nature', 'tous': 'Toutes les natures',
        'options': dict(NATURES),
    }]

    return render(request, 'common/registres.html', {
        'registres': registres,
        'total_entrees': sum(r['total'] for r in registres),
        'nb_actualisables': sum(1 for r in registres if r['refreshable']),
        'nb_periodiques': sum(1 for r in registres if r['periodic']),
        'facettes_registres': facettes,
        'peut_actualiser': request.user.is_authenticated,
        'est_staff': request.user.is_authenticated and request.user.is_staff,
        # Page de SUPERVISION : tout y est dans le corps (cf. WAMA_VOLETS §2 — elle figurait
        # parmi les 17 pages héritant de 3 cadres vides).
        'volet': VOLET_AUCUN,
    })


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

    # Facettes de la barre commune. Les options sont DÉCLARÉES bien qu'on soit en mode client :
    # la dérivation depuis le DOM rendrait les valeurs brutes (« model », « library »), alors que
    # la page affichait des libellés français. Déclarer prime sur dériver quand le libellé compte.
    facettes = [{
        'cle': 'registre', 'label': 'Registre', 'tous': 'Tous les registres',
        'options': {'model': 'Modèles', 'library': 'Librairies', 'media': 'Médias'},
    }]

    return render(request, 'common/licenses.html',
                  {'audit': synthese(request.user if request.user.is_authenticated else None),
                   'facettes_licences': facettes,
                   'volet': VOLET_AUCUN})


def external_sources_view(request):
    """
    Page du registre `sources_externes` — à quoi WAMA se connecte, et est-ce que ça répond.

    Deux couches, deux fraîcheurs, et la page les DISTINGUE au lieu de les fondre :
    - la DÉCLARATION (identité, adresse, portée, attribution) dérive du code à chaque
      affichage — elle ne peut pas être périmée ;
    - la SONDE (clé posée ? joignable ? latence ?) est le dernier rapport ÉCRIT, daté à
      l'écran. La page ne sonde jamais elle-même : quatorze requêtes réseau dans un rendu
      de page seraient le défaut des 31 s des anciens boutons, en pire (réseau externe).
    """
    from .external_sources import SOURCES, LOCAL, api_key, base_url, last_report

    rapport = last_report()
    sondes = {r['key']: r for r in (rapport or {}).get('results', [])}
    lignes = []
    for s in SOURCES:
        lignes.append({
            'key': s.key, 'label': s.label, 'usage': s.usage, 'doc': s.doc,
            'locale': s.scope == LOCAL, 'url': base_url(s.key),
            'setting': s.setting, 'env': s.env,
            'api_key_env': s.api_key_env,
            'cle_posee': bool(api_key(s.key)) if s.api_key_env else None,
            'attribution': s.attribution,
            'sonde': sondes.get(s.key),
        })

    facettes = [{'cle': 'portee', 'label': 'Portée', 'tous': 'Toutes les portées',
                 'options': {'locale': 'Service local', 'sortante': 'Internet (proxy UGE)'}}]

    return render(request, 'common/external_sources.html', {
        'lignes': lignes,
        'rapport_date': (rapport or {}).get('generated_at', ''),
        'compteurs': (rapport or {}).get('counts', {}),
        'nb_locales': sum(1 for l in lignes if l['locale']),
        'nb_a_cle': sum(1 for l in lignes if l['api_key_env']),
        'facettes_sources': facettes,
        'volet': VOLET_AUCUN,
    })


def skills_catalog_view(request):
    """
    Catalogue des SKILLS de prompt — la page qui manquait au registre `skills`.

    Le registre existait depuis le 22/08 avec son compteur et son rafraîchisseur, mais sans
    `url_name` : seul registre de la carte à ne désigner aucune page. Les skills étaient donc
    lisibles par l'assistant et par wama-dev-ai, et par personne d'autre.

    DÉRIVÉE, comme les licences : rien n'est stocké, la synthèse recalcule à chaque affichage
    depuis les fichiers, `PROMPT_TARGETS` et `DOMAINES`. Le bouton d'actualisation reste
    pertinent ici (nature REDECLARATION) — il vide le cache de lecture, pas la page.
    """
    from .services.skills_catalog import FAMILLES, synthese

    # Options DÉCLARÉES : les valeurs brutes sont des clés techniques (`role`, `repli`) et la
    # page affiche des libellés français — même arbitrage que /licences/ et /registres/.
    facettes = [{'cle': 'famille', 'label': 'Famille', 'tous': 'Toutes les familles',
                 'options': dict(FAMILLES)}]

    return render(request, 'common/skills.html',
                  {'cat': synthese(), 'facettes_skills': facettes, 'volet': VOLET_AUCUN})


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


# ── RAG : les SURFACES du geste (jalon 14, WAMA_MEMORY.md §7ter) ─────────────────
# Rappel de la décision qui commande tout ce bloc (objection de Fabien, 2026-08-21) :
# l'entrée au RAG est un GESTE EXPLICITE de l'utilisateur, jamais un balayage. Le premier
# balayage a écrit 939 fragments sans que personne n'ait rien demandé ; il a été purgé.
# Ces vues sont donc les SEULES portes d'écriture, et chacune part d'un clic.
#
# ⚠ PLACEMENT (tranché ici, 2026-08-22) : le geste vit dans l'INSPECTEUR, pas sur les cards
# des apps. L'inspecteur est global depuis le 20/08 et déjà nourri par `detail_registry`, qui
# porte `result_text`/`source_text` — donc AUCUNE ligne par app, et une app future obtient le
# geste le jour où elle enregistre son adapter de détail. C'est la même dérivation que le
# journal ; l'alternative (un bouton dans chaque gabarit de card) aurait été 10 portages à
# maintenir pour le même geste.

def _texte_indexable(detail):
    """Le texte d'un item, tel que le schéma canonique l'expose. `(texte, origine)`.

    On ne fabrique RIEN : `result_text` (sortie produite par WAMA — OCR, transcription,
    description) puis `source_text` (le document était déjà textuel). Un item sans texte n'est
    pas indexable, et c'est ce qui data-gate le bouton : pas de « Ajouter au RAG » sur une vidéo.
    """
    for cle, origine in (('result_text', 'sortie'), ('source_text', 'entrée')):
        v = (detail.get(cle) or '').strip()
        if v:
            return v, origine
    return '', ''


def _item_pour_rag(request, app_name, pk):
    """Résout (detail, erreur_http). Mutualise la garde de propriété d'`unified_detail`."""
    from django.http import JsonResponse
    from django.shortcuts import get_object_or_404

    from .utils.detail_registry import DetailRegistry

    entry = DetailRegistry.get(app_name)
    if not entry:
        return None, JsonResponse({'erreur': f"app inconnue : {app_name}"}, status=404)
    instance = get_object_or_404(entry['model'], pk=pk)
    proprio = getattr(instance, 'user', None)
    # Un item d'un collègue ne s'ajoute pas à MON rag : ce serait recopier son contenu sous mon
    # identité, donc contourner le partage par NIVEAU au lieu de l'utiliser.
    if proprio is not None and proprio != request.user and not request.user.is_staff:
        return None, JsonResponse({'erreur': "cet élément ne vous appartient pas"}, status=403)
    return entry['adapter'](instance), None


@login_required
@require_POST
def rag_ajouter(request):
    """Ajoute au RAG le texte d'un item d'app — LA porte d'écriture des surfaces.

    Générique par construction : `app`/`pk` suffisent, le texte vient du schéma canonique.
    `source_id` = `<app>:<pk>` — stable, donc le geste est IDEMPOTENT (re-cliquer ne duplique
    pas, changer de niveau ne recalcule pas les vecteurs) et la page de gestion sait remonter
    à l'item d'origine.
    """
    from .memory.index import WRITE_LEVELS, add_to_rag

    app_name = (request.POST.get('app') or '').strip()
    try:
        pk = int(request.POST.get('pk') or 0)
    except (TypeError, ValueError):
        pk = 0
    if not app_name or not pk:
        return JsonResponse({'erreur': 'app et pk requis'}, status=400)

    detail, erreur = _item_pour_rag(request, app_name, pk)
    if erreur is not None:
        return erreur

    texte, origine = _texte_indexable(detail)
    if not texte:
        return JsonResponse({'erreur': "cet élément ne porte pas de texte à indexer"}, status=400)

    prof = getattr(request.user, 'profile', None)
    niveau = (request.POST.get('niveau') or '').strip() \
        or (getattr(prof, 'rag_niveau_defaut', '') if prof else '') or 'user'
    if niveau not in WRITE_LEVELS:
        return JsonResponse({'erreur': f"niveau non ouvert : {niveau}"}, status=400)

    # L'unité cible ne se DEVINE pas quand il y en a plusieurs (`_resolve_unit` refuse) : on
    # la prend du geste, sinon du réglage de profil. Sans ce repli, un utilisateur à plusieurs
    # rattachements — cas courant à l'UGE, où les codes hérités coexistent avec les actuels —
    # ne pourrait jamais partager au labo depuis le bouton.
    unite = (request.POST.get('org_unit') or '').strip() \
        or (getattr(prof, 'rag_unite_defaut', '') if prof else '')
    res = add_to_rag(
        request.user, texte,
        # Référence CITABLE : c'est elle que le rappel affiche à côté de l'extrait ([reader:12]).
        source_ref=f'{app_name}:{pk}', source_id=f'{app_name}:{pk}',
        source_kind=app_name, niveau=niveau,
        org_unit=unite or None)
    if res.get('erreur'):
        return JsonResponse({'erreur': res['erreur']}, status=400)
    res['origine'] = origine
    return JsonResponse(res)


@login_required
@require_POST
def rag_retirer(request):
    """Retire un document du RAG. Le pendant du geste d'ajout — condition posée dès l'objection :
    ce qui entre par un geste doit pouvoir sortir par un geste."""
    from .memory.index import remove_from_rag

    source_id = (request.POST.get('source_id') or '').strip()
    if not source_id:
        return JsonResponse({'erreur': 'source_id requis'}, status=400)
    return JsonResponse({'retires': remove_from_rag(request.user, source_id)})


@login_required
@require_POST
def rag_preference(request):
    """Enregistre les défauts de niveaux du profil (écriture + rappel).

    DEUX préférences distinctes, demandées comme telles par Fabien : à quel niveau MES ajouts
    partent par défaut, et quels niveaux sont rappelés par défaut. Le rappel accepte l'ensemble
    VIDE — « ne rien utiliser » est un choix légitime, pas une valeur manquante (d'où le
    marqueur explicite plutôt qu'une liste absente, qu'on ne saurait pas distinguer d'un
    formulaire incomplet)."""
    from .memory.index import WRITE_LEVELS
    from .memory.store import NIVEAUX_RAG

    prof = getattr(request.user, 'profile', None)
    if prof is None:
        return JsonResponse({'erreur': 'profil introuvable'}, status=400)

    champs = []
    niveau = (request.POST.get('niveau_defaut') or '').strip()
    if niveau:
        if niveau not in WRITE_LEVELS:
            return JsonResponse({'erreur': f"niveau non ouvert : {niveau}"}, status=400)
        prof.rag_niveau_defaut = niveau
        champs.append('rag_niveau_defaut')

    if request.POST.get('rappel_soumis'):
        choisis = [n for n in request.POST.getlist('niveaux_rappel') if n in NIVEAUX_RAG]
        prof.rag_niveaux_rappel = choisis
        champs.append('rag_niveaux_rappel')

    if request.POST.get('unite_soumise'):
        # On VALIDE contre les affiliations réelles : accepter un code arbitraire laisserait
        # croire à un partage possible vers une unité dont l'utilisateur n'est pas membre —
        # `add_to_rag` le refuserait ensuite, mais seulement au moment du clic.
        code = (request.POST.get('unite_defaut') or '').strip()
        affiliations = list(prof.org_affiliations or [])
        if prof.org_entity_code:
            affiliations.append(prof.org_entity_code)
        if code and code not in affiliations:
            return JsonResponse({'erreur': f"vous n'êtes pas rattaché à « {code} »"}, status=400)
        prof.rag_unite_defaut = code
        champs.append('rag_unite_defaut')

    if champs:
        prof.save(update_fields=champs)
    return JsonResponse({'niveau_defaut': prof.rag_niveau_defaut,
                         'niveaux_rappel': prof.rag_niveaux_rappel})


@login_required
def rag_view(request):
    """« Mon RAG » — page de gestion : ce que J'AI ajouté, à quel niveau, et le retrait.

    Sœur du journal, et volontairement à côté de lui dans le menu : le journal montre ce que
    l'utilisateur a FAIT, cette page ce qu'il a CONFIÉ à l'IA. Elle est la seule vue où l'on
    voit d'un coup l'étendue de ce partage — c'est ce qui rend le consentement vérifiable, et
    pas seulement demandé une fois au moment du clic.
    """
    from django.urls import reverse

    from .app_registry import APP_CATALOG
    from .memory.index import WRITE_LEVELS, list_rag
    from .memory.store import NIVEAUX_RAG

    LIBELLE = {'user': 'Mon RAG (privé)', 'unit': 'RAG du labo',
               'project': 'RAG du projet', 'public': 'Public'}

    docs = list_rag(request.user)

    niveau_actif = (request.GET.get('niveau') or '').strip()
    q = (request.GET.get('q') or '').strip()
    if niveau_actif and niveau_actif != 'all':
        docs = [d for d in docs if d['niveau'] == niveau_actif]
    if q:
        docs = [d for d in docs if q.lower() in (d['source_ref'] or '').lower()]

    for d in docs:
        # `source_id` = `<app>:<pk>` pour les ajouts venus de l'inspecteur ; `adhoc:…` sinon.
        app_id, _, pk = (d['source_id'] or '').partition(':')
        spec = APP_CATALOG.get(app_id) or {}
        d['app'] = app_id if spec else ''
        d['app_libelle'] = spec.get('name') or app_id
        d['niveau_libelle'] = LIBELLE.get(d['niveau'], d['niveau'])
        # `vectorises < fragments` = un reindex reste dû : on l'AFFICHE au lieu de le taire,
        # sinon un document ajouté semble actif alors qu'aucun rappel sémantique ne le trouve.
        d['en_attente'] = d['vectorises'] < d['fragments']
        d['url_item'] = (reverse(spec['url_name']) if spec.get('url_name') else '')
        d['pk'] = pk

    prof = getattr(request.user, 'profile', None)
    # NULL = jamais choisi ⇒ on présente TOUS les niveaux cochés, ce qui est le comportement
    # réel (rien n'est filtré). Cocher/décocher devient alors un choix explicite, et la liste
    # vide — « ne rien rappeler » — reste atteignable en décochant tout.
    brut = getattr(prof, 'rag_niveaux_rappel', None) if prof else None
    rappel = list(NIVEAUX_RAG) if brut is None else list(brut)
    facettes = [{'cle': 'niveau', 'label': 'Niveau', 'tous': 'Tous les niveaux',
                 'options': {n: LIBELLE[n] for n in WRITE_LEVELS},
                 'valeur': niveau_actif or 'all'}]

    return render(request, 'common/rag.html', {
        'docs': docs,
        'total': len(docs),
        'fragments': sum(d['fragments'] for d in docs),
        'en_attente': sum(1 for d in docs if d['en_attente']),
        'facettes': facettes,
        'q': q,
        'url_reset': reverse('common:rag'),
        'niveaux_ecriture': [(n, LIBELLE[n]) for n in WRITE_LEVELS],
        'niveaux_rappel': [(n, LIBELLE[n], n in rappel) for n in NIVEAUX_RAG],
        'niveau_defaut': getattr(prof, 'rag_niveau_defaut', 'user') if prof else 'user',
        # Un profil sans affiliation RECONNUE ne peut pas publier au labo : on le DIT sur la
        # page plutôt que de laisser le geste échouer au clic avec un message d'erreur. Et on
        # ne liste que les unités RÉSOLUES (une `OrgUnit` existe) : proposer un code que
        # l'annuaire ignore offrirait un choix qui échouerait ensuite.
        'unites': unites_partageables(prof),
        'unite_defaut': getattr(prof, 'rag_unite_defaut', '') if prof else '',
        # « Mon RAG » : liste de documents, tout est dans le corps (WAMA_VOLETS §2).
        'volet': VOLET_AUCUN,
    })


def unites_partageables(profile):
    """Les unités vers lesquelles CE profil peut réellement partager — `[{code, nom}]`.

    Intersection entre ses rattachements d'annuaire et l'arbre `OrgUnit` peuplé par
    `manage.py sync_org_units`. Vide = le niveau labo restera refusé, et la page le dit.
    """
    from .models import OrgUnit

    if profile is None:
        return []
    codes = list(profile.org_affiliations or [])
    if profile.org_entity_code:
        codes.append(profile.org_entity_code)
    unites = OrgUnit.local().filter(code__in=set(codes))
    return [{'code': u.code, 'nom': u.name, 'type': u.get_unit_type_display()} for u in unites]


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
