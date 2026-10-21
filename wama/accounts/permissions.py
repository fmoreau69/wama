"""
Modèle d'accès WAMA à DEUX AXES (voir PROFILES_PERMISSIONS.md) :
  - PROFIL DE COMPTE (tier, unique, hiérarchique) : anonymous < utilisateur < developpeur < admin.
  - RÔLES MÉTIER (cumulatifs, = Django Groups préfixés 'role:') : communication / recherche / …

Le mapping app→rôles est **DB-backed et éditable** (modèle AppAccessPolicy, géré dans l'interface
utilisateurs). DEFAULT_APP_ACCESS ne sert que de **valeurs de seed**. Toute la résolution passe par
`accessible()` — point unique appliqué dans la nav, les vues et le studio.

Depuis S2 (2026-08-27) sa signature est GÉNÉRALE : `accessible(user, kind, element_id)`, où
`kind` désigne la FAMILLE d'élément (§8.2). Une seule famille est réellement gardée aujourd'hui
(`app`) ; les autres sont déclarées dans `KIND_DECISION` avec le mécanisme qui en décide. C'est
l'appelant qu'on ne veut pas réécrire deux fois : S3 branchera `AccessGrant` derrière cette même
signature sans toucher un seul site d'appel.

⚠️ Ce module ne doit PAS importer accounts.models au niveau module (cycle) — imports paresseux.
"""

# ── Profils de compte (tier) ───────────────────────────────────────────────
TIER_ORDER = ['anonymous', 'utilisateur', 'developpeur', 'admin']
TIER_CHOICES = [
    ('anonymous', 'Anonyme'),
    ('utilisateur', 'Utilisateur'),
    ('developpeur', 'Développeur'),
    ('admin', 'Admin'),
]
BYPASS_TIERS = {'developpeur', 'admin'}   # voient toutes les apps (gating d'apps contourné)

# ── Nature d'un compte (2026-10-01, demande de Fabien) ──────────────────────
#: Un compte qui n'est PAS une personne porte ce préfixe : tests nocturnes, smoke, droits,
#: évaluation. C'est le NOM qui le dit — un compte créé `wama_…` depuis la page rejoint seul la
#: section des comptes de test. ⚠ Ne pas confondre avec l'EXCLUSION des statistiques apprises
#: (`nightly_tests.TEST_USERNAMES`) : le compte d'évaluation est un compte de test au sens de
#: cette section, mais il NOURRIT l'ETA (décision de Fabien du 30/09). Tout compte exclu porte le
#: préfixe (garde `tests_account_kinds`), l'inverse n'est pas vrai.
TEST_ACCOUNT_PREFIX = 'wama_'
ANONYMOUS_USERNAME = 'anonymous'
ACCOUNT_KINDS = {
    'person': 'Utilisateurs',
    'test': 'Comptes de test et système',
}


#: Préfixe des identités de VISITEUR (2026-10-04, `accounts/visitors.py`) : un compte technique
#: par session de visiteur, créé à son premier geste sur une app publique et détruit avec ses
#: fichiers à l'expiration. Il porte le préfixe des comptes de test et système (`wama_`).
VISITOR_ACCOUNT_PREFIX = 'wama_visitor_'


def is_guest_account(user) -> bool:
    """Ce compte est-il un compte de SERVICE pour visiteur non connecté — le compte `anonymous`
    partagé, ou l'identité éphémère d'une session ? Ce n'est pas une personne : il ne voit et ne
    liste que ce qu'il possède (`scoping.listable_by`), et rien ne se partage avec lui.

    Domicile UNIQUE du prédicat : il était écrit `username == 'anonymous'` en plusieurs endroits,
    ce qui aurait laissé une identité de visiteur hériter des éléments publics de tout le parc."""
    username = getattr(user, 'username', '') or ''
    return username == ANONYMOUS_USERNAME or username.startswith(VISITOR_ACCOUNT_PREFIX)


def account_kind(user) -> str:
    """'test' pour un compte de test (préfixe `wama_`) ou le compte système anonyme, 'person'
    sinon — c'est la section de la page de gestion des utilisateurs."""
    username = getattr(user, 'username', '') or ''
    if username.startswith(TEST_ACCOUNT_PREFIX) or username == ANONYMOUS_USERNAME:
        return 'test'
    return 'person'

