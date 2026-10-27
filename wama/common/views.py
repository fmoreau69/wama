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
from .utils.volet import volet

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
    from .utils.app_metadata import enrich_prompt_value

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
        target_model = (body.get('target_model') or '').strip()
        field = (body.get('field') or '').strip() or 'prompt'
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not prompt:
        return JsonResponse({'error': 'Prompt vide'}, status=400)
    if len(prompt) > 2000:
        return JsonResponse({'error': 'Prompt trop long (max 2000 caractères)'}, status=400)

    # CONTRAT du modèle visé (2026-10-04) : `enrich_on_demand` savait le recevoir, la vue ne le
    # passait jamais — l'enrichi à la demande ignorait la forme qu'attend le modèle choisi (celle
    # de YuE2 : style + paroles balisées). Un « auto » ne désigne aucun modèle : pas de contrat.
    contract = None
    if target_model and not target_model.startswith('auto'):
        from wama.model_manager.models import AIModel
        contract = (AIModel.objects.filter(model_key=target_model)
                    .values_list('prompt_contract', flat=True).first()) or None

    lang = (getattr(getattr(request.user, 'profile', None), 'preferred_language', None) or 'en')
    try:
        # Par la DÉCLARATION de la cible (2026-10-04) : des paroles balisées restent hors du LLM.
        enhanced = enrich_prompt_value(app, field, prompt, domain=domain, language=lang,
                                       glossary=keywords or None, contract=contract,
                                       user=request.user)
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
    from .utils.volet import VOLET_AUCUN
    return render(request, 'common/modes_demo.html', {'volet': VOLET_AUCUN})   # rien à y montrer


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
    from wama.accounts.permissions import is_admin_tier
    if not is_admin_tier(request.user):
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
    # Depuis le 2026-10-02 le groupage est celui de `get_app_groups` — par MONDE, puis par catégorie
    # dans un monde —, le même que le menu et l'accueil : cette vue le refaisait à la main.
    from .app_registry import get_app_groups
    by_name = {a['name']: a for a in apps_list}
    apps_grouped = []
    for group in get_app_groups():
        cid, meta = group['id'], group['meta']
        items = [by_name[n] for n, _spec in group['apps']]
        links = []
        for link in group['links']:
            try:
                url = reverse(link['url_name'])
            except NoReverseMatch:
                continue  # surface pas encore installée → lien omis, pas d'erreur
            # Les surfaces TRANSVERSALES (studio, médiathèque, model_manager) et Lab se déclarent
            # hors catalogue (`register_surface`) — mais elles sont gardées par le MÊME
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
        for link in groupe['links']:
            if link['abonnable'] and link['autorisee'] and link['gate'] not in autorisees:
                autorisees.append(link['gate'])

    # ── 2ᵉ grille : la FONCTIONNELLE (WAMA_VERIFICATION §2, décidée le 22/08, câblée le
    # 01/09). L'adoption ci-dessus dit « le code contient la brique » ; celle-ci dit « le
    # geste exécuté a produit l'effet » — dernier verdict de CHAQUE scénario nocturne,
    # jamais « le dernier run » (un run est souvent partiel). Les scénarios enregistrés
    # jamais exécutés y figurent : ne montrer que ce qui a tourné surestimerait la couverture.
    grille_droits = []
    try:
        # Le registre se remplit de lui-même à sa première lecture (`nightly_tests.add_registrar`).
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
        # ── Le SUBSTRAT n'est pas une app (2026-09-19, remarque de Fabien). Le stage `suite`
        # a fait entrer 18 labels dans la grille, dont **10 hors du catalogue d'apps** :
        # `wama.common`, `wama_data`, `accounts`, `gateway`, `filemanager`, `model_manager`,
        # `studio`, `media_library` et les deux du Lab. Les afficher dans une table dont la
        # 1ʳᵉ colonne s'intitule « Application » ferait MENTIR la page — une grille par app
        # répond à « cette app est-elle conforme et fonctionne-t-elle ? », pas à « le dépôt
        # est-il sain ? ». Deux questions, deux tables ; même motif que l'extraction des
        # droits juste au-dessus. ⚠ Une page dédiée reste une DÉCISION différée (le critère
        # est écrit dans WAMA_VERIFICATION §2) : 18 lignes ne la remplissent pas encore.
        grille_substrat = {k: v for k, v in grille_fonctionnelle.items()
                           if k not in APP_CATALOG}
        for k in grille_substrat:
            grille_fonctionnelle.pop(k, None)
    except Exception:
        grille_fonctionnelle = {}   # la grille d'adoption reste servie même si celle-ci casse

    return render(request, 'common/apps.html',
                  {'apps_list': apps_list, 'apps_grouped': apps_grouped,
                   'conformity_measured_at': measured_at,
                   'facettes_apps': facettes,
                   'grille_fonctionnelle': grille_fonctionnelle,
                   'grille_substrat': grille_substrat,
                   'grille_droits': grille_droits,
                   'abo': _resume_abo(request.user, 'app', autorisees),
                   'abo_ids': autorisees,
                   # Ce que la page REMPLIT : l'inspecteur de l'app et ses actions, pas de média.
                   'volet': volet(medias=False)})


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
        # Page de SUPERVISION : tout y est dans le corps (cf. WAMA_VOLETS §2 — elle figurait
        # parmi les 17 pages héritant de 3 cadres vides).
        'volet': volet(medias=False, actions=False),
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
    from .services.license_audit import REGISTRES, synthese

    # Facettes de la barre commune. Les options sont DÉCLARÉES bien qu'on soit en mode client :
    # la dérivation depuis le DOM rendrait les valeurs brutes (« model », « library »), alors que
    # la page affichait des libellés français. Déclarer prime sur dériver quand le libellé compte.
    facettes = [{
        'cle': 'registre', 'label': 'Registre', 'tous': 'Tous les registres',
        'options': dict(REGISTRES),
    }]

    return render(request, 'common/licenses.html',
                  {'audit': synthese(request.user if request.user.is_authenticated else None),
                   'facettes_licences': facettes,
                   'volet': volet(medias=False, actions=False)})


def media_formats_view(request):
    """
    Page du registre `media_formats` — tout ce que WAMA sait reconnaître, par nature.

    POURQUOI ELLE EXISTE (demande de Fabien, 2026-09-17). La carte des registres affichait
    « Formats d'entrée » et « Formats de sortie » pour le monde Data et RIEN pour les médias :
    on pouvait en conclure que le monde Médias ne gouverne pas ses formats. C'est faux — le
    vocabulaire est déclaré, à domicile unique et gardé mécaniquement — mais il n'était
    consultable nulle part.

    ⚠ Pas de colonne entrée/sortie : un fichier a la MÊME nature des deux côtés. Ce que le
    converter sait ÉCRIRE est montré comme une facette de la nature, pas comme un second
    vocabulaire.

    La page DÉRIVE du code à chaque affichage (natures + extensions lues à l'appel, donc les
    extensions poussées par un monde au démarrage y sont) : elle ne peut pas être périmée, et
    n'a donc pas de bouton d'actualisation — `refresh_button` le décide seul de la nature.
    """
    from .app_registry import CONVERTER_OUTPUT_FORMATS, MEDIA_CATEGORIES, media_extensions

    par_nature = media_extensions()
    lignes = []
    for nature in MEDIA_CATEGORIES:
        exts = par_nature.get(nature, [])
        lignes.append({
            'nature': nature,
            'extensions': exts,
            'nombre': len(exts),
            'sorties': sorted(CONVERTER_OUTPUT_FORMATS.get(nature, [])),
        })

    return render(request, 'common/media_formats.html', {
        'lignes': lignes,
        'total_extensions': sum(l['nombre'] for l in lignes),
        'nb_natures': len(lignes),
        'nb_sans_sortie': sum(1 for l in lignes if not l['sorties']),
    })


def ui_bricks_view(request):
    """
    Page du registre `ui_bricks` — les BRIQUES dont une page d'édition se compose (2026-10-16,
    demande de Fabien : la carte des registres la nommait, rien ne la montrait).

    Ce qu'elle montre, et d'où elle le lit — le registre `common/surfaces.py`, rien d'autre :
      • chaque brique : ce qu'elle LIT (`consumes`, dans les deux vocabulaires existants — natures
        de média, types de données), ce qu'elle PRODUIT (`emits`), ses mondes, son script et ses
        dépendances ;
      • les SURFACES des apps qui la composent : une brique qu'aucune surface ne monte se voit.
    C'est la liste que la palette du Studio lira — jamais une seconde liste.

    DES BRIQUES SEULES (2026-10-19, décision de Fabien, « trois niveaux » — `ROUTE §F3b`) : une
    brique est un TOUT, un mécanisme une PIÈCE. Chaque brique dit de quels mécanismes elle est
    COMPOSÉE (`UIBrick.mechanisms`, lu de son code) ; les mécanismes eux-mêmes restent sur leur
    carte (`WAMA_MECANISMES.md`). La famille « Système » du 18/10, qui les rangeait à côté des
    briques, est retirée. Une brique de PAGE (card d'entrée, inspecteur, visionneuse) dit le
    gabarit qui la monte, ce qu'elle lit des déclarations de l'app, et les apps qui la montent —
    l'adoption mesurée (`UIBrick.adoption`).

    La page DÉRIVE du code à chaque affichage : elle ne peut pas être périmée, donc aucun bouton
    d'actualisation (`refresh_button` le décide seul de la nature déclarée).
    """
    from .app_registry import MEDIA_CATEGORIES, app_identity
    from .catalog.data_types import known_types
    from .mecanismes import MECHANISMS
    from .surfaces import BRICKS, SURFACES, WORLDS, load_all, thumbnail

    load_all()
    data_types = known_types()

    def vocabulary(value):
        if value in MEDIA_CATEGORIES:
            return 'nature de média'
        return 'type de données' if value in data_types else ''

    # Une app se NOMME par son identité déclarée (`app_identity`), jamais par sa clé.
    used_by = {}
    for surface in SURFACES.values():
        for key in dict.fromkeys(slot.brick for slot in surface.slots):
            used_by.setdefault(key, []).append({'app': surface.app, 'label': surface.label,
                                                'app_label': app_identity(surface.app)['label']})

    # Une brique de PAGE lit une déclaration de l'app qui la monte : une facette de son manifeste
    # (`app.<facette>`) ou le manifeste d'un autre kind (`pipeline`).
    def declared_reading(value):
        kind, _, facet = value.partition('.')
        return {'value': facet or kind,
                'vocabulary': "facette de l'app" if facet else "manifeste de l'app"}

    mechanism_names = {m.key: m.name for m in MECHANISMS}
    bricks = []
    for brick in sorted(BRICKS.values(), key=lambda b: b.name.lower()):
        adoption = brick.adoption()
        bricks.append({
            'key': brick.key, 'name': brick.name, 'description': brick.description,
            'reads': ([declared_reading(v) for v in brick.declarations] if brick.is_page
                      else [{'value': v, 'vocabulary': vocabulary(v)} for v in brick.consumes]),
            'emits': list(brick.emits),
            'usage': 'Édite' if brick.emits else 'Montre',
            'mounted': 'Page' if brick.is_page else 'Surface',
            'page': brick.is_page, 'mount': brick.mount,
            'worlds': list(brick.worlds), 'all_worlds': set(brick.worlds) == set(WORLDS),
            'script': brick.script, 'requires': list(brick.requires),
            'surfaces': used_by.get(brick.key, []),
            # Les apps qui montent une brique de page : l'adoption MESURÉE, rouges écartés.
            'apps': [{'app': app, 'app_label': app_identity(app)['label'],
                      'partial': state == 'partial'}
                     for app, state in adoption['apps'].items() if state],
            'criteria': adoption['criteria'], 'measured_at': adoption['measured_at'],
            'mechanisms': sorted(({'key': key, 'name': mechanism_names[key]}
                                  for key in brick.mechanisms()), key=lambda m: m['name'].lower()),
            'thumbnail': thumbnail(brick.key),
        })

    return render(request, 'common/ui_bricks.html', {
        'bricks': bricks,
        'surfaces_count': len(SURFACES),
        'page_count': sum(1 for b in bricks if b['page']),
        'unused_count': sum(1 for b in bricks if not b['page'] and not b['surfaces']),
        # La clé d'une facette nomme aussi sa ligne dans le volet (`_libelleDeCle`).
        'facets': [{'cle': 'usage', 'label': 'Usage', 'tous': 'Tous les usages',
                    'options': {u: u for u in sorted({b['usage'] for b in bricks})}},
                   {'cle': 'montage', 'label': 'Montée par', 'tous': 'Surfaces et pages',
                    'options': {m: m for m in sorted({b['mounted'] for b in bricks})}}],
        # Détail au clic dans le volet (l'inspecteur de registre) ; rien à prévisualiser.
        'volet': volet(medias=False, actions=False),
    })


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
    from django.urls import reverse

    from wama.accounts.views import is_admin

    from .external_sources import (KINDS, SOURCES, LOCAL, address_origin, api_key_origin,
                                   base_url, last_report)

    rapport = last_report()
    sondes = {r['key']: r for r in (rapport or {}).get('results', [])}
    admin = is_admin(request.user)
    stored = _instance_key_rows()
    lignes = []
    for s in SOURCES:
        origin = api_key_origin(s.key)
        lignes.append({
            'key': s.key, 'label': s.label, 'usage': s.usage, 'doc': s.doc,
            'kind': s.kind, 'kind_label': KINDS.get(s.kind, s.kind),
            'locale': s.scope == LOCAL, 'url': base_url(s.key),
            'setting': s.setting, 'env': s.env,
            # Adresse posée sur cette page par un admin (2026-10-10), pour une source qui le
            # déclare ; l'origine dit laquelle des surcharges vaut ('' = défaut déclaré).
            'address_editable': s.address_editable,
            'address_required': s.address_required,
            'address_origin': address_origin(s.key),
            'api_key_env': s.api_key_env,
            'cle_posee': bool(origin) if s.api_key_env else None,
            # Clé FACULTATIVE (2026-10-12) : absente, la source répond quand même — rien à poser.
            'api_key_optional': s.api_key_optional,
            # Clé posée par CHAQUE utilisateur, au profil (22/09) — jamais « configurée » ici.
            'user_key': s.user_key,
            'api_key_label': s.api_key_label, 'api_key_help_url': s.api_key_help_url,
            'attribution': s.attribution,
            'sonde': sondes.get(s.key),
            # Clé de l'INSTANCE (2026-10-07) : d'où elle vient ('stored' = posée sur cette page,
            # 'env' = `.env`), si elle est partagée, et — pour un admin seulement — qui l'a posée
            # et ce qu'elle ouvre. La clé elle-même ne quitte jamais le serveur.
            'key_origin': origin,
            'shareable': s.shareable,
            'shared': bool(stored.get(s.key) and stored[s.key]['shared']),
            'instance_key': stored.get(s.key) if admin else None,
        })

    # Facette « Type » (2026-09-02, remarque de Fabien : « je ne peux filtrer que par
    # local/externe ») : options DÉRIVÉES des types réellement présents, dans l'ordre de
    # `KINDS` — une option sans carte derrière serait un filtre qui vide la page.
    presents = {l['kind'] for l in lignes}
    facettes = [
        {'cle': 'type', 'label': 'Type', 'tous': 'Tous les types',
         'options': {k: v for k, v in KINDS.items() if k in presents}},
        {'cle': 'portee', 'label': 'Portée', 'tous': 'Toutes les portées',
         'options': {'locale': 'Service local', 'sortante': 'Internet (proxy UGE)'}},
    ]
    # Facette « Clé de l'instance » (2026-10-07) : retrouver d'un coup ce qui attend une clé.
    key_states = {'shared': 'Partagée avec tous les comptes', 'set': 'Posée',
                  'missing': 'À poser'}
    for l in lignes:
        l['key_state'] = ('shared' if l['shared'] else 'set' if l['key_origin']
                          else 'missing' if l['api_key_env'] and not l['api_key_optional']
                          else '')
    present_states = {l['key_state'] for l in lignes}
    facettes.append({'cle': 'cle', 'label': "Clé de l'instance", 'tous': 'Toutes',
                     'options': {k: v for k, v in key_states.items() if k in present_states}})

    return render(request, 'common/external_sources.html', {
        'lignes': lignes,
        'rapport_date': (rapport or {}).get('generated_at', ''),
        'compteurs': (rapport or {}).get('counts', {}),
        'nb_locales': sum(1 for l in lignes if l['locale']),
        'nb_a_cle': sum(1 for l in lignes if l['api_key_env'] or l['user_key']),
        'user_key_count': sum(1 for l in lignes if l['user_key']),
        'profile_url': reverse('accounts:profile'),
        'facettes_sources': facettes,
        'can_manage_keys': admin,
        # Inspecteur au clic sur une carte (volet droit : Paramètres = fiche, Actions =
        # boutons) — même câblage que `/apps/` (`WamaInspector` + `WamaDetails`). Pas de
        # section Médias : une source n'a rien à prévisualiser.
        'volet': volet(medias=False),
    })


