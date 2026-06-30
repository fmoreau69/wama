"""
Modèle d'accès WAMA à DEUX AXES (voir PROFILES_PERMISSIONS.md) :
  - PROFIL DE COMPTE (tier, unique, hiérarchique) : anonymous < utilisateur < developpeur < admin.
  - RÔLES MÉTIER (cumulatifs, = Django Groups préfixés 'role:') : communication / recherche / …

Le mapping app→rôles est **DB-backed et éditable** (modèle AppAccessPolicy, géré dans l'interface
utilisateurs). DEFAULT_APP_ACCESS ne sert que de **valeurs de seed**. Toute la résolution passe par
`accessible()` — point unique appliqué dans la nav, les vues et le studio.

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


# Résolution URL → app_id pour les apps dont le préfixe d'URL diffère de l'app_id
# (le middleware gate aussi ces chemins). Le 1er match de préfixe gagne.
PATH_APP_MAP = [
    ('lab/face-analyzer', 'face_analyzer'),
    ('lab/cam-analyzer',  'cam_analyzer'),
    ('media-library',     'media_library'),
    # 'studio' est désormais une vraie app montée sur /studio/ → résolu par le 1er segment.
]


def app_id_for_path(path):
    """app_id gardé correspondant à un chemin de requête, ou None."""
    p = path.strip('/')
    for prefix, app_id in PATH_APP_MAP:
        if p == prefix or p.startswith(prefix + '/'):
            return app_id
    seg = p.split('/', 1)[0]
    return seg if seg in DEFAULT_APP_ACCESS else None


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


def accessible(user, app_id):
    """
    Un user peut-il accéder à l'app ? Point UNIQUE de décision (nav, vues, studio).
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
    return [a for a in app_ids if accessible(user, a)]


def app_access(app_id):
    """
    Décorateur de vue (défense en profondeur, phase 2) : 403 si l'app n'est pas accessible.
      @app_access('imager')
      def index(request): ...
    À appliquer app par app APRÈS validation en conditions réelles (ne pas verrouiller en masse).
    """
    from functools import wraps

    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not accessible(request.user, app_id):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied(f"Accès non autorisé à l'app '{app_id}'.")
            return view(request, *args, **kwargs)
        return wrapped
    return deco