# ── Rôles métier ───────────────────────────────────────────────────────────
ROLES = {
    'communication': 'Communication',
    'recherche': 'Recherche',
    'ingenierie': 'Ingénierie',
    'administratif': 'Administratif',
}
ROLE_DESCRIPTIONS = {
    'communication': "Production de médias : génération d'images/vidéos/audio, montage, voix, avatars.",
    'recherche': "Analyse et connaissance : transcription, description, lecture de documents, anonymisation.",
    'ingenierie': "Outils techniques : gestion des modèles IA, conversion, analyse vidéo (lab).",
    'administratif': "Gestion documentaire, exports et anonymisation à des fins administratives.",
}
GROUP_PREFIX = 'role:'   # un rôle = un Group nommé 'role:<clé>'

# ── Valeurs de SEED du mapping app→accès (éditable ensuite en base) ─────────
# {app_id: {'roles': [...], 'public': bool, 'min_tier': str|None}}
# roles vide = app COMMUNE (tout compte authentifié). Apps hors APP_CATALOG (infra) tolérées.
DEFAULT_APP_ACCESS = {
    # Apps génératives / production
    'imager':       {'roles': ['communication']},
    'composer':     {'roles': ['communication']},
    'synthesizer':  {'roles': ['communication']},
    'avatarizer':   {'roles': ['communication']},
    'enhancer':     {'roles': ['communication']},
    'anonymizer':   {'roles': ['communication', 'recherche', 'administratif']},
    # Apps d'analyse / recherche
    'transcriber':  {'roles': ['recherche']},
    'describer':    {'roles': ['recherche']},
    'reader':       {'roles': ['recherche']},
    # Utilitaires / communs (aucun rôle = ouvert à tout compte authentifié)
    # `public` : l'app d'ESSAI du visiteur sans compte (décision de Fabien du 2026-08-30,
    # ouverte le 2026-10-04 avec une persistance PAR SESSION — `accounts/visitors.py`). C'est la
    # seule : conversion par ffmpeg/pandoc, aucune ressource GPU.
    'converter':    {'roles': [], 'public': True},
    'media_library': {'roles': []},
    # Registres : entrés dans la politique le 2026-10-13 (décision de Fabien) — ils n'avaient
    # AUCUNE garde. Le model manager en est un (le registre des modèles) : ses pages se LISENT
    # sous ce droit. Lire : tout compte, jamais le visiteur, lecture comprise
    # (`middleware.VISITOR_CLOSED`). GÉRER — actualiser un registre, installer, supprimer,
    # prospecter, libérer la carte — : à partir du profil développeur (`can_manage_registries`),
    # une seule règle pour tous les registres. Il n'y a donc plus de droit `model_manager` : il
    # mêlait les deux (2026-10-13).
    'registries':   {'roles': []},
    # Outils SANS PAGE (2026-10-13, décision de Fabien) : un volet ou une conversation, pas une
    # page du catalogue `/apps/`. Déclarés par `app_registry.register_pageless_tool` (monde,
    # libellé, sonde) ; leurs routes se résolvent comme toute app (1er segment, sinon
    # `PATH_APP_MAP`). Tout compte, jamais le visiteur.
    'filemanager':  {'roles': []},
    'assistant':    {'roles': []},
    # Orchestration (méta-app)
    'studio':       {'roles': ['communication', 'ingenierie']},
    # WAMA-Lab (expérimental / recherche — accès restreint)
    'face_analyzer': {'roles': ['recherche', 'ingenierie']},
    'cam_analyzer':  {'roles': ['recherche', 'ingenierie']},
}

# ── Familles d'éléments gardés (§8.2) ──────────────────────────────────────
# `accessible()` prend un `kind` dès maintenant, alors qu'une seule famille est gardée. Ce n'est
# pas de l'anticipation gratuite : c'est la SIGNATURE des ~14 sites d'appel qu'on ne veut pas
# réécrire une seconde fois quand S3 ouvrira les autres familles.
#
# 🔴 Chaque famille déclare QUI décide pour elle. Une famille qu'aucun mécanisme ne garde le dit
# ('S3'), au lieu de renvoyer True par accident. Et un `kind` ABSENT de cette table LÈVE : un
# `accessible(u, 'aap', x)` mal orthographié qui autoriserait silencieusement serait exactement
# la panne muette que le dépôt traque (cf. feedback « ce qui ne plante pas ne se signale pas »).
KIND_DECISION = {
    'app':       'ici',                # DEFAULT_APP_ACCESS / AppAccessPolicy — `_app_accessible()`
    # À QUI c'est : la ligne de son registre (`ROADMAP §29` étape 3, `_provenance_accessible`).
    # « Qui a le DROIT » (criticité dérivée — vram_gb, licence — + AccessGrant, §8.3) viendra
    # s'y AJOUTER avec S3, sans remplacer la provenance.
    'model':     'provenance',
    'library':   'S3',
    # Étape 4 : la ligne d'une fonction d'UTILISATEUR, ou l'app qui porte une fonction du CODE.
    'function':  'provenance',
    # 2026-10-20 (piste 2 de Fabien) : la ligne `PromptSkill` d'un auteur, ou le fichier système.
    'skill':     'provenance',
    'rag_scope': 'ScopedVisibility',   # gardé AILLEURS (portée héritée) — ne PAS dupliquer ici
}