def _instance_key_rows() -> dict:
    """{source: état} des clés d'instance POSÉES sur la page — jamais la clé elle-même."""
    from wama.accounts.models import InstanceApiKey
    rows = {}
    for row in InstanceApiKey.objects.exclude(api_key='').select_related('updated_by'):
        rows[row.source] = {
            'shared': row.shared,
            'updated_by': row.updated_by.get_username() if row.updated_by else '',
            'updated_at': row.updated_at.strftime('%d/%m/%Y %H:%M') if row.updated_at else '',
            'models_count': len(row.open_models or []),
            'discovery_error': row.discovery_error,
        }
    return rows


@login_required
@require_POST
def external_source_instance_key(request, key):
    """POST — la clé d'INSTANCE d'une source, posée par un admin (2026-10-07, décision de Fabien :
    « c'est la page Sources externes qui doit gérer les clés système »).

    `{api_key: "…"}` enregistre (chiffrée) ; `{api_key: ""}` retire ; `{shared: bool}` seul
    partage ou non la clé posée avec tous les comptes — refusé si la source ne se déclare pas
    `shareable`. Le geste d'enregistrement est CELUI du profil (`api_keys.store_key`).
    """
    import json

    from django.http import Http404

    from wama.accounts.api_keys import forget_opened_models, store_key
    from wama.accounts.models import InstanceApiKey
    from wama.accounts.views import is_admin

    from .external_sources import by_key

    if not is_admin(request.user):
        return JsonResponse({'error': 'Réservé aux administrateurs'}, status=403)
    source = by_key().get(key)
    if source is None or not source.api_key_env:
        raise Http404('Source sans clé d\'instance')
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    row = InstanceApiKey.objects.filter(source=key).first()
    if 'api_key' not in data:
        if 'shared' not in data:
            return JsonResponse({'error': 'Rien à enregistrer'}, status=400)
        if not source.shareable:
            return JsonResponse({'error': f"{source.label} ne délivre pas de clé partageable : "
                                          "chacun pose la sienne au profil."}, status=400)
        if row is None or not row.api_key:
            return JsonResponse({'error': "Posez d'abord la clé de l'instance."}, status=400)
        row.shared, row.updated_by = bool(data['shared']), request.user
        row.save(update_fields=['shared', 'updated_by', 'updated_at'])
        return JsonResponse({'success': True, 'shared': row.shared})

    api_key = (data.get('api_key') or '').strip()
    if not api_key:
        if row is not None:
            # La même ligne peut porter l'ADRESSE posée sur la page (2026-10-10) : on ne la
            # retire pas avec la clé — mais tout ce que la clé avait OUVERT part avec elle
            # (`cloud_models` lit `open_models` sur toutes les lignes d'une source).
            if row.base_url:
                row.api_key, row.shared, row.updated_by = '', False, request.user
                row.open_models, row.remote_listing = [], []
                row.discovered_at, row.discovery_error = None, ''
                row.save()
            else:
                row.delete()
            forget_opened_models(key)
        return JsonResponse({'success': True, 'has_key': False})
    row = row or InstanceApiKey(source=key)
    row.updated_by = request.user
    result = store_key(row, api_key)
    return JsonResponse(result, status=result.pop('status'))


@login_required
@require_POST
def external_source_instance_address(request, key):
    """POST `{base_url: "…"}` — l'ADRESSE d'une source, posée par un admin (2026-10-10, demande de
    Fabien : « les champs à compléter directement dans l'interface du registre des sources »).

    Seulement pour une source déclarée `address_editable`. Vide = retirée : le réglage, le `.env`
    puis le défaut déclaré reprennent la main. Même ligne d'instance que la clé.
    """
    import json

    from django.http import Http404

    from wama.accounts.models import InstanceApiKey
    from wama.accounts.views import is_admin

    from .external_sources import address_origin, base_url, by_key, valid_address

    if not is_admin(request.user):
        return JsonResponse({'error': 'Réservé aux administrateurs'}, status=403)
    source = by_key().get(key)
    if source is None or not source.address_editable:
        raise Http404("Source dont l'adresse ne se pose pas ici")
    try:
        raw = (json.loads(request.body).get('base_url') or '').strip()
    except (json.JSONDecodeError, ValueError, AttributeError):
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    address = valid_address(raw)
    if raw and not address:
        return JsonResponse({'error': "Adresse invalide : attendue sous la forme "
                                      "https://serveur.exemple.fr"}, status=400)
    row = InstanceApiKey.objects.filter(source=key).first()
    if not address:
        if row is not None:
            if row.api_key:
                row.base_url, row.updated_by = '', request.user
                row.save(update_fields=['base_url', 'updated_by', 'updated_at'])
            else:
                row.delete()
    else:
        row = row or InstanceApiKey(source=key)
        row.base_url, row.updated_by = address, request.user
        row.save()
    return JsonResponse({'success': True, 'url': base_url(key), 'address_origin': address_origin(key)})


def backends_catalog_view(request):
    """
    Page du registre `backends` (12ᵉ) — le VIVIER des moteurs, DÉRIVÉ (demande Fabien 03/09).

    Deux besoins, une seule source : la vision d'ensemble depuis WAMA, et le VOISINAGE dont
    le LLM de la marche B a besoin pour « s'inspirer du plus approchant » (nature routée →
    saveur de sortie, paquets, VRAM, modèles servis). Rien n'est stocké : la page lit les
    déclarations `wama/<app>/backends/` et le catalogue `AIModel` à chaque affichage — même
    argument que les licences, *une page qui DÉRIVE ne peut pas diverger de ses sources*.

    Les facettes sont DÉRIVÉES du contenu réel (une option sans carte derrière serait un
    filtre qui vide la page — leçon des sources externes), sauf leurs libellés.
    """
    from .services.backend_inventory import FLAVORS, summary

    inv = summary()
    apps_presentes = {e.app for a in inv['apps'] for e in a.entries}
    familles = {e.kind for a in inv['apps'] for e in a.entries}
    saveurs = {e.flavor for a in inv['apps'] for e in a.entries}
    # ENVIRONNEMENTS présents (`ISOLATION`) — la facette n'apparaît QUE s'il y a autre chose
    # que le venv principal : proposer « Tous les environnements » sur un parc à un seul
    # environnement serait un filtre décoratif (même règle que les autres facettes).
    environnements = {e.isolation or 'venv principal'
                      for a in inv['apps'] for e in a.entries}

    facettes = [
        {'cle': 'app', 'label': 'Application', 'tous': 'Toutes les apps',
         'options': {a: a for a in sorted(apps_presentes)}},
        {'cle': 'saveur', 'label': 'Sortie', 'tous': 'Toutes les sorties',
         'options': {k: v for k, v in FLAVORS.items() if k in saveurs}},
        {'cle': 'famille', 'label': 'Famille', 'tous': 'Toutes les familles',
         'options': {k: v for k, v in (('route', 'Routé (ROUTES)'),
                                       ('classe', 'Classe (BaseModelBackend)'))
                     if k in familles}},
    ]
    if len(environnements) > 1:
        facettes.append({'cle': 'environnement', 'label': 'Environnement',
                         'tous': 'Tous les environnements',
                         'options': {e: e for e in sorted(environnements)}})

    return render(request, 'common/backends.html', {
        'inv': inv,
        'facettes_backends': facettes,
        # Inspecteur au clic, la fiche dérivée de la tuile (`_inspector_registre.html`) ; pas de
        # section Médias (un backend n'a rien à prévisualiser) ni Actions (la page n'en porte
        # aucune : la section restait sur son texte par défaut — relevé le 2026-10-20 par le
        # garde des pages du compte, `tests_volet.AccountPagesHaveNoDefaultTest`).
        'volet': volet(medias=False, actions=False),
    })


@login_required
def docs_catalog_view(request):
    """
    Page du registre `docs` (15ᵉ, 2026-09-11) — la doc de WAMA en lecture seule, depuis WAMA.

    DÉRIVÉE : la liste vient de `docs_catalog.py` (la déclaration que `check_docs` lit aussi),
    chaque fiche est relue sur le disque. QUI LIT QUOI (`docs_catalog.visible_to`) : la doc
    UTILISATEUR, tout compte connecté (Fabien, 2026-09-14) ; le reste, les administrateurs
    (11/09). Un compte ne voit que les fiches qu'il peut ouvrir — pas de carte vers un refus.
    """
    from wama.accounts.views import is_admin

    from .docs_catalog import AUDIENCES, DOCS, FAMILIES, entry, visible_to

    admin = is_admin(request.user)
    docs = [entry(d) for d in DOCS if visible_to(d, admin)]
    familles = {d['family'] for d in docs}
    audiences = {d['audience'] for d in docs}
    facettes = [{'cle': 'famille', 'label': 'Famille', 'tous': 'Toutes les familles',
                 'options': {k: v for k, v in FAMILIES.items() if k in familles}}]
    # La facette « Audience » n'apparaît qu'à partir de DEUX audiences présentes : aujourd'hui
    # tout est de construction, et un filtre à une seule option serait décoratif.
    if len(audiences) > 1:
        facettes.append({'cle': 'audience', 'label': 'Audience', 'tous': 'Toutes les audiences',
                         'options': {k: v for k, v in AUDIENCES.items() if k in audiences}})

    return render(request, 'common/docs.html', {
        'docs': docs,
        'nb_familles': len(familles),
        'nb_lignes': sum(d['lines'] or 0 for d in docs),
        'nb_generees': sum(1 for d in docs if d['generated']),
        'nb_absents': sum(1 for d in docs if not d['exists']),
        'facettes_docs': facettes,
        'volet': volet(medias=False, actions=False),
    })


