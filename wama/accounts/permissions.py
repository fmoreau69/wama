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
# Descriptions de secours pour les apps hors APP_CATALOG (qui n'ont pas de meta description).
APP_DESCRIPTIONS_FALLBACK = {
    'media_library': "Médiathèque : vos assets (voix, images, audio…) et mots-clés de prompt.",
    'studio': "Studio (méta-app) : orchestration de pipelines en reliant les apps sur un canvas.",
    'face_analyzer': "WAMA-Lab : analyse de visages (recherche).",
    'cam_analyzer': "WAMA-Lab : analyse de vidéos de caméras embarquées (transport).",
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
    'converter':    {'roles': []},
    'media_library': {'roles': []},
    # Orchestration (méta-app)
    'studio':       {'roles': ['communication', 'ingenierie']},
    # Outils techniques (tier développeur requis)
    'model_manager': {'roles': ['ingenierie'], 'min_tier': 'developpeur'},
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
    'model':     'S3',                 # criticité DÉRIVÉE (vram_gb, licence) + AccessGrant (§8.3)
    'library':   'S3',
    'function':  'S3',
    'skill':     'S3',
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
    'model_manager': 'Technique',
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
    ('model-manager',     'model_manager'),
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


def user_roles(user):
    """Ensemble des clés de rôles métier d'un user (depuis ses Groups 'role:*')."""
    if not user or not getattr(user, 'is_authenticated', False):
        return set()
    out = set()
    for g in user.groups.all():
        if g.name.startswith(GROUP_PREFIX):
            out.add(g.name[len(GROUP_PREFIX):])
    return out


def _policy_for(app_id):
    """Politique effective d'une app : DB (AppAccessPolicy) sinon DEFAULT_APP_ACCESS sinon commune."""
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

    `kind` ∈ `KIND_DECISION` (app | model | library | function | skill | rag_scope). Seule la
    famille `app` est gardée ici aujourd'hui ; les autres déclarent leur mécanisme et renvoient
    True. Un `kind` inconnu LÈVE — cf. le commentaire de `KIND_DECISION`.
    """
    decideur = KIND_DECISION.get(kind)
    if decideur is None:
        raise ValueError(
            f"accessible() : famille d'élément inconnue « {kind} ». "
            f"Familles déclarées : {', '.join(sorted(KIND_DECISION))}. "
            f"(Signature depuis S2 : accessible(user, kind, element_id).)"
        )
    if decideur != 'ici':
        return True
    return _app_accessible(user, element_id)


def _app_accessible(user, app_id):
    """
    Décision pour la famille `app` :
      min_tier → bypass dev/admin → anonymous(public) → app commune → intersection rôles.
    """
    pol = _policy_for(app_id)
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
    """Sous-ensemble d'app_ids accessibles à user (préserve l'ordre)."""
    return [a for a in app_ids if accessible(user, 'app', a)]


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