# Regroupement des apps pour l'affichage (matrice d'accès). Ordre = ordre des sections.
APP_GROUP_ORDER = ['Production', 'Recherche / Analyse', 'Utilitaires', 'Orchestration',
                   'Technique', 'WAMA Lab']
APP_GROUP = {
    'imager': 'Production', 'composer': 'Production', 'synthesizer': 'Production',
    'avatarizer': 'Production', 'enhancer': 'Production', 'anonymizer': 'Production',
    'transcriber': 'Recherche / Analyse', 'describer': 'Recherche / Analyse', 'reader': 'Recherche / Analyse',
    'converter': 'Utilitaires', 'media_library': 'Utilitaires',
    'studio': 'Orchestration',
    'registries': 'Technique', 'filemanager': 'Utilitaires', 'assistant': 'Utilitaires',
    'face_analyzer': 'WAMA Lab', 'cam_analyzer': 'WAMA Lab',
}


def app_group(app_id):
    return APP_GROUP.get(app_id, 'Autres')


# ── Bac à sable (route §10.3 marche S) : jumelles DEV-ONLY, groupe dédié ─────────────────
try:
    from wama.common.sandbox import inject_sandbox_access
    inject_sandbox_access(DEFAULT_APP_ACCESS, APP_GROUP)
except Exception:
    pass


# Résolution URL → app_id pour les apps dont le préfixe d'URL diffère de l'app_id
# (le middleware gate aussi ces chemins). Le 1er match de préfixe gagne.
PATH_APP_MAP = [
    ('lab/face-analyzer', 'face_analyzer'),
    ('lab/cam-analyzer',  'cam_analyzer'),
    ('media-library',     'media_library'),
    # ⚠ Ajouté le 27/08 (S2, mesure « qui contourne `accessible()` »). `model_manager` était
    # déclaré dans DEFAULT_APP_ACCESS (rôle ingenierie, min_tier developpeur) mais monté sur
    # `/model-manager/` : le 1er segment ne résolvait AUCUN app_id, donc le middleware ne lui
    # appliquait JAMAIS sa propre politique. Une politique déclarée qu'aucun point d'application
    # ne lit ne garde rien — elle donne juste l'apparence d'un contrôle. Le piège du tiret était
    # connu (`wama/urls.py:57`, audit P2 du 17/08) : il avait été documenté, pas refermé.
    # Depuis le 2026-10-13, le model manager est une page des REGISTRES : il se lit sous leur
    # droit ; ses gestes restent aux développeurs (`model_manager.views.is_admin_or_dev`).
    ('model-manager',     'registries'),
    # La page des registres et son API d'état/actualisation vivent sous `/common/` (2026-10-13).
    ('common/registries',   'registries'),
    ('common/registres',    'registries'),
    ('common/api/registres', 'registries'),
    # L'assistant, outil SANS PAGE (2026-10-13, `app_registry.register_pageless_tool`) : ses
    # routes web. Le gestionnaire de fichiers, autre outil sans page, se résout par son 1er
    # segment (`/filemanager/`), comme toute app.
    ('api/ai-chat',       'assistant'),
    # 'studio' est désormais une vraie app montée sur /studio/ → résolu par le 1er segment.
]