@login_required
def doc_read_view(request, key):
    """Lecteur d'UN doc déclaré. La clé est cherchée dans le catalogue : ce qui n'y est pas
    n'existe pas pour cette vue (404), quel que soit le contenu du disque. Une doc que ce compte
    ne peut pas lire rend AUSSI 404 : un refus confirmerait qu'elle existe."""
    from django.http import Http404

    from wama.accounts.views import is_admin

    from .docs_catalog import entry, get, render_doc, visible_to

    admin = is_admin(request.user)
    doc = get(key)
    if doc is None or not visible_to(doc, admin):
        raise Http404("document non déclaré")
    try:
        rendu = render_doc(doc, admin=admin)
    except FileNotFoundError:
        raise Http404("document déclaré mais absent du disque")
    return render(request, 'common/doc_read.html', {
        'doc': entry(doc), 'rendu': rendu,
        # Le volet droit porte le SOMMAIRE (bloc `right_panel_settings`) — rien d'autre.
        'volet': volet(medias=False, actions=False),
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

    # Les skills d'un COMPTE (`common.PromptSkill`, `ROADMAP §29`, 2026-10-20) : les siens, ceux
    # qu'on lui partage, les systèmes promus — et les gestes, par `skills_manage`.
    from django.urls import reverse

    from .services.sharing import scope_choices
    from .services.user_skills import as_dict, visible_skills
    account = {}
    if request.user.is_authenticated:
        account = {'skills_api': reverse('common:skills_manage'),
                   'promotion_api': reverse('common:api_promotion_request'),
                   'skills_account': [as_dict(r, request.user)
                                      for r in visible_skills(request.user)],
                   'skills_scopes': scope_choices(request.user)}
    return render(request, 'common/skills.html',
                  {'cat': synthese(), 'facettes_skills': facettes,
                   'volet': volet(medias=False, actions=False), **account})


@login_required
@require_POST
def skills_manage(request):
    """AJAX — les gestes sur les skills d'un compte (`services/user_skills`) : `create` (nom,
    consigne), `update` (sa consigne), `share` (une portée, `scope` = `private`, `public`,
    `unit:<id>` ou `project:<id>`), `copy` (un skill qu'il voit, `pk` ; ou un skill système,
    `name`), `delete` (son auteur ou un admin), `promote` (un ADMIN seul : le skill devient
    système). « Demander la promotion » passe par la route commune (`api_promotion_request`).
    Rend la ligne telle que la page la montre."""
    import json

    from .services import user_skills as us
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    action, user = data.get('action'), request.user
    try:
        if action == 'create':
            row = us.create(user, data.get('name'), data.get('text'))
        elif action == 'update':
            row = us.update(user, data.get('pk'), data.get('text'))
        elif action == 'share':
            us.share(user, data.get('pk'), str(data.get('scope') or 'private'))
            row = us.visible_skills(user).get(pk=data.get('pk'))
        elif action == 'copy':
            row = us.copy(user, pk=data.get('pk'), name=data.get('name') or '')
        elif action == 'delete':
            us.delete(user, data.get('pk'))
            return JsonResponse({'success': True})
        elif action == 'promote':
            row = us.promote(user, data.get('pk'))
        else:
            return JsonResponse({'error': f'Action inconnue : {action!r}'}, status=400)
    except us.SkillRefused as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)
    return JsonResponse({'success': True, 'skill': us.as_dict(row, user)})


def pronunciations_catalog_view(request):
    """
    Catalogue des PRONONCIATIONS — comment la voix dit un terme (registre `pronunciations`,
    2026-10-27). DÉRIVÉE, comme les skills : le fichier du dépôt (système) et les lignes
    `common.Pronunciation` vues par le compte, relus à chaque affichage. Gestes :
    `pronunciations_manage` ; écoute : la voix de l'assistant (`kokoro_tts`, `pronunciation=`).
    """
    from django.urls import reverse

    from .services import user_pronunciations as up
    from .services.sharing import scope_choices
    from .tts.voices import voix_pour

    language_names = dict(up.languages())
    system = up.system_entries()
    for entry in system:
        entry['listen'] = up.listen_text(entry['term'], entry['language'])
        entry['language_label'] = language_names.get(entry['language'], entry['language'])
    facettes = [{'cle': 'langue', 'label': 'Langue', 'tous': 'Toutes les langues',
                 'options': {e['language']: e['language_label'] for e in system}},
                {'cle': 'forme', 'label': 'Forme', 'tous': 'Toutes les formes',
                 'options': {'spelling': 'Orthographe à dire', 'phonemes': 'Phonèmes'}}]
    context = {'system_entries': system, 'facettes_pronunciations': facettes,
               'volet': volet(medias=False, actions=False),
               'voices': {code: voix_pour(code) for code in language_names},
               'tts_api': reverse('kokoro_tts')}
    if request.user.is_authenticated:
        rows = []
        for row in up.visible_pronunciations(request.user):
            item = up.as_dict(row, request.user)
            item['listen'] = up.listen_text(row.term, row.language)
            item['language_label'] = language_names.get(row.language, row.language)
            rows.append(item)
        context.update({'pronunciations_api': reverse('common:pronunciations_manage'),
                        'promotion_api': reverse('common:api_promotion_request'),
                        'pronunciations_account': rows,
                        'pronunciation_scopes': scope_choices(request.user),
                        'languages': up.languages()})
    return render(request, 'common/pronunciations.html', context)


@login_required
@require_POST
def pronunciations_manage(request):
    """AJAX — les gestes sur les prononciations d'un compte (`services/user_pronunciations`) :
    `create` (terme, langue, orthographe et/ou phonèmes), `update`, `share` (`scope`), `copy` (une
    ligne vue, `pk` ; ou une entrée du fichier, `term` + `language`), `delete`, `promote` (un ADMIN
    seul). « Demander la promotion » passe par la route commune (`api_promotion_request`)."""
    import json

    from .services import user_pronunciations as up
    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    action, user = data.get('action'), request.user
    try:
        if action == 'create':
            row = up.create(user, data.get('term'), data.get('language') or 'fr',
                            data.get('spelling'), data.get('phonemes'))
        elif action == 'update':
            row = up.update(user, data.get('pk'), data.get('spelling'), data.get('phonemes'))
        elif action == 'share':
            up.share(user, data.get('pk'), str(data.get('scope') or 'private'))
            row = up.visible_pronunciations(user).get(pk=data.get('pk'))
        elif action == 'copy':
            row = up.copy(user, pk=data.get('pk'), term=data.get('term') or '',
                          language=data.get('language') or 'fr')
        elif action == 'delete':
            up.delete(user, data.get('pk'))
            return JsonResponse({'success': True})
        elif action == 'promote':
            row = up.promote(user, data.get('pk'))
        else:
            return JsonResponse({'error': f'Action inconnue : {action!r}'}, status=400)
    except up.PronunciationRefused as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)
    return JsonResponse({'success': True, 'pronunciation': up.as_dict(row, user)})


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
        # La card cliquée au volet (aperçu + fiche) ; son action vit sur la card (→) : ni
        # Paramètres ni Actions, qui restaient des cadres vides (2026-10-18).
        'volet': volet(parametres=False, actions=False),
    })


def _calendar_range(request, default_days_back=31, default_days_ahead=31, max_days=400):
    """Fenêtre `[start, end)` lue de la requête (FullCalendar envoie `start`/`end` en ISO 8601) —
    la décision est celle du service (`calendar.calendar_window`), que l'assistant lit aussi."""
    from .services.calendar import calendar_window
    return calendar_window(request.GET.get('start'), request.GET.get('end'),
                           days_back=default_days_back, days_ahead=default_days_ahead,
                           max_days=max_days)


@login_required
def calendar_view(request):
    """Calendrier de l'utilisateur — `WAMA_MEMORY.md §9bis.1`.

    La MÊME activité que le journal, sur l'axe du temps : la page ne porte aucune donnée, elle
    charge ses événements par `calendar_events` à chaque changement de fenêtre.
    """
    from .app_registry import app_identity
    from .services.calendar import MAINTENANCE_COLOR, nature_labels
    from .services.journal import STATUTS, compter_par_app

    legend = [{'app': row['app'], 'label': row['label'], 'color': app_identity(row['app'])['color']}
              for row in compter_par_app(request.user)]
    # Barre de filtrage COMMUNE (`common/_filter_bar.html`) en cible VIVANTE : le calendrier
    # redessine ses événements à chaque vue, les facettes sont donc DÉCLARÉES — les mêmes
    # valeurs que les `data-f-*` posés par `wama-calendar.js`. Les états sont ceux du journal.
    facettes = [
        {'cle': 'app', 'label': 'Application', 'tous': 'Toutes les applications',
         'options': {row['app']: row['label'] for row in legend}},
        {'cle': 'nature', 'label': 'Nature', 'tous': 'Tout', 'options': nature_labels()},
        {'cle': 'statut', 'label': 'État', 'tous': STATUTS['all'],
         'options': {k: v for k, v in STATUTS.items() if k != 'all'}},
    ]
    return render(request, 'common/calendar.html', {
        'legend': legend,
        'facettes': facettes,
        'maintenance_color': MAINTENANCE_COLOR,
        # La card de l'élément cliqué (aperçu + fiche) et l'action « ouvrir dans l'app », comme
        # le journal ; aucun réglage ne s'édite ici (2026-10-18).
        'volet': volet(parametres=False),
    })


@login_required
@require_GET
def calendar_events(request):
    """Événements de `[start, end)` au format FullCalendar. `maintenance=0` masque la couche de
    l'instance (tâches planifiées de WAMA, dont les fenêtres réservées aux tests nocturnes)."""
    from .services.calendar import events_for

    start, end = _calendar_range(request)
    with_maintenance = request.GET.get('maintenance', '1') != '0'
    events = events_for(request.user, start, end, with_maintenance=with_maintenance)
    return JsonResponse([e.as_fullcalendar() for e in events], safe=False)


@login_required
@require_GET
def calendar_ics(request):
    """Export iCalendar de SON calendrier (90 jours passés, 30 à venir par défaut).

    Authentifié par la SESSION : c'est un téléchargement, pas un abonnement. Un flux auquel un
    client (Outlook, Thunderbird) s'abonne ne porte pas de cookie — il lui faut un jeton propre à
    l'utilisateur et RÉVOCABLE, donc une table : il arrive avec l'étape 3 (§9bis.1).
    """
    from django.http import HttpResponse

    from .services.calendar import events_for, to_ics

    start, end = _calendar_range(request, default_days_back=90, default_days_ahead=30)
    events = events_for(request.user, start, end,
                        with_maintenance=request.GET.get('maintenance', '1') != '0')
    response = HttpResponse(to_ics(events, host=request.get_host() or 'wama'),
                            content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="wama-calendrier.ics"'
    return response


def _json_body(request):
    import json
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


def _action_json(action):
    """Une programmation, avec ses valeurs NOMMÉES PAR LE SCHÉMA (`when`, `at`) : la fenêtre
    « Modifier » les rend telles quelles par `WamaParams.render`."""
    from django.utils import timezone

    from .services.scheduled_actions import FIELD_AT, FIELD_WHEN
    return {'id': action.pk, 'tool': action.tool, 'app': action.app,
            'objectId': action.object_id, 'title': action.title,
            'runAt': action.run_at.isoformat(),
            'values': {FIELD_WHEN: action.placement,
                       FIELD_AT: timezone.localtime(action.run_at).strftime('%Y-%m-%dT%H:%M')}}


def _conflict_json(window):
    return {'title': window.title, 'start': window.start.isoformat(),
            'end': window.end.isoformat(), 'suggested': window.end.isoformat()}


@login_required
@require_POST
def schedule_create(request):
    """Programme le lancement d'une ou plusieurs cards (menu « Programmer… », ROUTE §10.6 13).

    Corps JSON : `{tool, ids, when, at?}` — les noms du SCHÉMA (`schedule_params`), ceux d'une
    ligne de fichier batch. Un placement manuel qui tombe dans une plage réservée ne crée rien :
    la réponse porte `conflict` (la plage, et sa fin proposée)."""
    from .services.scheduled_actions import ScheduleError, read_schedule, schedule_items

    data = _json_body(request)
    try:
        placement, requested = read_schedule(data)
        result = schedule_items(request.user, data.get('tool', ''), data.get('ids') or [],
                                placement, requested)
    except ScheduleError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    if result['conflict'] is not None:
        return JsonResponse({'ok': False, 'conflict': _conflict_json(result['conflict'])})
    return JsonResponse({'ok': True, 'actions': [_action_json(a) for a in result['actions']]})


@login_required
@require_POST
def schedule_update(request, pk):
    from .services.scheduled_actions import ScheduleError, read_schedule, reschedule

    data = _json_body(request)
    try:
        placement, requested = read_schedule(data)
        result = reschedule(request.user, pk, placement, requested)
    except ScheduleError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    if result['conflict'] is not None:
        return JsonResponse({'ok': False, 'conflict': _conflict_json(result['conflict'])})
    return JsonResponse({'ok': True, 'actions': [_action_json(result['action'])]})


@login_required
@require_POST
def schedule_cancel(request, pk):
    from .services.scheduled_actions import cancel
    return JsonResponse({'ok': cancel(request.user, pk)})


@login_required
@require_GET
def schedule_active(request):
    """Programmations actives de l'utilisateur (les pastilles des cards se posent d'après elles)
    et le SCHÉMA de la fenêtre « Programmer… » — une seule requête au chargement de la file."""
    from .services.global_queue import for_user, snapshot
    from .services.scheduled_actions import active_for, schedule_params
    from .utils.param_schema import schema_to_dicts

    # « Où en est ma tâche ? » (étape 4) : la place de SES éléments dans la file GPU globale,
    # le nombre de tâches devant eux et les heures prévues — la même lecture que le calendrier.
    entries = snapshot()
    return JsonResponse({'actions': [_action_json(a) for a in active_for(request.user)],
                         'schema': schema_to_dicts(schedule_params()),
                         'queue': for_user(request.user, entries=entries),
                         'queueLength': len(entries)})


@login_required
@require_POST
def calendar_feed(request):
    """Crée — ou RÉGÉNÈRE (`regenerate=1`) — le jeton d'abonnement `.ics`. Régénérer tue l'ancien
    lien aussitôt : c'est la révocation."""
    import secrets

    from django.urls import reverse

    from .models import CalendarFeed

    feed = CalendarFeed.objects.filter(user=request.user).first()
    if feed is None or request.POST.get('regenerate') == '1':
        token = secrets.token_urlsafe(32)
        feed, _ = CalendarFeed.objects.update_or_create(user=request.user,
                                                        defaults={'token': token})
    url = request.build_absolute_uri(reverse('common:calendar_feed_ics', args=[feed.token]))
    return JsonResponse({'ok': True, 'url': url})


@require_GET
def calendar_feed_ics(request, token):
    """Le calendrier d'un utilisateur pour un client qui s'ABONNE : authentifié par le jeton, pas
    par la session. 90 jours passés, 60 à venir."""
    from datetime import timedelta

    from django.http import Http404, HttpResponse
    from django.utils import timezone

    from .models import CalendarFeed
    from .services.calendar import events_for, to_ics

    feed = CalendarFeed.objects.select_related('user').filter(token=token).first()
    if feed is None or not feed.user.is_active:
        raise Http404
    now = timezone.now()
    events = events_for(feed.user, now - timedelta(days=90), now + timedelta(days=60))
    return HttpResponse(to_ics(events, host=request.get_host() or 'wama'),
                        content_type='text/calendar; charset=utf-8')


@login_required
def notifications_view(request):
    """Les notifications DANS WAMA du compte connecté — `WAMA_COLLABORATION.md §2.3` et §5.3 :
    la liste, lu / non lu, ouverte depuis le badge de l'en-tête. Premier type d'événement posé
    le 2026-09-24 : l'arrêt d'un worker Celery et les traitements qu'il a interrompus."""
    from .models import Notification
    items = list(Notification.objects.filter(recipient=request.user)[:200])
    return render(request, 'common/notifications.html', {
        'items': items,
        'unread_count': sum(1 for n in items if n.read_at is None),
    })


@login_required
@require_POST
def notifications_mark_read(request):
    """Marque comme lues les notifications du compte (toutes, ou `id` si fourni), puis revient
    à la page — formulaire simple, aucune brique JS propre à cette page."""
    from django.shortcuts import redirect
    from django.utils import timezone

    from .models import Notification
    qs = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
    ident = (request.POST.get('id') or '').strip()
    if ident.isdigit():
        qs = qs.filter(pk=int(ident))
    qs.update(read_at=timezone.now())
    return redirect('common:notifications')


@login_required
def notification_open(request, pk: int):
    """« Ouvrir » une notification (2026-10-07, remarque de Fabien : *« quand je clique sur
    Ouvrir, une notification devrait être marquée comme lue »*) — la marque lue, puis mène à son
    lien. Un lien qui sortirait de WAMA n'est pas suivi : retour à la page des notifications."""
    from django.shortcuts import get_object_or_404, redirect
    from django.utils import timezone
    from django.utils.http import url_has_allowed_host_and_scheme

    from .models import Notification
    note = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if note.read_at is None:
        note.read_at = timezone.now()
        note.save(update_fields=['read_at'])
    if note.url and url_has_allowed_host_and_scheme(note.url, allowed_hosts={request.get_host()},
                                                     require_https=request.is_secure()):
        return redirect(note.url)
    return redirect('common:notifications')


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

@login_required
@require_POST
def rag_ajouter(request):
    """Ajoute au RAG — LA porte d'écriture des surfaces, pour deux désignations :

      • un ÉLÉMENT d'app (`app` + `pk`) — inspecteur, menu « … » des cards ;
      • un FICHIER (`path`, chemin du gestionnaire de fichiers) — menu de l'arbre, 2026-10-14.

    Les gestes vivent dans la brique (`memory.index.add_item_to_rag` / `add_file_to_rag`), que
    l'outil de l'assistant appelle aussi : cette vue ne fait que lire la requête et rendre le
    code HTTP du refus. `niveau` / `org_unit` sont optionnels — défauts du profil sinon.
    """
    from .memory.index import add_file_to_rag, add_item_to_rag

    level = request.POST.get('niveau') or ''
    unit = request.POST.get('org_unit') or ''
    path = (request.POST.get('path') or '').strip()
    if path:
        res = add_file_to_rag(request.user, path, level=level, org_unit=unit)
    else:
        app_name = (request.POST.get('app') or '').strip()
        try:
            pk = int(request.POST.get('pk') or 0)
        except (TypeError, ValueError):
            pk = 0
        if not app_name or not pk:
            return JsonResponse({'erreur': 'app et pk requis (ou path)'}, status=400)
        res = add_item_to_rag(request.user, app_name, pk, level=level, org_unit=unit)
    status = res.pop('status', 200)
    return JsonResponse(res, status=status)


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
def rag_reindex(request):
    """« Vectoriser maintenant » (2026-10-16, décision de Fabien) : les vecteurs qui manquent aux
    documents et souvenirs du COMPTE, calculés par la tâche commune (`common.reindex_memory`, file
    GPU, derrière tout traitement) — jamais dans la requête (`WAMA_MEMORY §5bis`). Revient à la
    page avec ce qui a été fait : formulaire simple, comme le marquage des notifications."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from .tasks import reindex_memory_task

    reindex_memory_task.delay(user_id=request.user.pk)
    messages.info(request, "Vectorisation demandée : elle passe dès que la carte graphique est "
                           "libre. Rechargez la page dans quelques instants.")
    return redirect('common:rag')


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

    from .app_registry import app_identity
    from .memory.index import WRITE_LEVELS, list_rag
    from .memory.store import NIVEAUX_RAG
    from .services.calendar import next_occurrence
    from .services.journal import app_queue_url

    LIBELLE = {'user': 'Mon RAG (privé)', 'unit': 'RAG du labo',
               'project': 'RAG du projet', 'public': 'Public'}

    niveau_actif = (request.GET.get('niveau') or '').strip()
    q = (request.GET.get('q') or '').strip()
    docs = list_rag(request.user, level=niveau_actif, query=q)

    for d in docs:
        # `source_id` = `<app>:<pk>` pour un élément d'app ; `file:…` pour un fichier (son chemin
        # est le `source_ref`, affiché tel quel) ; `adhoc:…` sinon.
        app_id, _, pk = (d['source_id'] or '').partition(':')
        # Le nom et la page de l'app : son identité commune. La page lisait une clé `name` qu'aucune
        # entrée du catalogue ne porte — elle affichait la CLÉ de toutes les apps (2026-10-16).
        identity = app_identity(app_id)
        d['app'] = app_id if identity['declared'] else ''
        d['app_libelle'] = identity['label']
        d['niveau_libelle'] = LIBELLE.get(d['niveau'], d['niveau'])
        # `vectorises < fragments` = un reindex reste dû : on l'AFFICHE au lieu de le taire,
        # sinon un document ajouté semble actif alors qu'aucun rappel sémantique ne le trouve.
        d['en_attente'] = d['vectorises'] < d['fragments']
        d['url_item'] = app_queue_url(app_id) if identity['declared'] else ''
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
        # Quand passe le lot de vectorisation : lu du planificateur, jamais écrit au gabarit
        # (la page promettait « le prochain lot » alors qu'aucun n'était planifié).
        'next_reindex': next_occurrence('memory-reindex-nightly'),
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
        'volet': volet(medias=False, actions=False),
    })


@login_required
def memories_view(request):
    """« Mes souvenirs » — la page JUMELLE de « Mon RAG » (13ᵉ registre, 2026-09-09).

    Le fragment (`RagChunk`) avait sa page ; le souvenir (`MemoryItem`) n'en avait aucune, alors
    qu'ils héritent des mêmes mixins et partagent un seul `recall()`. Son seul accès était
    `memory_recall` — l'assistant, en langage naturel : impossible de LISTER ce que WAMA retient.

    Deux listes, deux questions distinctes (cf. `store.list_memories`) :
      • ACTIFS — exactement ce que `recall()` rendrait, par réutilisation de `_visible_memory` ;
      • FILE DE REVUE — les non approuvés, que la gouvernance cache au rappel (`WAMA_MEMORY §6`).
        Réservée au STAFF, parce qu'elle n'est délibérément pas scopée.

    ⚠ La page ne CRÉE rien et n'approuve rien pour l'instant : elle rend visible une file qui
    l'était pour personne. Le geste d'approbation est la marche suivante — l'ouvrir ici sans
    l'avoir tracé ferait exactement le « chemin parallèle » qu'on cherche à éviter.
    """
    from django.urls import reverse

    from .memory.store import list_memories

    actifs = list_memories(request.user)
    from wama.accounts.permissions import is_admin_tier
    reviewer = is_admin_tier(request.user)     # LA définition d'administrateur (2026-10-21)
    attente = list_memories(request.user, en_attente=True) if reviewer else []

    q = (request.GET.get('q') or '').strip()
    if q:
        motif = q.lower()
        actifs = [s for s in actifs if motif in (s['content'] or '').lower()
                  or motif in (s['subject'] or '').lower()]
        attente = [s for s in attente if motif in (s['content'] or '').lower()
                   or motif in (s['subject'] or '').lower()]

    kind_actif = (request.GET.get('kind') or '').strip()
    if kind_actif and kind_actif != 'all':
        actifs = [s for s in actifs if s['kind'] == kind_actif]
        attente = [s for s in attente if s['kind'] == kind_actif]

    from .models import MemoryItem
    kinds = {MemoryItem.KIND_SEMANTIC: 'Fait', MemoryItem.KIND_EPISODIC: 'Événement',
             MemoryItem.KIND_PROCEDURAL: 'Procédure'}
    facettes = [{'cle': 'kind', 'label': 'Nature', 'tous': 'Toutes natures',
                 'options': kinds, 'valeur': kind_actif or 'all'}]

    # Libellé résolu ICI : aucun filtre de gabarit n'est enregistré dans ce dépôt (vérifié —
    # `templatetags/` ne déclare que des tags), donc un `dict|lookup:clé` en gabarit n'existe
    # pas. Le résoudre côté vue est la voie du dépôt, pas un contournement.
    #
    # ⚠ PROPRIÉTAIRE ET PORTÉE dans la liste ACTIVE (ajoutés le 2026-09-09, relevé de Fabien).
    # La page s'appelle « Mes souvenirs » mais `_visible_memory` rend AUSSI ce qui est partagé
    # à mon unité ou publié par d'autres : taire à qui appartient une ligne laissait croire que
    # tout venait de moi. Et un souvenir de PLATEFORME n'a aucun propriétaire (`user=NULL`) —
    # c'est un état légitime, qui doit se lire comme tel et non comme une donnée manquante.
    portees = {'private': 'Privé', 'unit': 'Unité', 'project': 'Projet', 'public': 'Public'}
    for s in actifs + attente:
        s['kind_libelle'] = kinds.get(s['kind'], s['kind'])
        s['portee_libelle'] = portees.get(s['niveau'], s['niveau'])
        s['est_mien'] = bool(s['proprietaire']) and s['proprietaire'] == request.user.username
        s['proprietaire_libelle'] = (
            'moi' if s['est_mien']
            else (s['proprietaire'] or 'la plateforme (aucun propriétaire)'))

    # Unités proposables comme PORTÉE à la validation. Toutes, pas celles du relecteur : il
    # arbitre pour des souvenirs de PLATEFORME (`user=NULL`), qui ne dépendent d'aucun profil.
    # ⚠ Le champ est `unit_type`, pas `type` (mesuré — un `u.type` lève).
    unites = []
    if reviewer:
        from .models import OrgUnit
        unites = [{'id': u.id, 'nom': u.name or u.code} for u in OrgUnit.objects.order_by('name')]

    return render(request, 'common/memories.html', {
        'actifs': actifs,
        'attente': attente,
        'unites': unites,
        'total': len(actifs),
        'sans_vecteur': sum(1 for s in actifs if s['sans_vecteur']),
        'kinds': kinds,
        'facettes': facettes,
        'q': q,
        'url_reset': reverse('common:memories'),
        'est_staff': reviewer,
        # Même volet réduit que ses sœurs catalogues (`tests_inspecteur_registre`).
        'volet': volet(medias=False, actions=False),
    })


@login_required
@require_POST
def memories_approve(request):
    """Valide UN souvenir de la file de revue — le geste que `WAMA_MEMORY §6` exigeait.

    ⚠ RÉSERVÉ AU STAFF, pour la même raison que la file elle-même : elle n'est pas scopée.
    Un simple connecté n'a rien à approuver qui ne lui appartienne pas.

    ⚠ `visibility` est demandée DANS LE MÊME APPEL, jamais après : approuver un souvenir
    `user=NULL` + `private` (les 25 importés de `memory.json`) ne le rend visible à personne —
    le relecteur croirait avoir agi. Le geste est « je valide ET je décide de la portée ».
    """
    from .memory.store import approve
    from .models import MemoryItem

    from wama.accounts.permissions import is_admin_tier
    if not is_admin_tier(request.user):
        return JsonResponse({'erreur': 'réservé au staff'}, status=403)

    try:
        pk = int(request.POST.get('id') or 0)
    except (TypeError, ValueError):
        return JsonResponse({'erreur': 'id invalide'}, status=400)

    item = MemoryItem.objects.filter(pk=pk, approved_at__isnull=True).first()
    if item is None:
        return JsonResponse({'erreur': 'souvenir introuvable ou déjà approuvé'}, status=404)

    visibilite = (request.POST.get('visibility') or '').strip() or None
    unite = None
    if visibilite == 'unit':
        from .models import OrgUnit
        unite = OrgUnit.objects.filter(pk=request.POST.get('org_unit') or 0).first()
        if unite is None:
            return JsonResponse({'erreur': "visibilité « unité » sans unité valide"}, status=400)

    resultat = approve(item, par=request.user, visibility=visibilite, scope_org_unit=unite)
    if resultat is None:
        return JsonResponse({'erreur': 'approbation refusée'}, status=400)
    return JsonResponse({'approuve': resultat.pk, 'visibilite': resultat.visibility})


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
        from .app_registry import app_identity
        app_id = self.app_id or (self.request.path.split('/') + [''])[1]
        url_name = app_identity(app_id)['url_name']
        if not url_name:
            return '/'
        return reverse(url_name) + f'#{self.tab_anchor}'


class AppAboutView(AppTabRedirectView):
    tab_anchor = 'about-pane'


class AppHelpView(AppTabRedirectView):
    tab_anchor = 'help-pane'


@login_required
def app_about_models(request, app_id: str):
    """Fragment de l'onglet « À propos » : les modèles des selects de catalogue de l'app et les
    publications que leurs auteurs y rattachent (`services/model_publications`). Chargé par le
    gabarit commun à l'ouverture de l'onglet — pas au rendu de chaque page d'app."""
    from django.http import Http404
    from django.shortcuts import render

    from wama.model_manager.models import ModelSource

    from .app_registry import APP_CATALOG
    from .services.model_publications import app_models

    # Une app du catalogue, ou une app qui DÉCLARE des modèles sans y figurer (monde Lab).
    if app_id not in APP_CATALOG and app_id not in ModelSource.values:
        raise Http404
    return render(request, 'common/_about_models.html', {'groups': app_models(app_id)})

@login_required
def api_partage(request, surface: str, nature: str, pk: int):
    """PARTAGE d'un élément ou d'un LOT de file — l'interface du mécanisme de visibilité (§7).

    GET  → les portées OFFRABLES par cet utilisateur + l'état courant de la cible.
    POST → applique la portée (`visibility`, `org_unit_id`, `project_id`).

    `surface` et non « app » : la clé est celle de `PreviewRegistry`, et l'enhancer en expose
    DEUX (`enhancer`, `audio_enhancer`) avec deux modèles distincts. Le front la lit sur la
    card elle-même (`data-preview-url` = `/common/preview/<surface>/<pk>/`, présent sur les 10
    gabarits de card du parc — mesuré) : c'est déjà l'idiome de l'inspecteur, qui en dérive
    l'URL de détail. Aucune déclaration nouvelle, et le cas de l'enhancer se distingue tout seul.

    `nature` ∈ {element, lot}. Le LOT est une cible de plein droit — « le batch est l'unité de
    partage » (imager/views.py:231) — et son partage DESCEND à ses éléments, là où le partage
    d'un élément REMONTE à son lot. Les deux sens sont des exigences, pas des commodités : le
    filtre de lecture s'applique aux deux niveaux, donc n'en écrire qu'un produit un partage
    qui ne montre rien.

    ⚠ La cible est cherchée DANS LE PÉRIMÈTRE DE L'UTILISATEUR (`user=request.user`), donc un pk
    étranger rend 404 et non 403 : un 403 confirmerait l'existence de l'objet d'un autre. Le
    service revérifie la propriété — c'est son invariant, pas une redite : il est appelable
    ailleurs (commande de gestion prévue au §7.5).

    ⚠ Ce endpoint n'accorde AUCUN droit d'écriture (cf. `services/sharing`). Le partage est en
    lecture seule par construction ; l'escalade est le jalon S3 `AccessGrant`.
    """
    from django.shortcuts import get_object_or_404
    from wama.common.services.access_requests import AccessRequestRefused
    from wama.common.services.sharing import (ConsentRequired, RefusDePartage, etat, partager,
                                              partager_lot, portees_offrables)
    from wama.common.utils.batch_common import batch_model_for_app
    from wama.common.utils.preview_registry import PreviewRegistry

    if nature not in ('element', 'lot'):
        return JsonResponse({'error': f"nature inconnue : {nature}"}, status=404)

    modele_element = PreviewRegistry.get_model(surface)
    if modele_element is None:
        return JsonResponse({'error': f"surface inconnue : {surface}"}, status=404)

    if nature == 'lot':
        modele = batch_model_for_app(surface)
        if modele is None:
            return JsonResponse({'error': f"{surface} n'a pas de modèle de lot"}, status=404)
    else:
        modele = modele_element
    cible = get_object_or_404(modele, pk=pk, user=request.user)

    if request.method == 'GET':
        # `modes` (2026-10-03) : les modes DÉCLARÉS, la modale grise ceux qui n'existent pas encore.
        from wama.common.services.sharing import SHARE_MODES
        return JsonResponse({'ok': True, 'surface': surface, 'nature': nature, 'pk': pk,
                             'etat': etat(cible),
                             'portees': portees_offrables(request.user),
                             'modes': list(SHARE_MODES)})

    if request.method != 'POST':
        return JsonResponse({'error': 'méthode non autorisée'}, status=405)

    # `request.POST` et JAMAIS `request.body` : sur un POST multipart le flux est déjà consommé
    # par le middleware CSRF et `request.body` lève `RawPostDataException` — leçon payée deux
    # fois dans ce dépôt (`queue_manipulation.ids_from_request`).
    visibility = request.POST.get('visibility') or ''
    unite = request.POST.get('org_unit_id') or None
    projet = request.POST.get('project_id') or None
    # Le consentement VALIDÉ dans la modale (élément qui porte une personne, 2026-09-30).
    consent = request.POST.get('consent') == '1'
    # PARTAGE À UNE PERSONNE (2026-10-06) — mêmes coordonnées : `person` (identifiant ou e-mail,
    # résolu comme pour « Transférer à… ») + `mode` ; `revoke_person` (id) pour le retirer.
    from django.contrib.auth import get_user_model
    from wama.common.services.card_transfer import find_recipient
    from wama.common.services.sharing import share_with_person, unshare_person
    try:
        if request.POST.get('person'):
            recipient = find_recipient(request.POST.get('person'), request.user)
            report = share_with_person(request.user, cible, modele_element, recipient,
                                       request.POST.get('mode') or 'read', nature=nature,
                                       surface=surface, consent=consent)
            return JsonResponse({'ok': True, **report, 'persons': etat(cible)['persons']})
        if request.POST.get('revoke_person'):
            who = get_object_or_404(get_user_model(), pk=request.POST.get('revoke_person'))
            removed = unshare_person(request.user, cible, who)
            return JsonResponse({'ok': True, 'removed': removed,
                                 'persons': etat(cible)['persons']})
        if nature == 'lot':
            compte_rendu = partager_lot(request.user, cible, modele_element,
                                        visibility, unite, projet, consent=consent)
        else:
            compte_rendu = partager(request.user, cible, visibility, unite, projet, consent=consent)
        # « Retirer le partage » de la page Partages : la portée ET les personnes.
        if request.POST.get('unshare_persons') == '1':
            for person in etat(cible)['persons']:
                unshare_person(request.user, cible,
                               get_user_model().objects.get(pk=person['user_id']))
    except ConsentRequired as refus:
        # 409 et le TEXTE à valider : la modale le montre au lieu d'un refus sec.
        return JsonResponse({'ok': False, 'consent_required': True, 'reason': str(refus),
                             'statement': refus.statement}, status=409)
    except (RefusDePartage, AccessRequestRefused) as refus:
        return JsonResponse({'ok': False, 'reason': str(refus)}, status=400)
    return JsonResponse({'ok': True, **compte_rendu})

@login_required
def api_released_files(request):
    """GET — les fichiers que des cards retirées ont LIBÉRÉS et que l'utilisateur n'a pas encore vus
    annoncés ; ils le sont désormais (une fois). `common/services/released_files.py`."""
    from wama.common.services.released_files import take_unannounced
    return JsonResponse({'files': take_unannounced(request.user)})


@login_required
@require_POST
def api_released_files_delete(request):
    """POST `ids` — LE geste explicite : supprimer des fichiers libérés. Chacun est revérifié
    (toujours inutilisé, à cet utilisateur) juste avant ; un fichier repris entre-temps est gardé."""
    from wama.common.services.released_files import delete_released
    ids = [int(i) for i in request.POST.getlist('ids') if str(i).isdigit()]
    return JsonResponse(delete_released(request.user, ids, request.POST.getlist('paths')))


@login_required
@require_POST
def api_transfer(request):
    """POST `surface`, `pk`, `to` (identifiant ou e-mail), `consent`, `nature` (element | lot) —
    « Transférer à… » : la card, ou le lot entier, change de propriétaire
    (`common/services/card_transfer.py`, 2026-10-01).

    Coordonnées = celles du partage (`api_partage`) : la SURFACE de `PreviewRegistry` et un pk
    cherché parmi les cards DE L'UTILISATEUR (404 sinon). Les refus PRÉVUS (destinataire inconnu,
    consentement à valider) répondent 200 avec un motif : un statut d'erreur pour un cas prévu rend
    le contrôle aveugle (leçon du gestionnaire de fichiers, `WAMA_VERIFICATION`). La réponse dit
    ce que devient le lot quitté (`batch`), pour que la file se mette à jour sans rechargement."""
    from django.shortcuts import get_object_or_404
    from wama.common.services.card_transfer import (TransferConsentRequired, find_recipient,
                                                    transfer_card, transfer_lot)
    from wama.common.services.sharing import RefusDePartage
    from wama.common.utils.batch_common import batch_model_for_app, batch_snapshot, batch_state
    from wama.common.utils.preview_registry import PreviewRegistry

    surface = request.POST.get('surface') or ''
    model = PreviewRegistry.get_model(surface)
    if model is None:
        return JsonResponse({'error': 'surface inconnue'}, status=404)
    consent = request.POST.get('consent') in ('1', 'true', 'on')
    # `nature=lot` (2026-10-01) : le LOT entier part, avec ses cards — mêmes coordonnées que le
    # partage d'un lot (`api_partage`) : la surface d'une card fille, le pk du lot.
    is_lot = request.POST.get('nature') == 'lot'
    if is_lot:
        batch_model = batch_model_for_app(surface)
        if batch_model is None:
            return JsonResponse({'error': f"{surface} n'a pas de modèle de lot"}, status=404)
        target = get_object_or_404(batch_model, pk=request.POST.get('pk'), user=request.user)
    else:
        target = get_object_or_404(model, pk=request.POST.get('pk'), user=request.user)
    try:
        recipient = find_recipient(request.POST.get('to'), request.user)
        if is_lot:
            return JsonResponse({'transferred': True, 'nature': 'lot',
                                 **transfer_lot(request.user, target, model, recipient, consent)})
        snapshot = batch_snapshot(target)
        report = transfer_card(request.user, target, recipient, consent=consent)
    except TransferConsentRequired as exc:
        return JsonResponse({'transferred': False, 'consent_required': True,
                             'statement': exc.statement})
    except RefusDePartage as exc:
        return JsonResponse({'transferred': False, 'reason': str(exc)})
    return JsonResponse({'transferred': True, **report, 'batch': batch_state(snapshot, model)})


@login_required
def api_people(request):
    """GET `q` — les PERSONNES à proposer pour un partage ou un transfert (complétion, 2026-10-07) :
    nom et identifiant, jamais l'adresse e-mail ; sans `q`, les personnes proches
    (`card_transfer.suggest_recipients`)."""
    from wama.common.services.card_transfer import suggest_recipients
    return JsonResponse({'people': suggest_recipients(request.user, request.GET.get('q') or '')})


@login_required
@require_POST
def api_reception(request):
    """POST `surface`, `pk`, `nature` (element | lot), `action` (hide | show) — RANGER une entrée
    REÇUE dans sa file (`common/services/reception.py`, 2026-10-02, `WAMA_COLLABORATION §3bis.2`).

    Mêmes coordonnées que le partage et le transfert. L'unité est l'ENTRÉE de file : désigner une
    card retire son lot entier (la file se construit à partir des lots), ou la card seule quand
    elle n'a pas de lot. L'élément n'est cherché qu'au pk : c'est le service qui revérifie qu'il est
    VISIBLE par l'utilisateur et qu'il n'est PAS à lui. Un refus prévu répond 200 avec son motif."""
    from wama.common.services.reception import NotReceived, hide, show
    from wama.common.utils.batch_common import batch_model_for_app, batch_of
    from wama.common.utils.preview_registry import PreviewRegistry

    surface = request.POST.get('surface') or ''
    model = PreviewRegistry.get_model(surface)
    if model is None:
        return JsonResponse({'error': 'surface inconnue'}, status=404)
    pk = request.POST.get('pk')
    if not str(pk or '').isdigit():
        return JsonResponse({'error': 'pk manquant'}, status=400)
    if request.POST.get('nature') == 'lot':
        batch_model = batch_model_for_app(surface)
        entry = batch_model.objects.filter(pk=pk).first() if batch_model else None
    else:
        card = model.objects.filter(pk=pk).first()
        entry = (batch_of(card) or card) if card is not None else None
    if entry is None:
        return JsonResponse({'done': False, 'reason': 'élément introuvable'})
    gesture = show if request.POST.get('action') == 'show' else hide
    try:
        gesture(request.user, entry)
    except NotReceived as exc:
        return JsonResponse({'done': False, 'reason': str(exc)})
    return JsonResponse({'done': True, 'entry': f'{entry._meta.label}#{entry.pk}'})


@login_required
@require_POST
def api_replace_grant(request):
    """POST `surface`, `pk` — l'utilisateur a CONFIRMÉ qu'il arrête le traitement en cours de
    cette card pour la relancer (2026-10-22, décision de Fabien). L'accord, à usage unique, est
    consommé par le lancement ordinaire de l'app qui suit (`process_control.begin_processing`) ;
    la confirmation elle-même est posée par la brique des actions de card (`queue-actions.js`),
    pour toutes les apps. Seul qui peut MODIFIER la card l'obtient (propriétaire, collaborateur)."""
    from wama.common.utils.preview_registry import PreviewRegistry
    from wama.common.utils.process_control import grant_replace
    from wama.common.utils.scoping import editable_or_404

    surface = request.POST.get('surface') or ''
    model = PreviewRegistry.get_model(surface)
    if model is None:
        return JsonResponse({'error': 'surface inconnue'}, status=404)
    pk = request.POST.get('pk')
    if not str(pk or '').isdigit():
        return JsonResponse({'error': 'pk manquant'}, status=400)
    card = editable_or_404(model, request.user, pk=int(pk))
    running = getattr(card, 'status', None) == 'RUNNING'
    if running:
        grant_replace(model, card.pk, request.user)
    return JsonResponse({'granted': running})


def _shared_target(surface, pk, nature):
    """La card (ou le lot, `nature=lot`) désignée par les coordonnées du partage — cherchée au seul
    pk : c'est le service appelé qui revérifie la visibilité et la propriété. None si introuvable."""
    from wama.common.utils.batch_common import batch_model_for_app
    from wama.common.utils.preview_registry import PreviewRegistry
    if not str(pk or '').isdigit():
        return None
    model = batch_model_for_app(surface) if nature == 'lot' else PreviewRegistry.get_model(surface)
    return model.objects.filter(pk=pk).first() if model is not None else None


@login_required
def api_access(request):
    """GET `surface`, `pk`, `nature` — « Mon accès » d'une card REÇUE : le mode courant, les modes
    déclarés (grisés s'ils n'existent pas), les demandes en attente (2026-10-03)."""
    from wama.common.services.access_requests import access_state
    from wama.common.services.reception import NotReceived, _check_received
    obj = _shared_target(request.GET.get('surface'), request.GET.get('pk'), request.GET.get('nature'))
    if obj is None:
        return JsonResponse({'error': 'élément introuvable'}, status=404)
    try:
        _check_received(request.user, obj)
    except NotReceived as exc:
        return JsonResponse({'error': str(exc)}, status=404)
    return JsonResponse(access_state(request.user, obj))


@login_required
@require_POST
def api_access_request(request):
    """POST `surface`, `pk`, `nature`, `level` — DEMANDER un niveau sur une card reçue ; le
    propriétaire est prévenu dans WAMA. Un refus prévu répond 200 avec son motif."""
    from wama.common.services.access_requests import AccessRequestRefused, request_access
    surface, nature = request.POST.get('surface') or '', request.POST.get('nature') or 'element'
    obj = _shared_target(surface, request.POST.get('pk'), nature)
    if obj is None:
        return JsonResponse({'requested': False, 'reason': 'élément introuvable'})
    try:
        grant = request_access(request.user, obj, request.POST.get('level') or '', surface=surface)
    except AccessRequestRefused as exc:
        return JsonResponse({'requested': False, 'reason': str(exc)})
    return JsonResponse({'requested': True, 'id': grant.pk})


@login_required
def access_request_page(request, pk: int):
    """La DEMANDE, là où la notification renvoie : ce qui est demandé, par qui ; Accepter / Refuser
    pour le propriétaire, l'état pour le demandeur. Personne d'autre ne la voit.

    Une demande de PROMOTION (niveau `system`, 2026-10-20) se tranche par un ADMINISTRATEUR : c'est
    lui qui y répond (« Valider / Refuser »), et la page lui donne de quoi INSPECTER l'élément —
    sa famille, son auteur, sa portée, et le lien vers la page qui le montre."""
    from django.http import Http404
    from django.shortcuts import render
    from wama.accounts.permissions import is_admin_tier
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import _label, promotion_family, target
    from .utils.volet import VOLET_AUCUN
    grant = ObjectGrant.objects.select_related('beneficiary', 'granted_by').filter(pk=pk).first()
    obj = target(grant) if grant is not None else None
    if grant is not None and grant.level == ObjectGrant.LEVEL_SYSTEM:
        decider = is_admin_tier(request.user)
        if not (decider or grant.beneficiary_id == request.user.pk):
            raise Http404
        registry = promotion_family(obj) if obj is not None else None
        from django.urls import NoReverseMatch, reverse
        try:
            inspect_url = reverse(registry.url_name) if registry and registry.url_name else ''
        except NoReverseMatch:
            inspect_url = ''
        from wama.common.manifests.ownership import provenance_of
        return render(request, 'common/access_request.html', {
            'grant': grant, 'is_owner': decider, 'promotion': True,
            'element_label': _label(obj) if obj is not None else '(élément supprimé)',
            'element_app': registry.label if registry else '',
            'family': registry.label if registry else '',
            'facts': provenance_of(obj, request.user) if obj is not None else {},
            'inspect_url': inspect_url,
            'volet': VOLET_AUCUN,
        })
    is_owner = obj is not None and getattr(obj, 'user_id', None) == request.user.pk
    # Celui qui a RÉPONDU la voit encore : accepter la propriété lui a justement retiré la card
    # (mesuré par le geste du 2026-10-03 — la page lui répondait 404 juste après son « Accepter »).
    answered_by_me = grant is not None and grant.granted_by_id == request.user.pk
    if grant is None or not (is_owner or answered_by_me or grant.beneficiary_id == request.user.pk):
        raise Http404
    return render(request, 'common/access_request.html', {
        'grant': grant, 'is_owner': is_owner,
        'element_label': _label(obj) if obj is not None else '(élément supprimé)',
        'element_app': obj._meta.app_label if obj is not None else '',
        # La page n'a rien à mettre au volet : aucune section par défaut (2026-10-20).
        'volet': VOLET_AUCUN,
    })


@login_required
@require_POST
def api_access_request_answer(request, pk: int):
    """POST `accept` (1|0), `consent` — le PROPRIÉTAIRE répond. Accepter la propriété cède l'élément
    (« Transférer à… ») ; un consentement manquant revient avec son texte à valider."""
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import AccessRequestRefused, answer
    from wama.common.services.card_transfer import TransferConsentRequired
    from wama.common.services.sharing import RefusDePartage
    grant = ObjectGrant.objects.filter(pk=pk).first()
    if grant is None:
        return JsonResponse({'done': False, 'reason': 'demande introuvable'}, status=404)
    try:
        if grant.level == ObjectGrant.LEVEL_SYSTEM:
            # Une PROMOTION : un administrateur la tranche (`answer_promotion`).
            from wama.common.services.access_requests import answer_promotion
            try:
                report = answer_promotion(request.user, grant,
                                          request.POST.get('accept') in ('1', 'true'))
            except (PermissionError, ValueError) as exc:
                raise AccessRequestRefused(str(exc)) from exc
            return JsonResponse({'done': True, **report})
        report = answer(request.user, grant, request.POST.get('accept') in ('1', 'true'),
                        consent=request.POST.get('consent') in ('1', 'true', 'on'))
    except TransferConsentRequired as exc:
        return JsonResponse({'done': False, 'consent_required': True, 'statement': exc.statement})
    except (AccessRequestRefused, RefusDePartage) as exc:
        return JsonResponse({'done': False, 'reason': str(exc)})
    return JsonResponse({'done': True, **report})


@login_required
def shares_page(request):
    """La page « Partages » (`WAMA_COLLABORATION §5.3`, 2026-10-03) : ce que j'ai partagé — portée,
    collaborateurs, et c'est ICI qu'on retire un droit (E5) ou le partage — et ce qu'on m'a
    partagé, avec mon accès ; les demandes en attente dans les deux sens."""
    from django.shortcuts import render
    from wama.common.services.journal import TRIS
    from wama.common.services.sharing import CURRENT_SHARE_MODE, shares_overview
    data = shares_overview(request.user)
    # UNE liste, comme les autres pages du compte et des registres (2026-10-20, Fabien : « faire
    # converger avec toutes les autres pages ») : le SENS devient une facette de la barre
    # commune au lieu de deux onglets, et l'ordre de départ est celui du premier tri déclaré.
    items = [dict(s, direction="Partagé par moi") for s in data['shared']] + \
            [dict(s, direction="Partagé avec moi") for s in data['received']]
    items.sort(key=lambda s: s['scope_since'].timestamp() if s.get('scope_since') else 0,
               reverse=True)
    # Le libellé d'une facette est celui que la fiche du volet dérive de sa clé (`data-f-partage`
    # → « Partage ») : le filtre et la fiche disent le même mot.
    facettes = [{'cle': key, 'label': label, 'tous': tous} for key, label, tous in (
        ('sens', 'Sens', 'Tous les partages'), ('app', 'App', 'Toutes'),
        ('nature', 'Nature', 'Toutes'), ('partage', 'Partage', 'Tous'))]
    # Les libellés de tri du journal (`journal.TRIS`, alignés sur la barre des files).
    sort_options = [('since:desc', TRIS['recent']), ('since:asc', TRIS['oldest']),
                    ('label:asc', TRIS['name']), ('app:asc', 'App')]
    return render(request, 'common/shares.html', {
        **data, 'items': items, 'facettes': facettes, 'sort_options': sort_options,
        # Ce qu'une PORTÉE accorde, déclaré une fois (`SHARE_MODES`) : la lecture.
        'scope_mode': CURRENT_SHARE_MODE,
        # Ce que la page REMPLIT : l'aperçu et le détail d'un élément partagé (ceux de sa card,
        # par l'inspecteur commun) et la fiche de chaque partage ; pas d'actions dans le volet.
        'volet': volet(actions=False)})


@login_required
@require_POST
def api_promotion_request(request):
    """POST `registry` + `pk` (ou `key`, le champ d'identifiant que le registre nomme) — « Demander
    la promotion » d'un élément d'auteur, LA route de toutes les familles (skill, thème de charte,
    modèle…, `ROADMAP §29` 6a). Seul son auteur la trouve ; les administrateurs sont prévenus et la
    notification mène à la demande (`access_requests.request_promotion`)."""
    import json

    from wama.common.services.access_requests import (AccessRequestRefused, request_page_url,
                                                      request_promotion)
    from wama.common.services.sharing import catalogue_owned_rows
    try:
        data = json.loads(request.body or '{}') if request.content_type == 'application/json' \
            else request.POST
    except ValueError:
        return JsonResponse({'requested': False, 'reason': 'JSON invalide'}, status=400)
    found = next(((r, m) for r, m in catalogue_owned_rows() if r.key == data.get('registry')), None)
    row = None
    if found is not None:
        registry, model = found
        rows = model._default_manager.filter(owner=request.user)
        if str(data.get('pk') or '').isdigit():
            row = rows.filter(pk=data.get('pk')).first()
        elif data.get('key') and registry.owner_key:
            row = rows.filter(**{registry.owner_key: data.get('key')}).first()
    if row is None:
        return JsonResponse({'requested': False, 'reason': 'élément introuvable'}, status=404)
    try:
        grant = request_promotion(request.user, row)
    except AccessRequestRefused as exc:
        return JsonResponse({'requested': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'requested': True, 'url': request_page_url(grant)})


@login_required
@require_POST
def api_catalogue_unshare(request):
    """POST `registry`, `pk` — « Retirer le partage » d'un élément de CATALOGUE depuis la page
    « Partages » (skill de prompt, thème de charte…, `ROADMAP §29`) : il redevient privé, par le
    service commun. La famille se lit au registre (`sharing.catalogue_owned_rows`) ; seule une
    ligne de son auteur est trouvée, un pk étranger rend 404."""
    from wama.common.services.sharing import RefusDePartage, catalogue_owned_rows, share_scope
    model = next((m for r, m in catalogue_owned_rows() if r.key == request.POST.get('registry')),
                 None)
    pk = request.POST.get('pk') or ''
    row = model._default_manager.filter(pk=pk, owner=request.user).first() \
        if model is not None and pk.isdigit() else None
    if row is None:
        return JsonResponse({'ok': False, 'reason': 'élément introuvable'}, status=404)
    try:
        share_scope(request.user, row, 'private')
    except RefusDePartage as exc:
        return JsonResponse({'ok': False, 'reason': str(exc)}, status=400)
    return JsonResponse({'ok': True})


@login_required
@require_POST
def api_grant_revoke(request, pk: int):
    """POST — le PROPRIÉTAIRE retire un droit accordé (E5 : effet immédiat, tâche en cours finie,
    bénéficiaire prévenu)."""
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import AccessRequestRefused, revoke
    grant = ObjectGrant.objects.filter(pk=pk).first()
    if grant is None:
        return JsonResponse({'done': False, 'reason': 'droit introuvable'}, status=404)
    try:
        revoke(request.user, grant)
    except AccessRequestRefused as exc:
        return JsonResponse({'done': False, 'reason': str(exc)})
    return JsonResponse({'done': True})


@login_required
@require_POST
def api_edit_lock(request):
    """POST `surface`, `pk`, `nature`, `action` (acquire | release) — le VERROU DOUX d'une card
    partagée en collaboration (E4, 2026-10-03) : rend qui d'autre a ses réglages ouverts. Réservé à
    qui peut éditer (`scoping.can_edit`) ; ne refuse jamais un enregistrement, il le DIT."""
    from wama.common.services import edit_lock
    from wama.common.utils.scoping import can_edit
    obj = _shared_target(request.POST.get('surface'), request.POST.get('pk'),
                         request.POST.get('nature') or 'element')
    if obj is None or not can_edit(request.user, obj):
        return JsonResponse({'error': 'élément introuvable'}, status=404)
    if request.POST.get('action') == 'release':
        edit_lock.release(request.user, obj)
        return JsonResponse({'released': True})
    return JsonResponse(edit_lock.acquire(request.user, obj))


@login_required
def api_notifications_recent(request):
    """GET `after` (id) — le nombre de non lues et les NOUVELLES non lues (id > `after`, 5 au plus) :
    ce que lit le JS commun pour tenir la cloche à jour et montrer chaque nouvelle notification en
    bas à droite (2026-10-03). Sans `after`, rend seulement le compte et le dernier id.

    `sound` (2026-10-06) : le son que la page JOUE pour chaque nouvelle notification — décidé ICI
    (type sonore + préférence du profil, `notifications.notification_sound`), jamais par le JS."""
    from wama.common.models import Notification
    from wama.common.utils.notifications import notification_sound
    unread = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
    last = Notification.objects.filter(recipient=request.user).order_by('-pk').values_list(
        'pk', flat=True).first() or 0
    after = request.GET.get('after')
    items = []
    if str(after or '').isdigit():
        items = [{'id': n.pk, 'title': n.title, 'body': n.body, 'url': n.url,
                  'sound': notification_sound(n, request.user)}
                 for n in unread.filter(pk__gt=int(after)).order_by('pk')[:5]]
    return JsonResponse({'unread': unread.count(), 'last_id': last, 'items': items})


@login_required
def api_notifications_list(request):
    """GET `filter` (`unread` | `all`, défaut), `limit` (défaut 20, au plus 50) — les
    notifications du PANNEAU de la cloche (`WAMA_COLLABORATION.md §2.3`, 2026-10-13) : les plus
    récentes d'abord, chacune avec son style et ses gestes (`services.notification_panel`)."""
    from wama.common.services.notification_panel import notification_list
    try:
        limit = int(request.GET.get('limit') or 20)
    except ValueError:
        limit = 20
    return JsonResponse(notification_list(request.user,
                                          unread_only=request.GET.get('filter') == 'unread',
                                          limit=limit))


@login_required
@require_POST
def api_notification_act(request, pk: int, action: str):
    """POST — `read`, `unread` ou `delete` sur UNE notification du compte (panneau de la cloche
    et page complète). Rend le nombre de non lues, pour la pastille."""
    from django.utils import timezone
    from wama.common.models import Notification
    note = Notification.objects.filter(pk=pk, recipient=request.user).first()
    if note is None:
        return JsonResponse({'done': False, 'reason': 'notification introuvable'}, status=404)
    if action == 'delete':
        note.delete()
    elif action in ('read', 'unread'):
        note.read_at = timezone.now() if action == 'read' else None
        note.save(update_fields=['read_at'])
    else:
        return JsonResponse({'done': False, 'reason': f'geste inconnu : {action}'}, status=400)
    unread = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
    return JsonResponse({'done': True, 'unread': unread})


@login_required
@require_POST
def api_notifications_read_all(request):
    """POST — « Tout marquer comme lu » du panneau de la cloche."""
    from django.utils import timezone
    from wama.common.models import Notification
    n = Notification.objects.filter(recipient=request.user,
                                    read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({'done': True, 'marked': n, 'unread': 0})


@login_required
def api_reception_hidden(request):
    """GET `app` — combien d'entrées reçues l'utilisateur a retirées de sa file dans cette app
    (la ligne « Réafficher » sous la barre de la file)."""
    from wama.common.services.reception import hidden_count
    return JsonResponse({'count': hidden_count(request.user, request.GET.get('app') or '')})


@login_required
@require_POST
def api_reception_show_all(request):
    """POST `app` — remet dans la file tout ce que l'utilisateur en avait retiré dans cette app."""
    from wama.common.services.reception import show_all
    return JsonResponse({'shown': show_all(request.user, request.POST.get('app') or '')})


@login_required
@require_POST
def api_released_files_renew(request):
    """POST `ids` — « Garder » un fichier inutilisé quand la rétention est FINIE : il repart pour
    une durée complète, et sera de nouveau annoncé avant son prochain terme."""
    from wama.common.services.released_files import renew_released
    ids = [int(i) for i in request.POST.getlist('ids') if str(i).isdigit()]
    return JsonResponse({'renewed': renew_released(request.user, ids)})


@login_required
def api_released_files_all(request):
    """GET — TOUS les fichiers inutilisés de l'utilisateur (onglet « Inutilisés » de la
    médiathèque), avec taille et ancienneté. Lecture seule : rien n'est marqué annoncé."""
    from wama.common.services.released_files import list_unused
    return JsonResponse(list_unused(request.user))


@login_required
@require_POST
def api_released_files_keep(request):
    """POST `ids` ou `paths` — l'utilisateur GARDE ces fichiers (case de la confirmation laissée
    décochée) : rien n'est supprimé, et ils ne seront plus annoncés."""
    from wama.common.services.released_files import keep_released
    ids = [int(i) for i in request.POST.getlist('ids') if str(i).isdigit()]
    return JsonResponse({'kept': keep_released(request.user, ids, request.POST.getlist('paths'))})


@login_required
def api_released_files_preview(request):
    """GET `surface`, `nature` ∈ {element, lot, queue}, `pk` — les fichiers que ce retrait LIBÉRERAIT
    (possédés, désignés par rien d'autre ensuite). La confirmation de suppression ne propose
    « Supprimer aussi le fichier » que s'il y en a (décision de Fabien, 2026-10-01).

    Mêmes coordonnées que le partage (`api_partage`) : la SURFACE de `PreviewRegistry` — l'enhancer
    en a deux — et un pk cherché DANS LE PÉRIMÈTRE DE L'UTILISATEUR (404 sinon). `queue` = toute la
    file de cette surface, ce que retire « Tout effacer ».
    """
    from django.shortcuts import get_object_or_404
    from wama.common.services.released_files import freed_by
    from wama.common.utils.batch_common import batch_elements, batch_model_for_app
    from wama.common.utils.preview_registry import PreviewRegistry

    surface = request.GET.get('surface') or ''
    nature = request.GET.get('nature') or 'element'
    model = PreviewRegistry.get_model(surface)
    if model is None or nature not in ('element', 'lot', 'queue'):
        return JsonResponse({'error': 'cible inconnue'}, status=404)
    batch_model = batch_model_for_app(surface)
    if nature == 'element':
        instances = [get_object_or_404(model, pk=request.GET.get('pk'), user=request.user)]
    elif nature == 'lot':
        if batch_model is None:
            return JsonResponse({'error': f"{surface} n'a pas de modèle de lot"}, status=404)
        lot = get_object_or_404(batch_model, pk=request.GET.get('pk'), user=request.user)
        instances = [lot, *batch_elements(lot, model)]
    else:
        instances = list(model.objects.filter(user=request.user))
        if batch_model is not None:
            instances += list(batch_model.objects.filter(user=request.user))
    paths = freed_by(instances)
    return JsonResponse({'files': [{'path': p, 'name': p.rsplit('/', 1)[-1]} for p in paths]})


@login_required
def api_envoyer_vers(request, surface: str, pk: int):
    """ENVOYER VERS — quelles apps peuvent recevoir la sortie de cet élément, et par où.

    RÉSOLVEUR EN LECTURE SEULE. Il ne réalise PAS l'envoi : il rend les chemins de sortie et les
    destinations éligibles, et le client POSTe sur `filemanager:api_import` — l'endpoint qui
    reçoit déjà « Envoyer vers… » depuis le gestionnaire de fichiers (critère de grille
    `filemanager_import` 10/10, scénario nocturne `<app>.send_to`). Écrire ici un second chemin
    d'import aurait dupliqué ses gardes — dont `is_path_allowed`, qui est exactement le genre de
    garde qu'on ne recopie pas.

    Cadre (Fabien 2026-09-08) : « la sortie qu'on envoie en entrée d'une autre app, dans l'idée
    de faire du chaînage progressif, sans forcément devoir passer par le studio ».

    ⚠ Les destinations sont DÉRIVÉES de trois conditions (importeur, extension déclarée, accès),
    jamais listées : le menu du gestionnaire de fichiers a offert pendant des semaines trois apps
    que le serveur refusait (`WAMA_VERIFICATION §Geste 14`). Une liste vide est une RÉPONSE.
    """
    from django.urls import reverse
    from wama.common.services.send_to import destinations, sorties_de
    from wama.common.utils.preview_registry import PreviewRegistry
    from wama.common.utils.scoping import visible_or_404

    modele = PreviewRegistry.get_model(surface)
    if modele is None:
        return JsonResponse({'error': f"surface inconnue : {surface}"}, status=404)
    # Ce que le compte VOIT — le sien ou une card REÇUE (2026-10-16 : en mode lecture, le
    # destinataire peut « envoyer vers une autre app », `WAMA_COLLABORATION §3bis` ; le menu le lui
    # offrait, ce résolveur rendait 404 et le sous-menu « Indisponible »). Un pk qu'il ne voit pas
    # rend 404, pas 403 (cf. `api_partage`). L'import revalide le chemin (`readable_by`).
    element = visible_or_404(modele, request.user, pk=pk)

    chemins = sorties_de(surface, element)
    return JsonResponse({
        'ok': True, 'surface': surface, 'pk': pk,
        'chemins': chemins,
        'destinations': destinations(request.user, chemins),
        # L'endpoint est RENDU et non écrit dans le JS : le front n'a pas à connaître les URLs
        # d'une autre app, et un changement de route ne casse pas la brique commune.
        'endpoint': reverse('filemanager:api_import'),
    })


@login_required
@require_POST
def api_batch_label(request, surface: str, pk: int):
    """NOMMER UN LOT — POST `label` (vide = effacer le nom, le lot reprend son titre dérivé).

    Même adressage que « Envoyer le lot vers… » (`batch_model_for_app`), mais une ÉCRITURE : le
    lot du compte ou celui sur lequel il COLLABORE (`editable_or_404`, le geste tracé comme une
    modification du lot), jamais un lot seulement reçu en lecture. Rend l'identité recalculée
    (`batch_identity.identity_of`) : la card mère se met à jour sans rechargement de la page."""
    from wama.common.services import batch_identity
    from wama.common.utils.batch_common import batch_model_for_app
    from wama.common.utils.batch_views import read_settings_payload
    from wama.common.utils.scoping import editable_or_404

    batch_model = batch_model_for_app(surface)
    if batch_model is None:
        return JsonResponse({'error': f"{surface} n'a pas de modèle de lot"}, status=404)
    batch = editable_or_404(batch_model, request.user, trace='regle', pk=pk)
    batch_identity.rename(batch, read_settings_payload(request).get('label', ''))
    identity = batch_identity.identity_of(batch)
    return JsonResponse({'ok': True, 'surface': surface, 'pk': pk, 'identity': identity,
                         'title': batch_identity.display_title(identity)})


@login_required
def api_send_batch_to(request, surface: str, pk: int):
    """ENVOYER LE LOT VERS — le résolveur d'`api_envoyer_vers`, pour la card MÈRE (2026-10-14).

    Mêmes trois pièces, aucune nouvelle : les sorties de CHAQUE élément du lot
    (`send_to.batch_outputs`), les destinations dérivées (`send_to.destinations`), et l'endpoint
    qui reçoit (`filemanager:api_import`). Les fichiers partent dans UNE requête : l'import les
    range alors en lot chez la destination (regroupement « par arrivée »), comme une sélection
    de l'arbre de fichiers.

    En PARTIEL ANNONCÉ, comme une sélection (`destinations(partiel=True)`) : un lot peut mêler
    des formats (images et vidéos d'un imager), et chaque destination dit quels fichiers elle
    prend. Les éléments SANS résultat sont comptés (`without_output`) : le menu le dit.
    Même périmètre que l'élément : un lot que le compte VOIT (le sien ou un lot REÇU), dont
    seuls les éléments qu'il voit partent ; un lot qu'il ne voit pas rend 404.
    """
    from django.urls import reverse
    from wama.common.services.send_to import batch_outputs, destinations
    from wama.common.utils.batch_common import batch_model_for_app
    from wama.common.utils.scoping import visible_or_404

    batch_model = batch_model_for_app(surface)
    if batch_model is None:
        return JsonResponse({'error': f"{surface} n'a pas de modèle de lot"}, status=404)
    batch = visible_or_404(batch_model, request.user, pk=pk)

    paths, elements, without_output = batch_outputs(surface, batch, viewer=request.user)
    return JsonResponse({
        'ok': True, 'surface': surface, 'pk': pk, 'nature': 'lot',
        # Mêmes clés que le résolveur d'un élément : le client les lit avec le même code.
        'chemins': paths,
        'destinations': destinations(request.user, paths, partiel=True),
        'endpoint': reverse('filemanager:api_import'),
        'elements': elements,
        'without_output': without_output,
    })


@login_required
def api_result_reference(request, surface: str, nature: str, pk: int):
    """RÉSULTAT DE RÉFÉRENCE d'un élément ou d'un lot — le port `reference_result`.

    GET  → la référence posée et la mesure (élément : sa mesure ; lot : la comparaison des
           modèles, `result_evaluation.batch_evaluation`).
    POST → `file` : pose la référence (sur le lot = sur TOUS ses éléments, un seul fichier) ;
           `action=remove` : la retire.

    Même forme que `api_partage` (surface de `PreviewRegistry`, `nature` ∈ {element, lot},
    périmètre de l'utilisateur → 404 sur un pk étranger), parce que c'est le même besoin :
    un geste sur un élément OU sur un lot, que la card et la card mère portent pareil.
    Une surface qui n'a pas déclaré son évaluation (`register_evaluation`) rend 404 : on ne
    reçoit pas une référence que rien ne saurait lire.
    """
    from django.shortcuts import get_object_or_404
    from wama.common.services import result_evaluation as evaluation
    from wama.common.utils.batch_common import batch_elements, batch_model_for_app
    from wama.common.utils.preview_registry import PreviewRegistry

    if nature not in ('element', 'lot'):
        return JsonResponse({'error': f"nature inconnue : {nature}"}, status=404)
    if evaluation.evaluation_spec(surface) is None:
        return JsonResponse({'error': f"{surface} n'évalue pas ses résultats"}, status=404)
    element_model = PreviewRegistry.get_model(surface)
    if element_model is None:
        return JsonResponse({'error': f"surface inconnue : {surface}"}, status=404)

    if nature == 'lot':
        batch_model = batch_model_for_app(surface)
        if batch_model is None:
            return JsonResponse({'error': f"{surface} n'a pas de modèle de lot"}, status=404)
        batch = get_object_or_404(batch_model, pk=pk, user=request.user)
        targets = list(batch_elements(batch, element_model))
    else:
        targets = [get_object_or_404(element_model, pk=pk, user=request.user)]

    def state():
        if nature == 'lot':
            return {'batch': evaluation.batch_evaluation(surface, targets)}
        return {'item': evaluation.item_evaluation(surface, targets[0])}

    if request.method == 'GET':
        return JsonResponse({'ok': True, 'surface': surface, 'nature': nature, 'pk': pk,
                             **state()})
    if request.method != 'POST':
        return JsonResponse({'error': 'méthode non autorisée'}, status=405)

    # `request.POST`/`FILES`, jamais `request.body` (multipart consommé par le middleware CSRF).
    if request.POST.get('action') == 'remove':
        removed = evaluation.detach_reference(surface, targets)
        return JsonResponse({'ok': True, 'removed': removed, **state()})
    uploaded = request.FILES.get('file')
    if uploaded is None:
        return JsonResponse({'ok': False, 'reason': 'aucun fichier reçu'}, status=400)
    try:
        report = evaluation.attach_reference(surface, targets, uploaded)
    except evaluation.ReferenceRefused as refusal:
        return JsonResponse({'ok': False, 'reason': str(refusal)}, status=400)
    return JsonResponse({'ok': True, **report, **state()})


@login_required
def api_result_import(request, surface: str, pk: int):
    """RÉSULTAT EXISTANT d'un élément — le port `work_result` : un résultat produit AILLEURS
    (autre outil, version antérieure) qui tient lieu de traitement.

    POST `file` : l'app en fait le résultat de l'élément (`import_result` déclaré), puis il est
    mesuré s'il porte une référence ; `action=remove` : retire le fichier (le résultat reste
    jusqu'à la prochaine relance). Un ÉLÉMENT seulement — un résultat appartient à une entrée.
    Même garde que `api_result_reference` : 404 hors surface qui le déclare, ou pk étranger.
    """
    from django.shortcuts import get_object_or_404
    from wama.common.services import result_evaluation as evaluation
    from wama.common.utils.preview_registry import PreviewRegistry

    spec = evaluation.evaluation_spec(surface)
    if spec is None or spec.import_result is None:
        return JsonResponse({'error': f"{surface} ne reprend pas de résultat existant"}, status=404)
    element_model = PreviewRegistry.get_model(surface)
    if element_model is None:
        return JsonResponse({'error': f"surface inconnue : {surface}"}, status=404)
    item = get_object_or_404(element_model, pk=pk, user=request.user)
    if request.method != 'POST':
        return JsonResponse({'error': 'méthode non autorisée'}, status=405)

    if request.POST.get('action') == 'remove':
        return JsonResponse({'ok': True, 'removed': evaluation.detach_result(surface, item)})
    uploaded = request.FILES.get('file')
    if uploaded is None:
        return JsonResponse({'ok': False, 'reason': 'aucun fichier reçu'}, status=400)
    try:
        report = evaluation.attach_result(surface, item, uploaded)
    except evaluation.ReferenceRefused as refusal:
        return JsonResponse({'ok': False, 'reason': str(refusal)}, status=400)
    return JsonResponse({'ok': True, **report, 'item': evaluation.item_evaluation(surface, item)})


@login_required
def api_item_for_path(request):
    """L'ÉLÉMENT dont un fichier de `media/` est la SORTIE — pour le menu de l'arbre (2026-09-18).

    GET `?path=<relatif à MEDIA_ROOT>` → `{ok, surface, pk}` ; `surface` et `pk` sont `null`
    quand le fichier n'est la sortie déclarée d'aucun élément de l'utilisateur (dépôt
    temporaire, entrée d'app, montage). Lecture seule : les gestes eux-mêmes (partage,
    médiathèque, RAG) passent ensuite par LEURS endpoints, ceux que le menu d'une card appelle
    déjà — ce résolveur ne fait que rendre les coordonnées qu'une card porte dans son HTML.

    La garde de CHEMIN est celle de l'import (`is_path_allowed`), pas une copie — même règle
    que `api_envoyer_vers_chemins`.
    """
    from wama.common.services.send_to import item_for_output_path
    from wama.filemanager.views import is_path_allowed

    chemin = (request.GET.get('path') or '').replace('\\', '/').lstrip('/')
    if not chemin:
        return JsonResponse({'error': 'Aucun chemin fourni'}, status=400)
    if not is_path_allowed(chemin, request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    surface, element = item_for_output_path(request.user, chemin)
    return JsonResponse({'ok': True, 'path': chemin, 'surface': surface,
                         'pk': element.pk if element is not None else None})


@login_required
def api_media_probe(request):
    """Les PROPRIÉTÉS d'un fichier DÉSIGNÉ (durée, codec…) — pour une card qui en dérive un
    réglage avant de créer quoi que ce soit (2026-10-04 : la durée du composer reprend celle de
    la chanson à reprendre). Un fichier téléversé se lit chez le client ; un fichier désigné
    (médiathèque, arbre) n'a que son chemin — d'où cette sonde.

    GET `?path=<relatif à MEDIA_ROOT>` → `{ok, media_type, duration, duration_display,
    properties}`. Garde = celle de la DÉSIGNATION (`media_paths.designate` : confinement puis
    `readable_by`) : on ne sonde que ce que l'utilisateur pourrait désigner. Sonde mise en cache
    par fichier (`probe_media_cached`)."""
    from wama.common.utils.media_paths import (OutsideMediaRoot, readable_by,
                                               resolve_under_media_root)
    from wama.common.utils.media_probe import probe_media_cached

    try:
        abs_path, rel = resolve_under_media_root(request.GET.get('path') or '')
    except (OutsideMediaRoot, FileNotFoundError, ValueError):
        return JsonResponse({'error': 'Fichier introuvable'}, status=404)
    if not readable_by(rel, request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    info = probe_media_cached(abs_path)
    return JsonResponse({'ok': True, **{k: info.get(k) for k in (
        'media_type', 'duration', 'duration_display', 'properties')}})


@login_required
def api_envoyer_vers_chemins(request):
    """ENVOYER VERS depuis le GESTIONNAIRE DE FICHIERS — le MÊME résolveur, entré par des CHEMINS.

    Unifié le 2026-09-14 (demande de Fabien). L'arbre calculait ses destinations CHEZ LE CLIENT
    (`WAMA_APP_CATALOG` × `WAMA_FILEMANAGER_IMPORTERS`) quand la card les demandait AU SERVEUR :
    deux dérivations des mêmes conditions, qui divergeaient déjà — l'arbre ne vérifiait pas
    l'ACCÈS à l'app. Une seule source désormais : `send_to.destinations`.

    POST, corps JSON : `{"paths": [...]}` (un fichier ou une sélection) ou `{"folder": "..."}`
    (dossier entier). Lecture seule — l'envoi reste `filemanager:api_import`, rendu en `endpoint`.
    """
    import json

    from django.urls import reverse
    from wama.common.services.send_to import destinations, destinations_dossier
    from wama.filemanager.views import is_path_allowed

    if request.method != 'POST':
        return JsonResponse({'error': 'POST attendu'}, status=405)
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    endpoint = reverse('filemanager:api_import')

    # La garde de CHEMIN est celle de l'import, pas une copie : un chemin que l'import refuserait
    # n'obtient pas non plus de menu (même mot, même porte).
    dossier = (data.get('folder') or '').strip() if isinstance(data, dict) else ''
    if dossier:
        if not is_path_allowed(dossier, request.user):
            return JsonResponse({'error': 'Access denied'}, status=403)
        return JsonResponse({'ok': True, 'folder': dossier, 'chemins': [],
                             'destinations': destinations_dossier(request.user),
                             'endpoint': endpoint})

    chemins = [c for c in (data.get('paths') or []) if isinstance(c, str) and c] \
        if isinstance(data, dict) else []
    if not chemins:
        return JsonResponse({'error': 'Aucun chemin fourni'}, status=400)
    if not all(is_path_allowed(c, request.user) for c in chemins):
        return JsonResponse({'error': 'Access denied'}, status=403)
    return JsonResponse({'ok': True, 'chemins': chemins,
                         'destinations': destinations(request.user, chemins,
                                                      partiel=len(chemins) > 1),
                         'endpoint': endpoint})