# ── Services du SUBSTRAT logés sous le préfixe d'une app ────────────────────────────────
#
# Une app peut héberger des routes qui ne LUI appartiennent pas : le catalogue de modèles est
# monté sous `/model-manager/`, mais l'UI de SIX apps en dépend (descriptif sous le select,
# filtrage voix/langues, options tirées du catalogue — briques communes `wama-model-help.js`,
# `wama-model-caps.js`, `wama-params.js`). Les gater comme des pages du model_manager rendait
# ces mécanismes MUETS pour tout utilisateur n'ayant pas droit à cette app — c'est-à-dire pour
# tout le monde sauf les admins.
#
# ⚠ Mesuré le 2026-09-01 avant d'écrire cette exemption, et c'est ce qui la rend SÛRE : sur les
# **53 routes API** du model_manager, **zéro route mutante ne tient par la seule garde d'app** —
# installation, suppression, prospection, sauvegarde, nettoyage GPU portent TOUTES leur propre
# `is_admin_or_dev`. Exempter le préfixe API ne change donc l'accès effectif que des deux seules
# routes en « login seul », qui sont précisément les deux lectures du catalogue.
#
# 🔴 Le critère n'est PAS « c'est une API » — ce serait ouvrir les API des autres apps, dont la
# garde d'app est la seule protection. Le critère est : *cette route sert-elle l'UI d'AUTRES
# apps ?* Une entrée ici se justifie par ce test, et par l'audit des gardes propres ci-dessus.
#
# Décision de Fabien (2026-09-01) : « seul l'accès au TEMPLATE doit être restreint, pas le
# fonctionnement du model manager ». Un cadrillage complet des permissions reste à faire — la
# construction est là, les règles ne sont pas abouties.
ROUTES_SUBSTRAT = (
    'model-manager/api',
)


def app_id_for_path(path):
    """app_id gardé correspondant à un chemin de requête, ou None.

    `None` signifie « ce chemin n'est pas gardé par l'accès à une app » — ce qui vaut pour un
    chemin hors app comme pour un service du substrat logé sous le préfixe d'une app
    (cf. `ROUTES_SUBSTRAT`).
    """
    p = path.strip('/')
    for prefix in ROUTES_SUBSTRAT:
        if p == prefix or p.startswith(prefix + '/'):
            return None
    for prefix, app_id in PATH_APP_MAP:
        if p == prefix or p.startswith(prefix + '/'):
            return app_id
    seg = p.split('/', 1)[0]
    return seg if seg in DEFAULT_APP_ACCESS else None


def refused_app(user, path, allowed_apps=None):
    """L'app gardée que `path` désigne et que `user` (connecté) n'a PAS le droit d'ouvrir, sinon
    None. Ce que `AppAccessMiddleware` refuse à un compte, dit une fois pour lui et pour
    l'assistant (`can_open_page`). `allowed_apps` : la lecture groupée `accessible_apps` déjà
    faite par l'appelant (le menu) — même décision, sans une requête par page."""
    app_id = app_id_for_path(path)
    if not app_id:
        return None
    allowed = (app_id in allowed_apps) if allowed_apps is not None else accessible(user, 'app', app_id)
    return None if allowed else app_id


def can_open_page(user, access, path, allowed_apps=None) -> bool:
    """`user` peut-il ouvrir la page servie à `path` ? La MÊME décision que la requête réelle,
    dans l'ordre où elle est prise (2026-10-14, pages du compte) :
      1. le middleware d'accès — chemin fermé au visiteur (`middleware.visitor_refusal`), puis,
         pour un compte, la politique de l'app du chemin (`refused_app`) ;
      2. le décorateur de la vue, que la page DÉCLARE (`app_registry.ACCOUNT_PAGE_ACCESS`) :
         `public`, `account` (`login_required`), `admin` (`accounts.views.is_admin`, le
         prédicat de `admin_required`).
    Une page peut montrer moins selon le rôle (la documentation, les sources) : c'est la page
    qui filtre, l'ouvrir reste permis. `tests_account_pages` confronte cette décision à la
    réponse de chaque vue déclarée."""
    from wama.accounts.middleware import visitor_refusal
    authenticated = bool(user is not None and getattr(user, 'is_authenticated', False))
    if visitor_refusal(user, path):
        return False
    if authenticated and refused_app(user, path, allowed_apps):
        return False
    if access == 'public':
        return True
    if access == 'account':
        return authenticated
    if access == 'admin':
        from wama.accounts.views import is_admin
        return authenticated and is_admin(user)
    raise ValueError(f"accès de page inconnu : {access!r}")


def tool_accessible(user, tool_name):
    """
    Un user peut-il exécuter cet outil `tool_api` ? MÊME décision que `accessible()` : la
    surface outils (assistant IA, API REST v1, runner studio) est gardée comme la navigation.

    Sans ce point d'application, un token d'API contourne intégralement tier + rôles : les
    vues d'app sont gardées par AppAccessMiddleware, mais `/api/v1/tools/run/` ne l'est pas
    (`app_id_for_path('/api/v1/…')` → None, et l'auth DRF par token arrive APRÈS le middleware).

    Outil transverse (app None) → autorisé : l'ownership reste porté par `tool_api` (filtres
    `user=user` sur les querysets), qui est une garantie orthogonale au gating d'app.

    La correspondance outil→app vit dans `tool_api` (le pivot possède sa convention de
    nommage) ; ce module ne garde que la DÉCISION.
    """
    from wama.tool_api import app_id_for_tool
    app_id = app_id_for_tool(tool_name)
    return True if app_id is None else accessible(user, 'app', app_id)


# ── LE RÔLE DU COMPTE : UNE source, le NIVEAU du profil (décision de Fabien, 2026-10-21) ─────────
# Trois sources décidaient d'« administrateur » ou de « développeur » : le niveau du profil
# (`UserProfile.account_tier`), les drapeaux Django (`is_superuser`, `is_staff`) et les groupes
# hérités `admin` / `dev` / `user` de la migration `accounts/0002`. Rien ne les tenait d'accord
# (mesuré : un compte du groupe `dev` au niveau « utilisateur », deux développeurs sans groupe).
# Désormais :
#   • le NIVEAU décide, lu par `user_tier` (un superutilisateur y est compté administrateur : un
#     compte créé par `createsuperuser` n'a pas encore de profil) ;
#   • les DRAPEAUX en sont la conséquence, posés par le seul écrivain du niveau
#     (`set_account_tier` : administrateur ⇒ `is_staff` + `is_superuser`, sinon ni l'un ni
#     l'autre) — ils n'ouvrent plus que le site d'administration Django, rien dans WAMA ;
#   • les groupes `admin` / `dev` / `user` sont retirés (`manage.py align_account_tiers`) ; ils
#     ne portaient aucune permission. Les rôles MÉTIER `role:*` (axe B) ne sont pas concernés.
# Deux prédicats, deux gestes : `is_admin_tier` (valider, modérer, gérer les comptes) et
# `is_developer` (gérer les registres, les outils de développement).


def can_manage_registries(user):
    """GÉRER un registre — l'actualiser, et pour le registre des modèles : installer, supprimer,
    prospecter, libérer la carte. DOMICILE UNIQUE (2026-10-13, décision de Fabien : le model
    manager est un registre, aligné sur les autres). Les LIRE relève du droit d'accès `registries`.

    Le PROFIL décide (développeur ou administrateur, superutilisateur compris), jamais les
    Groups hérités 'dev'/'admin' de la migration `accounts/0002` : c'était le second barème
    retiré du model manager le 27/08 (`tests_access_points.ModelManagerGardeUniqueTests`).
    Même décision que `is_developer` depuis le 2026-10-21 : ce nom dit le GESTE gardé.
    """
    return is_developer(user)


def is_developer(user):
    """
    Développeur ou administrateur — DOMICILE UNIQUE du prédicat (2026-09-15).

    Le NIVEAU du profil seul décide (`BYPASS_TIERS`, lu par `user_tier`, superutilisateur
    compris) — décision de Fabien du 2026-10-21. Il réunissait jusque-là le niveau et les GROUPES
    Django `dev` / `admin` / `developpeur`, qui sont retirés (`align_account_tiers`).
    Consommateurs : l'abonnement Claude Code (`claude_code.subscription_allowed`), les outils MCP
    de développement (`common/services/dev_tools.py`), la gestion des registres.

    ⚠ DÉFAUT CORRIGÉ en l'extrayant de `subscription_allowed` : sa branche tier lisait
    `profile.tier`, un attribut qui N'EXISTE PAS — le champ est `account_tier`
    (`accounts/models.py:116`). Un compte promu développeur PAR SON TIER, sans groupe, était donc
    refusé en silence, et aucun test ne le voyait : ils ne construisaient que des groupes.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    return user_tier(user) in BYPASS_TIERS


def all_gated_apps():
    """Ensemble des app_ids soumis au contrôle d'accès (pour calculer accessible_apps)."""
    return set(DEFAULT_APP_ACCESS.keys())


def tier_rank(tier):
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def user_tier(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return 'anonymous'
    if getattr(user, 'is_superuser', False):
        return 'admin'
    prof = getattr(user, 'profile', None)
    return getattr(prof, 'account_tier', 'utilisateur') or 'utilisateur'


def is_admin_tier(user):
    """Le compte est-il ADMINISTRATEUR ? Le NIVEAU du profil, superutilisateur compris.

    LA définition de WAMA depuis le 2026-10-21 (décision de Fabien). Les trois définitions qui
    coexistaient (groupe `admin`, drapeau `is_staff`, niveau) n'en font plus qu'une : les vues de
    gestion des comptes, la modération, la validation, la promotion, les contournements « admin »
    et les registres réservés lisent ce prédicat."""
    return user_tier(user) == 'admin'


def administrators() -> list:
    """Les comptes ACTIFS administrateurs, ceux qu'on prévient d'une demande à trancher.

    Eux seuls la tranchent (un compte à valider, une promotion). Une lecture, pour toutes les
    demandes."""
    from django.contrib.auth import get_user_model
    return [u for u in get_user_model().objects.filter(is_active=True).select_related('profile')
            if is_admin_tier(u)]


def set_account_tier(user, tier: str):
    """Le SEUL écrivain du niveau d'un compte, drapeaux Django compris ; rend le niveau posé.

    Pose le profil, puis les drapeaux qui en découlent (administrateur ⇒ `is_staff` +
    `is_superuser`, sinon ni l'un ni l'autre) — ils n'ouvrent que le site d'administration
    Django."""
    from .models import UserProfile
    if tier not in dict(TIER_CHOICES):
        raise ValueError(f"niveau inconnu : {tier!r}")
    # Le profil DÉJÀ chargé sur le compte, s'il l'est : l'objet que tient l'appelant suit alors
    # le niveau posé (une copie relue à part le laisserait sur l'ancien).
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    if profile.account_tier != tier:
        profile.account_tier = tier
        profile.save(update_fields=['account_tier'])
    admin = tier == 'admin'
    if (user.is_staff, user.is_superuser) != (admin, admin):
        user.is_staff = user.is_superuser = admin
        user.save(update_fields=['is_staff', 'is_superuser'])
    return tier


def user_roles(user):
    """Ensemble des clés de rôles métier d'un user (depuis ses Groups 'role:*')."""
    if not user or not getattr(user, 'is_authenticated', False):
        return set()
    out = set()
    for g in user.groups.all():
        if g.name.startswith(GROUP_PREFIX):
            out.add(g.name[len(GROUP_PREFIX):])
    return out


def _all_policies():
    """Toutes les politiques en base, {app_id: AppAccessPolicy} — DEUX requêtes pour une liste
    d'apps, au lieu de deux PAR app (le menu en évaluait 26 par page, 2026-10-02). None si la
    base ne répond pas : chaque app retombe alors sur sa lecture unitaire."""
    try:
        from wama.accounts.models import AppAccessPolicy
        return {p.app_id: p for p in AppAccessPolicy.objects.prefetch_related('roles')}
    except Exception:
        return None


def _policy_for(app_id, policies=None):
    """Politique effective d'une app : DB (AppAccessPolicy) sinon DEFAULT_APP_ACCESS sinon commune.
    `policies` : lecture groupée (`_all_policies`) déjà faite par l'appelant."""
    if policies is not None:
        p = policies.get(app_id)
    else:
        try:
            from wama.accounts.models import AppAccessPolicy
            p = AppAccessPolicy.objects.filter(app_id=app_id).prefetch_related('roles').first()
        except Exception:
            p = None
    if p is not None:
        return {
            'roles': {g.name[len(GROUP_PREFIX):] for g in p.roles.all() if g.name.startswith(GROUP_PREFIX)},
            'public': p.public,
            'min_tier': p.min_tier or None,
        }
    d = DEFAULT_APP_ACCESS.get(app_id, {})
    return {'roles': set(d.get('roles', [])), 'public': d.get('public', False), 'min_tier': d.get('min_tier')}


def accessible(user, kind, element_id):
    """
    Un user peut-il accéder à cet élément ? Point UNIQUE de décision (nav, vues, studio, outils).

    `kind` ∈ `KIND_DECISION` (app | model | library | function | skill | rag_scope). La famille
    `app` se décide ici par sa politique ; une famille « provenance » (`model`, `function`,
    `skill`) par la
    portée de l'élément sur la ligne de son registre, ou par l'app qui déclare un élément du
    code ; les autres déclarent leur mécanisme et renvoient
    True. Un `kind` inconnu LÈVE — cf. le commentaire de `KIND_DECISION`.
    """
    decideur = KIND_DECISION.get(kind)
    if decideur is None:
        raise ValueError(
            f"accessible() : famille d'élément inconnue « {kind} ». "
            f"Familles déclarées : {', '.join(sorted(KIND_DECISION))}. "
            f"(Signature depuis S2 : accessible(user, kind, element_id).)"
        )
    if decideur == 'provenance':
        return _provenance_accessible(user, kind, element_id)
    if decideur != 'ici':
        return True
    return _app_accessible(user, element_id)


def _provenance_accessible(user, kind, element_id):
    """L'élément est-il VISIBLE de `user` ? Lu sur la ligne qui le porte, celle que son registre
    déclare (`owner_model`, nommée par `owner_key`), avec le filtre commun des catalogues
    (`catalogue_visible_q` : système, publics, les siens, sa portée ; tout pour l'admin).

    Un élément SANS ligne est du code : il n'a pas d'auteur à lui, il suit l'app qui le déclare
    (`Registry.element_app` — système dans une app réelle, à son créateur dans une jumelle), et
    rien ne le restreint quand le registre n'en nomme aucune. Un élément privé d'utilisateur a
    toujours sa ligne, puisque c'est elle qui porte son auteur."""
    from wama.common.models import catalogue_visible_q
    from wama.common.registries import carried_rows, declared_in_code, declaring_app
    rows = carried_rows(element_id, access_kind=kind)
    if rows is None:
        raise ValueError(f"accessible() : la famille « {kind} » se décide par la provenance, "
                         f"mais aucun registre ne nomme la ligne qui la porte")
    if rows.exists():
        if rows.filter(catalogue_visible_q(user, model=rows.model)).exists():
            return True
        # Le skill privé d'un autre compte porte le nom du fichier système qu'il remplace pour
        # son auteur : il ne retire pas ce fichier aux autres (`Registry.in_code`).
        if not declared_in_code(element_id, access_kind=kind):
            return False
    app = declaring_app(element_id, access_kind=kind)
    return not app or accessible(user, 'app', app)


def _app_accessible(user, app_id, policies=None, owners=None):
    """
    Décision pour la famille `app` :
      créateur de jumelle → min_tier → bypass dev/admin → anonymous(public) → app commune
      → intersection rôles.
    `policies` / `owners` : lectures GROUPÉES faites par `accessible_apps` (même décision).
    """
    # Jumelle de bac à sable : son CRÉATEUR y accède quel que soit son tier (décision Fabien
    # 2026-09-03 — chacun voit SES jumelles, pas celles des autres ; dev/admin voient tout
    # par la voie tier normale). Dérogation AVANT min_tier : c'est lui qui bloquerait un
    # créateur non-dev. Une jumelle sans `created_by` (CLI) reste dev/admin-only.
    try:
        if owners is not None:
            _owner = owners.get(app_id, '')
        else:
            from wama.common.sandbox import twin_owner
            _owner = twin_owner(app_id)
        if _owner and getattr(user, 'username', '') == _owner:
            return True
    except Exception:
        pass
    pol = _policy_for(app_id, policies)
    tier = user_tier(user)
    if pol['min_tier'] and tier_rank(tier) < tier_rank(pol['min_tier']):
        return False
    if tier in BYPASS_TIERS:
        return True
    if tier == 'anonymous':
        return bool(pol['public'])
    if not pol['roles']:           # app commune
        return True
    return bool(pol['roles'] & user_roles(user))


def accessible_apps(user, app_ids):
    """Sous-ensemble d'app_ids accessibles à user (préserve l'ordre).

    MÊME décision que `accessible(user, 'app', …)` app par app, mais les politiques et les
    propriétaires de jumelles se lisent UNE fois pour la liste (2026-10-02 : le menu de chaque
    page faisait 52 requêtes et 26 lectures du registre des bacs à sable)."""
    app_ids = list(app_ids)
    if KIND_DECISION.get('app') != 'ici':
        return [a for a in app_ids if accessible(user, 'app', a)]
    policies = _all_policies()
    try:
        from wama.common.sandbox import load_registry
        owners = {e.get('label'): e.get('created_by') or '' for e in load_registry()}
    except Exception:
        owners = None
    return [a for a in app_ids if _app_accessible(user, a, policies, owners)]


class _CaseUser:
    """Compte FICTIF (tier + rôles) passé à `accessible()` pour énumérer les cas d'accès.

    Il n'offre que ce que lisent `user_tier()`/`user_roles()` : décider à sa place recopierait
    `_app_accessible()`, et deux barèmes pour une même question ne restent d'accord que par chance.
    """
    is_authenticated = True
    is_superuser = False
    username = ''

    class _Groups:
        def __init__(self, names):
            self._names = names

        def all(self):
            from types import SimpleNamespace
            return [SimpleNamespace(name=n) for n in self._names]

    def __init__(self, tier, roles):
        from types import SimpleNamespace
        self.profile = SimpleNamespace(account_tier=tier)
        self.groups = self._Groups([GROUP_PREFIX + r for r in roles])


def presented_apps():
    """Les outils que MONTRENT les vues des droits (scène de la présentation, constellation des
    utilisateurs) : ceux que décide le contrôle d'accès, sans les jumelles de bac à sable —
    dev-only par contrat, elles doubleraient leur app source. Rangés par MONDE déclaré, dans
    l'ordre des sections du menu (2026-10-13), puis par groupe."""
    from wama.common.app_registry import WORLD_SECTIONS, app_world

    def world_rank(a):
        return (WORLD_SECTIONS.get(app_world(a)) or {}).get('order', 99)
    return sorted((a for a in all_gated_apps() if app_group(a) != 'Bac à sable'),
                  key=lambda a: (world_rank(a), APP_GROUP_ORDER.index(app_group(a))
                                 if app_group(a) in APP_GROUP_ORDER else 99, a))


def access_cases():
    """Tous les cas du modèle d'accès : chaque tier × chaque combinaison de rôles × chaque app.

    Décision rendue par `accessible()` sur la politique EFFECTIVE (base, sinon seed) — c'est ce
    que montre la présentation (visualisation 3D des droits). Renvoie aussi le nombre de
    comportements DISTINCTS : les tiers qui contournent le gating rendent la même ligne quelles
    que soient les rôles, si bien que les configurations se replient sur bien moins de cas réels.
    """
    from itertools import combinations
    role_keys = list(ROLES)
    role_sets = [list(c) for n in range(len(role_keys) + 1) for c in combinations(role_keys, n)]
    from wama.common.app_registry import WORLD_SECTIONS, app_identity, app_world
    apps = presented_apps()
    policies = {a: _policy_for(a) for a in apps}
    matrix, distinct = [], set()
    for tier in TIER_ORDER:
        rows = []
        for roles in role_sets:
            row = [accessible(_CaseUser(tier, roles), 'app', a) for a in apps]
            rows.append(row)
            distinct.add(tuple(row))
        matrix.append(rows)
    return {
        'tiers': [{'key': k, 'label': l} for k, l in TIER_CHOICES],
        'roles': [{'key': k, 'label': ROLES[k], 'help': ROLE_DESCRIPTIONS.get(k, '')} for k in role_keys],
        'role_sets': role_sets,
        # `label` : l'identité commune d'une app (catalogue, surface ou outil sans page).
        'apps': [{'id': a, 'label': app_identity(a)['label'], 'group': app_group(a), 'world': app_world(a),
                  'roles': sorted(policies[a]['roles']), 'public': bool(policies[a]['public']),
                  'min_tier': policies[a]['min_tier']} for a in apps],
        'matrix': matrix,
        # Libellé de chaque monde : celui des sections du menu, jamais redit côté scène.
        'worlds': {w: s['label'] for w, s in WORLD_SECTIONS.items()},
        'configurations': len(TIER_ORDER) * len(role_sets),
        'distinct_rows': len(distinct),
    }


def app_access(app_id):
    """
    Décorateur de vue (défense en profondeur, phase 2) : 403 si l'app n'est pas accessible.
      @app_access('imager')
      def index(request): ...
    À appliquer app par app APRÈS validation en conditions réelles (ne pas verrouiller en masse).
    MÊME décision que AppAccessMiddleware : les requêtes anonymes passent (le tier anonyme est
    servi via compte anonyme, comme partout dans WAMA) — les deux couches ne doivent jamais
    diverger, sinon le décorateur casse l'usage anonyme au lieu de doubler le middleware.
    """
    from functools import wraps

    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = getattr(request, 'user', None)
            if (user is not None and getattr(user, 'is_authenticated', False)
                    and not accessible(user, 'app', app_id)):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied(f"Accès non autorisé à l'app '{app_id}'.")
            return view(request, *args, **kwargs)
        return wrapped
    return deco
