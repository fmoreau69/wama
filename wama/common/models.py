"""
Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).

`BatchMixin` : comportement partagé des modèles « Batch » unifiés des apps de file.
C'est un **mixin Python sans champ** → aucune migration. Le modèle concret doit fournir :
  - `items`      : related_name des `BatchItem` (membres).
  - `total`      : entier maintenu par les signaux `batch_sync` (= nombre de membres).
  - `batch_file` : fichier batch partagé (optionnel).

Usage :  class BatchTranscript(BatchMixin, models.Model): ...

`ProcessingTimeMixin` : durée RÉELLE de traitement (mesurée par le worker, persistée) — modèle
ABSTRAIT (une migration additive par app concrète).
"""

from django.db import models
from pgvector.django import VectorField


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulaire de STATUT des files d'items — domicile UNIQUE
# ─────────────────────────────────────────────────────────────────────────────
#
# Les 13 modèles de file du monde MÉDIAS déclaraient chacun leur `STATUS_CHOICES`. Mesuré le
# 2026-09-01 avant de centraliser : les 13 disaient **exactement la même chose** — il n'y avait
# donc rien à réparer, seulement 13 copies à remplacer par une source. (Le critère de grille
# `status_vocab` est ce qui a tenu cette unanimité ; il atteste l'adoption, il ne signale pas
# une dérive — je l'avais lu à l'envers.)
#
# ⚠ Ce vocabulaire est celui d'une FILE D'ITEMS, pas celui de tout ce qui a un `status` :
#   • `model_manager.ModelSyncLog` (`started/completed/failed`) est un JOURNAL, pas une file ;
#   • le monde LAB (`cam_analyzer`, `face_analyzer`) a son propre cycle de vie, avec `draft`,
#     `paused`, `stale` — des états qui n'ont aucun sens pour un traitement de média.
# Les rapatrier ici écraserait des différences LÉGITIMES : une centralisation qui uniformise ce
# qui n'est pas pareil est une perte d'information, pas un gain.
#
# Valeurs INCHANGÉES (ce sont celles en base sur ~300 lignes réelles) : centraliser ne
# renomme rien et n'exige aucune migration de données.

#: États d'un item de file. `PENDING` = son tour n'est pas venu ; `RUNNING` = ça tourne.
JOB_PENDING = 'PENDING'
JOB_RUNNING = 'RUNNING'
JOB_SUCCESS = 'SUCCESS'
JOB_FAILURE = 'FAILURE'

#: Le couple (valeur, libellé) tel que les 13 apps le déclaraient. À passer en `choices=`.
JOB_STATUS_CHOICES = [
    (JOB_PENDING, 'En attente'),
    (JOB_RUNNING, 'En cours'),
    (JOB_SUCCESS, 'Terminé'),
    (JOB_FAILURE, 'Échec'),
]

#: États où l'item n'est plus en mouvement — utile aux compteurs de file et aux garde-fous.
JOB_STATUS_FINAUX = frozenset({JOB_SUCCESS, JOB_FAILURE})


class ProcessingTimeMixin(models.Model):
    """Durée RÉELLE de traitement, en secondes. Le worker la CALCULE déjà (il la passe au learner
    ETA via record_run) ; on la PERSISTE ici pour qu'elle reste affichée après rechargement
    (CARD_DESIGN §10.6 : le réel, en regard de la prédiction ETA). Généralise le
    processing_seconds/processing_display de transcriber = source unique.

    Modèle ABSTRAIT → chaque app concrète hérite le champ. Champ identique à celui de transcriber
    (default=0) → transcriber converge sans altération de colonne."""

    processing_seconds = models.FloatField(default=0)

    class Meta:
        abstract = True

    @property
    def processing_display(self) -> str:
        """Durée de traitement formatée (ex. '12 min 30 s' / '45 s'). '' si non mesurée."""
        s = int(self.processing_seconds or 0)
        if s <= 0:
            return ''
        m, sec = divmod(s, 60)
        return (f"{m} min {sec:02d} s" if m else f"{sec} s")


class BatchMixin:
    """Sémantique + cycle de fichiers communs aux modèles Batch (tout est batch ; unitaire = card unique)."""

    @property
    def is_unitary(self) -> bool:
        """True si le batch n'a qu'un seul membre → s'affiche en card unique.
        S'appuie sur `total` (maintenu exact par le signal batch_sync) → pas de requête."""
        return self.total == 1

    def cleanup_files(self) -> None:
        """Supprime le fichier batch partagé s'il n'est plus référencé. Défensif.
        Appelable aussi explicitement sur les chemins bulk (queryset.delete ne passe pas par delete())."""
        try:
            from wama.common.utils.queue_duplication import safe_delete_file
            if hasattr(self, 'batch_file'):
                safe_delete_file(self, 'batch_file')
        except Exception:
            pass

    def delete(self, *args, **kwargs):
        # Un batch nettoie son fichier partagé quand il est supprimé (quel que soit le déclencheur :
        # vue, signal de batch vidé, cascade). Centralise un nettoyage jusque-là éparpillé.
        self.cleanup_files()
        return super().delete(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Appartenance organisationnelle + visibilité par scope (MONDES / partage / RAG)
# Voir docs/WAMA_VISION_COMPLET.md §Les quatre mondes, memory/project_wama_mondes.md.
# ─────────────────────────────────────────────────────────────────────────────

# Autorité « maison » — celle de l'établissement qui héberge cette instance. Volontairement la
# chaîne VIDE : c'est la valeur qu'ont déjà toutes les lignes en base, donc la migration ne
# renomme rien et ne peut pas entrer en collision.
LOCAL_AUTHORITY = ''


class OrgUnit(models.Model):
    """Unité organisationnelle = nœud de l'arbre institut/université → département →
    labo/service → équipe. COLONNE VERTÉBRALE unique : sert l'héritage RAG, les scopes
    de partage (médiathèque, fonctions) ET le gating d'accès. Synchronisée depuis
    l'annuaire LDAP/SUPANN (`ou=structures`, `supannCodeEntiteParent`) ou saisie manuelle."""
    TYPE_CHOICES = [
        ('institut', 'Institut'), ('universite', 'Université'), ('etablissement', 'Établissement'),
        ('departement', 'Département'), ('labo', 'Laboratoire'), ('service', 'Service'),
        ('equipe', 'Équipe'), ('autre', 'Autre'),
    ]
    # ⚠ `code` N'EST PAS unique globalement (correctif S2 du 27/08, §8.6). `supannCodeEntite` est
    # unique PAR ÉTABLISSEMENT, pas entre établissements : deux universités ont chacune leur
    # « DSI », et avec `unique=True` la seconde était simplement impossible à créer. C'était le
    # SEUL point non évolutif de tout le modèle d'accès — audité comme tel, et refermé ici plutôt
    # que plus tard, parce que le code voyage (cf. `authority` ci-dessous).
    code = models.CharField(max_length=64, db_index=True,
                            help_text='supannCodeEntite (identifiant annuaire).')
    # L'AUTORITÉ qui émet ce code — l'établissement / l'annuaire d'origine (ex. un domaine).
    # Vide = « l'établissement de cette instance », ce qui préserve exactement l'unicité d'avant
    # pour toutes les lignes existantes : la migration est donc sans risque de collision.
    #
    # Pourquoi un CHAMP plutôt qu'un préfixe dans `code` (les deux options du §8.6) : le code doit
    # rester le code de l'annuaire TEL QUEL, sinon chaque synchro LDAP devient de la chirurgie de
    # chaîne (`OrgUnit.objects.filter(code=supannCodeEntite)` cesserait de fonctionner) et une
    # donnée déjà en base — `{IFSTTAR}LESCOT` — deviendrait illisible. La forme préfixée existe,
    # mais comme forme EXPORTÉE (`qualified_code`), là où le code cesse d'être interne.
    authority = models.CharField(max_length=64, blank=True, default='', db_index=True,
                                 help_text="Établissement/annuaire émetteur du code "
                                           "(vide = celui de cette instance).")
    name = models.CharField(max_length=192)
    unit_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default='autre')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='children')
    source = models.CharField(max_length=16, default='ldap')   # 'ldap' | 'manual'

    class Meta:
        ordering = ['name']
        verbose_name = 'Unité organisationnelle'
        constraints = [
            models.UniqueConstraint(fields=['authority', 'code'],
                                    name='orgunit_authority_code_unique'),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_unit_type_display()})'

    @classmethod
    def local(cls):
        """Les unités de l'établissement de CETTE instance (`authority=''`).

        🔴 Tout `filter(code=…)` interne passe par ici. Rendre `code` non unique sans refermer les
        résolutions internes déplacerait simplement le défaut : le jour où une unité étrangère
        porterait le même code, `filter(code=…).first()` en choisirait une AU HASARD (ordering par
        `name`), sans rien signaler. C'est exactement la panne muette de `/model-manager/` —
        connue, documentée, jamais refermée. On la referme ici en même temps qu'on l'ouvre."""
        return cls.objects.filter(authority=LOCAL_AUTHORITY)

    @property
    def qualified_code(self):
        """Identifiant **globalement** unique — la forme sous laquelle le code SORT de WAMA.

        Un manifeste porte `scope_org_unit` en clair (str, pas une FK) et voyage : c'est le seul
        endroit où le code devient un identifiant PUBLIC, donc le seul qui doive être qualifié.
        Sans autorité, la forme est le code nu — les manifestes déjà écrits restent lisibles."""
        return f'{self.authority}:{self.code}' if self.authority else self.code

    @classmethod
    def split_qualified(cls, value):
        """`'univ:DSI'` → `('univ', 'DSI')` ; `'DSI'` → `('', 'DSI')`.

        Accepte les DEUX formes exprès : les manifestes antérieurs au 27/08 portent le code nu, et
        les rejeter reviendrait à casser la portabilité qu'on cherche justement à protéger."""
        value = (value or '').strip()
        autorite, sep, code = value.partition(':')
        return (autorite, code) if sep else ('', value)

    @classmethod
    def resolve_qualified(cls, value):
        """L'unité désignée par un code qualifié OU nu, ou None. Point d'entrée UNIQUE : c'est
        ici qu'on saura quoi faire le jour où un manifeste arrivera d'un autre établissement."""
        autorite, code = cls.split_qualified(value)
        if not code:
            return None
        return cls.objects.filter(authority=autorite, code=code).first()

    def ancestors(self, include_self=True):
        """Chaîne racine→…→self (liste d'OrgUnit), garde anti-cycle."""
        chain, node, guard = [], self, 0
        while node and guard < 20:
            chain.append(node)
            node = node.parent
            guard += 1
        chain.reverse()
        return chain if include_self else chain[:-1]

    def self_and_ancestor_ids(self):
        return [u.id for u in self.ancestors(include_self=True)]


class Project(models.Model):
    """Projet de recherche = groupe de collaboration EXPLICITE qui peut TRAVERSER l'arbre
    org : org propriétaire (labo) MAIS membres pouvant venir d'autres orgs (partenaires :
    autre labo/institut/université). Le partage par unité (`OrgUnit`) ne couvre PAS un projet
    inter-établissements → un `Project` est le 4e scope de partage. Voir §MONDES/Projets."""
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=192)
    description = models.TextField(blank=True, default='')
    owner_org = models.ForeignKey(OrgUnit, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='projects',
                                  help_text='Unité propriétaire (labo porteur).')
    lead = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='led_projects', help_text='Responsable du projet.')
    members = models.ManyToManyField('auth.User', through='ProjectMembership',
                                     related_name='projects', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Projet'

    def __str__(self):
        return f'{self.name} ({self.code})'


class ProjectMembership(models.Model):
    """Adhésion d'un utilisateur à un projet, avec son rôle et son org (traçabilité
    cross-org : de quel labo/établissement vient chaque partenaire)."""
    ROLE_CHOICES = [('lead', 'Responsable'), ('member', 'Membre'), ('partner', 'Partenaire'),
                    ('viewer', 'Lecture seule')]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='project_memberships')
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default='member')
    org = models.ForeignKey(OrgUnit, null=True, blank=True, on_delete=models.SET_NULL,
                            related_name='+', help_text='Org d\'origine du membre (partenaire).')
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('project', 'user')
        verbose_name = 'Adhésion projet'

    def __str__(self):
        return f'{self.user_id} @ {self.project_id} ({self.role})'


def user_projects(user):
    """Ids des projets dont l'utilisateur est membre (tous rôles)."""
    if not getattr(user, 'is_authenticated', False):
        return set()
    return set(ProjectMembership.objects.filter(user=user).values_list('project_id', flat=True))


def user_scope_org_ids(user):
    """Ensemble des OrgUnit ids « couvrant » l'utilisateur : ses unités de rattachement
    ET tous leurs ancêtres. Un item partagé au LABO est visible pour un membre d'une
    ÉQUIPE du labo (l'équipe a le labo pour ancêtre)."""
    if not getattr(user, 'is_authenticated', False):
        return set()
    prof = getattr(user, 'profile', None)
    if prof is None:
        return set()
    codes = list(prof.org_affiliations or [])
    if prof.org_entity_code:
        codes.append(prof.org_entity_code)
    ids = set()
    for u in OrgUnit.local().filter(code__in=set(codes)):
        ids.update(u.self_and_ancestor_ids())
    return ids


class ElementPreference(models.Model):
    """ABONNEMENT d'un utilisateur à un élément de catalogue (app, modèle, fonction, skill…).

    🔴 C'est une PRÉFÉRENCE, PAS UN DROIT (PROFILES_PERMISSIONS §8.1). Elle ne peut que
    RESTREINDRE ce que l'utilisateur voit à l'intérieur de ce à quoi il a DÉJÀ droit, jamais
    l'élargir. Aucune décision d'accès ne consulte cette table — c'est ce qui la rend sûre par
    construction, et livrable avant la couche de droits (`AccessGrant`, §8.2, pas encore écrite).

    ⚠ SEULES LES EXCEPTIONS SONT STOCKÉES. Le défaut est « abonné à tout ce que mon rôle
    autorise » : un compte neuf n'a aucune ligne ici et voit tout ce à quoi il a droit. Se
    désabonner écrit une ligne, se réabonner l'EFFACE. Stocker l'état complet aurait exigé de
    semer une ligne par (utilisateur × élément) à la création du compte, puis à chaque nouvel
    élément installé — un invariant à maintenir, donc un invariant qui dérive.

    `element_id` est une CLÉ TEXTUELLE, pas une FK : les éléments ne sont pas tous des lignes en
    base (un skill est un fichier `.md`). Un élément qui disparaît laisse une ligne orpheline
    inoffensive — elle ne masque plus rien puisque l'élément n'est plus listé.
    """
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                             related_name='element_preferences')
    kind = models.CharField(max_length=16, db_index=True)      # cf. services/subscriptions.KINDS
    element_id = models.CharField(max_length=128)
    subscribed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'kind', 'element_id')]
        verbose_name = "Préférence d'abonnement"
        verbose_name_plural = "Préférences d'abonnement"

    def __str__(self):
        etat = 'abonné' if self.subscribed else 'masqué'
        return f'{self.user} · {self.kind}:{self.element_id} ({etat})'


class ScopedVisibility(models.Model):
    """Mixin ABSTRAIT : visibilité par scope (privé / PROJET / unité org / public).
    - `unit` + `scope_org_unit` : partagé avec l'unité ET ses sous-unités (labo→équipes) ;
    - `project` + `scope_project` : partagé avec les MEMBRES d'un projet (peut TRAVERSER
      les orgs : partenaires d'un autre labo/université). Utilisé par médiathèque + fonctions."""
    VIS_PRIVATE, VIS_PROJECT, VIS_UNIT, VIS_PUBLIC = 'private', 'project', 'unit', 'public'
    VIS_CHOICES = [(VIS_PRIVATE, 'Privé'), (VIS_PROJECT, 'Projet (membres, cross-org)'),
                   (VIS_UNIT, 'Unité (labo/dépt/univ…)'), (VIS_PUBLIC, 'Public')]
    visibility = models.CharField(max_length=12, choices=VIS_CHOICES, default=VIS_PRIVATE,
                                  db_index=True)
    scope_org_unit = models.ForeignKey(OrgUnit, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+',
                                       help_text="Unité de partage si visibility='unit'.")
    scope_project = models.ForeignKey('common.Project', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+',
                                      help_text="Projet de partage si visibility='project'.")

    class Meta:
        abstract = True


def scoped_visible_q(user, owner_field='user'):
    """`Q` filtrant les objets ScopedVisibility visibles pour `user` : les siens + les
    publics + ceux partagés à une unité qui le couvre + ceux partagés à un projet dont
    il est membre (le scope PROJET traverse les orgs → partenaires externes)."""
    from django.db.models import Q
    q = Q(visibility=ScopedVisibility.VIS_PUBLIC)
    if getattr(user, 'is_authenticated', False):
        q |= Q(**{owner_field: user})
        ids = user_scope_org_ids(user)
        if ids:
            q |= Q(visibility=ScopedVisibility.VIS_UNIT, scope_org_unit_id__in=ids)
        pids = user_projects(user)
        if pids:
            q |= Q(visibility=ScopedVisibility.VIS_PROJECT, scope_project_id__in=pids)
    return q


class PromptScoped(models.Model):
    """
    Modèle portant un prompt utilisateur TRAITÉ par la PromptPipeline (enrichissement).

    Convention commune (cf. `common/utils/app_metadata.py`, WAMA_LLM.md) :
    - `prompt` (déclaré par l'app) reste **ce que l'utilisateur a tapé** — jamais écrasé ;
    - `prompt_processed` = ce qui part réellement au modèle (vide → on envoie `prompt`) ;
    - `prompt_trace` = ce que la pipeline a fait, pour pouvoir le montrer et l'annuler ;
    - `prompt_keywords` = les mots-clés cliqués, conservés comme DONNÉE (glossaire verbatim).

    Hériter de ce mixin suffit : l'enrichissement à l'ingestion, le champ à deux états et le
    retour au prompt d'origine viennent avec, sans une ligne de code par app.
    """

    prompt_processed = models.TextField(
        blank=True, default="",
        help_text="Prompt traité effectivement envoyé au modèle (vide = utiliser `prompt`)")
    prompt_trace = models.JSONField(
        default=dict, blank=True,
        help_text="Trace PromptPipeline par champ : {enriched, source, language, keywords}")
    prompt_keywords = models.JSONField(default=list, blank=True)

    class Meta:
        abstract = True


class ScopedQuerySet(models.QuerySet):
    """QuerySet des modèles `ScopedVisibility` : expose `visible_to(user)`."""

    def visible_to(self, user, owner_field='user'):
        """Objets que `user` a le droit de VOIR : les siens + publics + unité + projet."""
        return self.filter(scoped_visible_q(user, owner_field=owner_field))

    def owned_by(self, user, owner_field='user'):
        """Objets que `user` a le droit de MODIFIER — aujourd'hui : les siens, point.

        Le partage est en LECTURE SEULE par construction : les vues mutantes (start, delete,
        enregistrement des paramètres) passent par ici, les vues de liste par `visible_to`.
        L'écriture sur objet partagé viendra avec `ObjectGrant` (PROFILES_PERMISSIONS §7.3) ;
        d'ici là, aucune vue ne peut accorder l'écriture par inadvertance.
        """
        return self.filter(**{owner_field: user})


class ScopedManager(models.Manager.from_queryset(ScopedQuerySet)):
    """
    Manager par défaut des modèles partageables.

    Pourquoi un manager et pas un helper : les droits par objet **fuient dans toutes les
    requêtes** — il suffit d'une vue qui oublie le filtre pour tout ouvrir. En faisant de
    `Model.objects.visible_to(user)` le chemin nommé, l'oubli devient visible à la relecture et
    **mesurable** par la grille de conformité (PROFILES_PERMISSIONS §7.4).
    """


class UserFunction(ScopedVisibility):
    """Fonction de traitement CRÉÉE PAR UN UTILISATEUR (WAMA Data), stockée en BDD, avec
    confidentialité par scope (privée / partagée à une unité / publique). Distincte des
    fonctions SYSTÈME code-déclarées (FUNCTION_CATALOG, toujours publiques). Décrite par
    ses capacités E/S comme un FunctionSpec → fusionnée au catalogue selon la visibilité."""
    key = models.CharField(max_length=128, unique=True, db_index=True)
    name = models.CharField(max_length=192)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=32, default='transform')
    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='wama_functions')
    tags = models.JSONField(default=list, blank=True)
    projects = models.JSONField(default=list, blank=True)
    inputs = models.JSONField(default=list, blank=True)     # [PortSpec dict]
    outputs = models.JSONField(default=list, blank=True)    # [PortSpec dict]
    params = models.JSONField(default=list, blank=True)     # [ParamSpec dict]
    impl = models.TextField(blank=True)                     # référence/code (à venir)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Fonction utilisateur'

    def __str__(self):
        return f'{self.name} ({self.owner_id})'

    def to_dict(self):
        """Même forme qu'un FunctionSpec.to_dict() pour fusion dans le catalogue."""
        return {
            'key': self.key, 'name': self.name, 'description': self.description,
            'category': self.category, 'binding': 'user', 'app': '', 'impl': self.impl,
            'tags': self.tags or [], 'projects': self.projects or [],
            'visibility': self.visibility,
            'owner': self.owner.get_username() if self.owner_id else '',
            'scope': self.scope_org_unit.name if self.scope_org_unit_id else None,
            'inputs': self.inputs or [], 'outputs': self.outputs or [],
            'params': self.params or [], 'cost': {},
        }


class Manifest(models.Model):
    """Store des MANIFESTES (union discriminée par `manifest_kind`) — cf. WAMA_MANIFEST_SPEC.md.

    Source AUTORITAIRE re-synchronisable. L'enveloppe (identité/monde/confidentialité) est en colonnes ;
    le `body` spécifique au kind est un JSON. `scope_project`/`scope_org_unit` sont des CODES (str), pas
    des FK : un manifeste peut référencer un projet/une unité pas encore créés (portabilité). SANDBOX =
    `visibility='private'` ; `promote()` publie au commun. Idempotent sur (manifest_kind, key)."""

    manifest_kind = models.CharField(max_length=32, db_index=True)   # app|function|dataset|model|pipeline|project
    key = models.CharField(max_length=128, db_index=True)            # unique DANS le kind
    schema_version = models.CharField(max_length=16, default='1.0')

    name = models.CharField(max_length=200)                          # anglais canonique
    description = models.TextField(blank=True, default='')           # anglais canonique
    world = models.CharField(max_length=16, default='transverse')    # media|data|lab|transverse

    owner = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='wama_manifests')
    visibility = models.CharField(max_length=12, default='private')  # private(=sandbox)|project|unit|public
    scope_project = models.CharField(max_length=64, blank=True, default='')   # code Project
    scope_org_unit = models.CharField(max_length=64, blank=True, default='')  # code OrgUnit

    projects = models.JSONField(default=list, blank=True)            # traçabilité qualité
    source = models.JSONField(default=dict, blank=True)              # {type, ref}
    body = models.JSONField(default=dict, blank=True)                # spécifique au kind
    errors = models.JSONField(default=list, blank=True)             # dernières erreurs de validation

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('manifest_kind', 'key'),)
        ordering = ('manifest_kind', 'key')
        indexes = [models.Index(fields=['manifest_kind', 'visibility'])]

    def __str__(self):
        return f"{self.manifest_kind}:{self.key} ({self.visibility})"

    @property
    def is_sandbox(self) -> bool:
        return self.visibility == 'private'

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def as_manifest(self) -> dict:
        """Reconstruit le dict manifeste complet (enveloppe + body)."""
        return {
            'manifest_kind': self.manifest_kind,
            'key': self.key,
            'schema_version': self.schema_version,
            'name': self.name,
            'description': self.description,
            'world': self.world,
            'owner': self.owner.get_username() if self.owner_id else None,
            'visibility': self.visibility,
            'scope_project': self.scope_project or None,
            'scope_org_unit': self.scope_org_unit or None,
            'projects': self.projects or [],
            'source': self.source or {},
            'body': self.body or {},
        }


class Library(models.Model):
    """
    Registre des librairies externes — **NÉ de la projection** du manifeste `library`.

    Pourquoi ici et pas ailleurs : ROADMAP §16.7 désigne `library` comme le kind PILOTE du
    manifeste-first, précisément parce qu'il n'a **aucun registre historique à réconcilier**
    (contrairement aux modèles, qui avaient `AIModel` bien avant les manifestes). Ce registre
    naît donc propre : sa seule source d'écriture déclarative est `write_back_library()`.

    Frontière (SPEC §7.1) : on stocke ce que la librairie EST — dépôt, licence, version, install,
    points d'entrée, contraintes. **JAMAIS l'usage qu'une app en fait** : ça, c'est le `requires`
    du manifeste d'app, et le dupliquer ici recréerait la divergence qu'on cherche à éliminer.
    """

    # ── Identité ────────────────────────────────────────────────────────────────
    #: Nom de distribution PyPI (= `key` du manifeste, p.ex. 'faster-whisper').
    key = models.CharField(max_length=128, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default='')

    # ── Facettes DÉCLARATIVES (miroir du body du manifeste, écrites par la projection) ──
    version = models.CharField(max_length=64, blank=True, default='')
    license = models.CharField(max_length=128, blank=True, default='')
    # Auteur/éditeur — pendant de `license`, et pour les mêmes raisons : une licence à
    # attribution (CC-BY, BSD, MIT…) est INAPPLICABLE sans le nom à citer. Le couple
    # licence+auteur existait déjà dans `media_library/providers/base.Asset` ; on en reprend
    # le vocabulaire au lieu d'en inventer un second (2026-08-12).
    author = models.CharField(max_length=200, blank=True, default='',
                              help_text="Auteur/éditeur déclaré en amont (métadonnée PyPI `Author`).")
    repository = models.CharField(max_length=300, blank=True, default='')
    pip_spec = models.CharField(
        max_length=200, blank=True, default='',
        help_text="Spécificateur d'installation épinglé, p.ex. 'faster-whisper==1.2.1'")
    requires_python = models.CharField(max_length=64, blank=True, default='')
    entry_points = models.JSONField(default=dict, blank=True)
    dependencies = models.JSONField(default=list, blank=True)
    constraints = models.JSONField(
        default=dict, blank=True,
        help_text="Contraintes GPU/OS non extractibles mécaniquement (remplies par le rôle "
                  "wama-dev-ai « librarian », jamais inventées)")

    # ── VERROU D'INSTALLATION (ROADMAP §16.7, transposé d'Hermes) ───────────────
    # Verrou n°2 d'Hermes : l'allowlist vit DANS l'arbre, et la config utilisateur ne peut pas
    # élargir le périmètre. Transposé ici : `is_allowed` est une décision HUMAINE explicite et
    # n'est **JAMAIS** écrit par `write_back_library()`. Sans cette exclusion, ingérer un manifeste
    # suffirait à s'auto-autoriser à installer — le verrou ne vaudrait plus rien.
    is_allowed = models.BooleanField(
        default=False, db_index=True,
        help_text="Autorisée à l'installation (allowlist). Décision humaine — jamais projetée "
                  "depuis un manifeste.")

    # ── État RUNTIME (mesuré, jamais projeté — un manifeste est portable, l'install ne l'est pas) ──
    is_installed = models.BooleanField(default=False, db_index=True)
    installed_version = models.CharField(max_length=64, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Librairie"
        verbose_name_plural = "Librairies"
        ordering = ['key']

    def __str__(self):
        return f"{self.key} ({self.version or 'version inconnue'})"

    #: Champs que la projection a le droit d'écrire. Tout le reste (`is_allowed`, état runtime,
    #: timestamps) est HORS projection — cf. les deux blocs ci-dessus.
    PROJECTABLE_FIELDS = (
        'name', 'summary', 'version', 'license', 'author', 'repository',
        'pip_spec', 'requires_python', 'entry_points', 'dependencies', 'constraints',
    )

    def to_dict(self):
        return {
            'key': self.key,
            'name': self.name,
            'summary': self.summary,
            'version': self.version,
            'license': self.license,
            'author': self.author,
            'repository': self.repository,
            'pip_spec': self.pip_spec,
            'requires_python': self.requires_python,
            'entry_points': self.entry_points or {},
            'dependencies': self.dependencies or [],
            'constraints': self.constraints or {},
            'is_allowed': self.is_allowed,
            'is_installed': self.is_installed,
            'installed_version': self.installed_version,
        }


class RunOutcome(models.Model):
    """
    Journal des FAITS observés sur un résultat produit — préalable de toute auto-amélioration
    (ROADMAP §16.7). Append-only : chaque ligne est un événement, jamais un état mis à jour.

    POURQUOI CETTE BRIQUE. Les boucles visées (qualité des modèles, enrichissement de prompt,
    prospection) sont TOUTES bloquées sur l'absence de ce signal, et **aucun framework ne le
    récupérera rétroactivement** : ce qui n'est pas capté aujourd'hui est perdu. WAMA jette
    déjà des labels humains de grande valeur — corrections manuelles du Transcriber (paires
    ASR→vérité), entités démasquées/ajoutées de l'Anonymizer (FP/FN), générations de l'Imager
    gardées vs supprimées, prompts enrichis acceptés vs réécrits.

    ⚠ CAPTURE IMPLICITE, JAMAIS UN FORMULAIRE DE NOTATION. Règle posée en §16.7 et transposée
    d'un SI de labo réel : les chaînes qui vivent sont celles où le contributeur obtient quelque
    chose AU MOMENT où il agit ; celles qui reposent sur la bonne volonté (« notez ce résultat
    pour améliorer le système ») meurent, même bien conçues. On ne se nourrit donc QUE de gestes
    que l'utilisateur fait déjà : télécharger, corriger, relancer, supprimer.

    ⚠ ON ENREGISTRE UN FAIT, PAS UN JUGEMENT. Il n'y a volontairement **aucun champ score** ici.
    « Supprimé » ne veut pas dire « mauvais » — ce peut être un simple ménage ; « téléchargé » ne
    veut pas dire « parfait ». L'interprétation appartient à l'AGRÉGATION, qui a le nombre pour
    elle, et elle reste un signal RELATIF à escalader vers l'humain — jamais un gate absolu
    (garde-fous §16.5). Mélanger le fait et son interprétation ici rendrait le journal
    ininterprétable le jour où l'on changera d'avis sur la lecture.
    """

    #: Les signaux sont des GESTES, nommés par ce qui a été fait — pas par ce qu'on en conclut.
    SIGNAL_CHOICES = [
        ('produit',    'Résultat produit'),          # posé par le squelette de tâche
        ('echec',      'Échec de production'),
        ('telecharge', 'Résultat téléchargé'),       # l'utilisateur l'emporte
        ('corrige',    'Résultat corrigé à la main'),  # il ne convenait pas tel quel
        ('relance',    'Relancé sur le même item'),  # le précédent n'a pas suffi
        ('supprime',   'Résultat supprimé'),
    ]

    app = models.CharField(max_length=32, db_index=True)
    #: Cible : nom du modèle Django + clé primaire. Pas de FK générique — les items vivent dans
    #: 10 apps et une ContentType ne servirait qu'à joindre ce qu'on ne joint jamais.
    object_type = models.CharField(max_length=64)
    object_id = models.IntegerField(db_index=True)
    # Référence par chaîne (`settings.AUTH_USER_MODEL`) : ce module n'importe aucun modèle
    # d'auth, et l'importer ici créerait un cycle avec les apps qui en dépendent.
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='run_outcomes')

    signal = models.CharField(max_length=16, choices=SIGNAL_CHOICES, db_index=True)

    #: Clés catalogue des modèles ayant produit le résultat. LISTE, parce qu'une exécution peut
    #: en mobiliser plusieurs (anonymizer : un détecteur de visages + un de plaques).
    #: ⚠ L'attribution devient alors ambiguë — un signal sur un résultat à 2 modèles ne dit pas
    #: LEQUEL a démérité. L'agrégation doit donc pondérer, ou ne retenir que les exécutions à
    #: modèle unique. Écrit ici pour que le choix reste possible plus tard, pas pour le trancher.
    model_keys = models.JSONField(default=list, blank=True)

    #: Ce que le fait porte de mesurable : ampleur d'une correction, format téléchargé, réglages
    #: modifiés à la relance… Jamais une note.
    detail = models.JSONField(default=dict, blank=True)

    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Signal d'exécution"
        verbose_name_plural = "Signaux d'exécution"
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['app', 'signal']),
            models.Index(fields=['object_type', 'object_id']),
            models.Index(fields=['occurred_at']),
        ]

    def __str__(self):
        return f"{self.app}:{self.object_type}#{self.object_id} → {self.signal}"


# ─────────────────────────────────────────────────────────────────────────────
# Mémoire & RAG — doc de référence : WAMA_MEMORY.md
#
# Les modèles vivent ICI (et non dans `common/memory/`) par le même précédent que `RunOutcome` :
# le modèle est dans `models.py`, la logique dans une brique dédiée (`common/memory/`). Les y
# déplacer imposerait un import circulaire avec `ScopedVisibility`, sans rien gagner.
#
# ⚠ AUCUN APPELANT à ce jour — jalon 3 de WAMA_MEMORY.md §10. Rien ne change pour un utilisateur
# tant que le Hook B de `prompt_pipeline` n'est pas branché (jalon 6).
# ─────────────────────────────────────────────────────────────────────────────

#: Dimension des vecteurs `bge-m3`. Figée ici parce qu'un changement impose une MIGRATION (la
#: colonne pgvector est typée `vector(N)`), pas un simple réindex — contrairement au changement
#: de modèle à dimension égale, qui n'exige que de recalculer les embeddings.
EMBEDDING_DIMS = 1024


class Embedded(models.Model):
    """
    Socle vectoriel commun au souvenir et au fragment. ABSTRAIT — aucune table.

    RÈGLE : `content` est conservé VERBATIM. On n'y résume ni ne paraphrase à l'écriture, parce
    que la perte serait irréversible et qu'on ne saurait jamais ce qu'on a jeté. La condensation
    est un choix de LECTURE (ce qu'on injecte dans un prompt), jamais d'écriture.
    """

    content = models.TextField(help_text="Texte VERBATIM. Jamais résumé à l'écriture.")

    #: SHA-256 du contenu normalisé — dédup EXACTE, réglée avant tout appel LLM ou embedding.
    #: L'écrasante majorité des doublons sont des re-projections à l'identique : les traiter ici
    #: coûte un index, alors que les traiter par similarité coûterait un embedding par candidat.
    content_hash = models.CharField(max_length=64, db_index=True, blank=True, default='')

    #: NULL tant que l'embedder n'a pas tourné. C'est un état NORMAL, pas une anomalie : une
    #: écriture ne doit jamais être perdue parce qu'Ollama était éteint (cf. `embed.py`).
    embedding = VectorField(dimensions=EMBEDDING_DIMS, null=True, blank=True)

    #: Le modèle qui a produit le vecteur. Sans ce champ, une bascule d'embedder mélangerait deux
    #: espaces vectoriels dans la même colonne — les distances deviendraient du bruit SANS AUCUNE
    #: erreur visible. Avec lui, une bascule est un réindex explicite et mesurable.
    embedding_model = models.CharField(max_length=64, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MemoryItem(Embedded, ScopedVisibility):
    """
    LE SOUVENIR — un fait, un événement ou une procédure. NON re-dérivable.

    ⚠ JAMAIS PURGÉ AUTOMATIQUEMENT. C'est la raison d'être de la séparation d'avec `RagChunk` :
    le 2026-08-19, une purge ciblée a détruit 13 évaluations LLM parce que deux natures de
    données cohabitaient dans la même table (GPU dépensé pour rien). Deux tables rendent
    l'accident IMPOSSIBLE, pas seulement improbable.

    Le scope (privé / projet / unité / public) vient de `ScopedVisibility` : un rappel est une
    queryset filtrée par `scoped_visible_q(user)`. La hiérarchie RAG université → labo → équipe →
    utilisateur de la vision §11 est donc HÉRITÉE, pas ré-implémentée.
    """

    KIND_SEMANTIC = 'semantic'      # un fait stable      : « Fabien exporte en PDF »
    KIND_EPISODIC = 'episodic'      # un événement daté   : « transcription 142 corrigée le 12/08 »
    KIND_PROCEDURAL = 'procedural'  # une manière de faire : « pour un m4a, décoder avant Whisper »
    # ⚠ 'emotional' (4e type de memorywire) est RÉSERVÉ, PAS implémenté — décision 2026-08-20,
    # raisonnement complet dans WAMA_MEMORY.md §8. En résumé : seul type sans producteur
    # mécanique (il INFÈRE au lieu de constater), inférence fausse indétectable, et profiler
    # l'humeur d'un agent public dans un magasin de scope `unit` n'est pas neutre. Le bénéfice
    # visé (pondération du rappel) est obtenu par `salience`, dérivée de gestes RÉELS.
    KIND_CHOICES = [
        (KIND_SEMANTIC, 'Fait'), (KIND_EPISODIC, 'Événement'), (KIND_PROCEDURAL, 'Procédure'),
    ]

    #: Provenance — OBLIGATOIRE. C'est le levier le plus efficace pour dépoisonner un magasin :
    #: on invalide par provenance en une requête, au lieu d'auditer item par item.
    PROV_PROJECTION = 'projection'  # dérivé mécaniquement d'un fait déjà en base (RunOutcome…)
    PROV_ASSISTANT = 'assistant'    # produit par l'assistant IA au fil d'une conversation
    PROV_DEV_AI = 'dev-ai'          # produit par wama-dev-ai
    PROV_HUMAN = 'human'            # saisi ou validé explicitement par un humain
    PROVENANCE_CHOICES = [
        (PROV_PROJECTION, 'Projection'), (PROV_ASSISTANT, 'Assistant IA'),
        (PROV_DEV_AI, 'wama-dev-ai'), (PROV_HUMAN, 'Humain'),
    ]

    kind = models.CharField(max_length=12, choices=KIND_CHOICES, db_index=True)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True,
                             related_name='memory_items',
                             help_text='À qui appartient le souvenir (None = souvenir système).')
    subject = models.CharField(max_length=128, blank=True, default='', db_index=True,
                               help_text='De quoi ça parle : app, model_key, thème.')

    #: D'où vient le souvenir. Même convention que `RunOutcome` (chaîne + pk, pas de ContentType) :
    #: les items vivent dans 10 apps et une FK générique ne servirait qu'à joindre ce qu'on ne
    #: joint jamais. Vide pour un souvenir qui ne pointe aucun objet (une préférence, une règle).
    source_app = models.CharField(max_length=32, blank=True, default='', db_index=True)
    source_object_type = models.CharField(max_length=64, blank=True, default='')
    source_object_id = models.IntegerField(null=True, blank=True, db_index=True)

    provenance = models.CharField(max_length=12, choices=PROVENANCE_CHOICES, db_index=True)

    #: None pour un fait MÉCANIQUE. Mettre 1.0 sur une projection inventerait un chiffre là où il
    #: n'y a pas de mesure — et rendrait incomparables les confiances qui, elles, en sont une.
    confidence = models.FloatField(null=True, blank=True)

    #: Fenêtre de validité (l'apport réel du graphe temporel de Graphiti, pour deux colonnes au
    #: lieu d'un serveur). Un souvenir périmé est INVALIDÉ (`valid_to`), jamais écrasé : l'écraser
    #: détruirait la trace de ce qui était tenu pour vrai, et donc toute possibilité d'audit.
    valid_from = models.DateTimeField(null=True, blank=True, db_index=True)
    valid_to = models.DateTimeField(null=True, blank=True, db_index=True)

    #: `merge()` CHAÎNE les souvenirs fusionnés au lieu de les supprimer.
    superseded_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='supersedes')

    #: HITL. `approved_at IS NULL` ⇒ INVISIBLE au rappel. Tout écrit issu d'un LLM naît ainsi :
    #: mesure du 2026-07-17 sur 6 audits wama-dev-ai — affirmations d'absence fausses 4 fois sur 6.
    #: Une mémoire qui gobe ces sorties se corrompt en une nuit, et le poison est indiscernable
    #: d'un fait une fois écrit.
    approved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    approved_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='approved_memory_items')

    #: Saillance — pondère le rappel. DÉRIVÉE de `RunOutcome` (corrigé/relancé/supprimé = friction ;
    #: téléchargé = emporté), donc RECALCULABLE et jamais saisie. C'est ce qui donne le bénéfice
    #: de la « mémoire émotionnelle » sans inférer quoi que ce soit sur l'utilisateur.
    salience = models.FloatField(default=0.0, db_index=True)

    class Meta:
        verbose_name = 'Souvenir'
        verbose_name_plural = 'Souvenirs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'kind']),
            models.Index(fields=['subject', 'kind']),
            models.Index(fields=['source_app', 'source_object_type', 'source_object_id']),
            models.Index(fields=['provenance', 'approved_at']),
            models.Index(fields=['content_hash']),
        ]

    def __str__(self):
        return f"[{self.kind}/{self.provenance}] {self.content[:60]}"

    @property
    def is_active(self):
        """Approuvé ET non invalidé. Le rappel n'expose QUE des souvenirs actifs."""
        from django.utils import timezone
        if self.approved_at is None:
            return False
        return self.valid_to is None or self.valid_to > timezone.now()


class RagChunk(Embedded, ScopedVisibility):
    """
    LE FRAGMENT — un morceau d'un document source. RE-DÉRIVABLE : la source fait foi, donc une
    réindexation peut le détruire et le reconstruire sans perte. C'est exactement ce qu'un
    `MemoryItem` ne supporte pas — d'où deux tables.

    ⚠ PIÈGE — la visibilité est DÉNORMALISÉE depuis la source. Les sources sont hétérogènes
    (média, manifeste, corpus, document) : joindre à la volée est impossible, on copie donc le
    scope au moment de l'indexation. Cette copie DOIT être rafraîchie quand la source change de
    visibilité, sans quoi un fragment resterait partagé au labo après que le média a été repassé
    en privé. Le rafraîchissement est une obligation, pas une optimisation (jalon 5).
    """

    SOURCE_CHOICES = [
        ('media', 'Média (médiathèque)'), ('manifest', 'Manifeste'),
        ('corpus', 'Corpus externe'), ('doc', 'Document'),
    ]

    source_kind = models.CharField(max_length=12, choices=SOURCE_CHOICES, db_index=True)
    source_id = models.CharField(max_length=64, db_index=True)
    source_ref = models.TextField(blank=True, default='',
                                  help_text='Chemin/URL + offset — pour citer et rouvrir.')
    #: Position dans la source : permet de restituer le voisinage d'un fragment retrouvé, ce
    #: qu'un fragment isolé ne peut pas faire (une phrase sans son paragraphe induit en erreur).
    ordinal = models.IntegerField(default=0)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, null=True, blank=True,
                             related_name='rag_chunks')
    indexed_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = 'Fragment RAG'
        verbose_name_plural = 'Fragments RAG'
        ordering = ['source_kind', 'source_id', 'ordinal']
        indexes = [
            models.Index(fields=['source_kind', 'source_id', 'ordinal']),
            models.Index(fields=['content_hash']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['source_kind', 'source_id', 'ordinal'],
                                    name='ragchunk_unique_source_position'),
        ]

    def __str__(self):
        return f"{self.source_kind}:{self.source_id}#{self.ordinal}"


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION — le fil de dialogue avec l'assistant  (ROADMAP §19.5)
# ─────────────────────────────────────────────────────────────────────────────
# POURQUOI UNE TROISIÈME TABLE, et surtout pas `MemoryItem`. La règle de ce module vaut ici
# plus qu'ailleurs : deux natures de données ⇒ deux tables. Un tour de conversation est
# RE-JOUABLE, PURGEABLE et VOLUMINEUX ; un `MemoryItem` n'est pas re-dérivable et n'est
# JAMAIS purgé automatiquement. Les faire cohabiter reproduirait l'accident du 2026-08-19,
# où une purge ciblée a détruit 13 évaluations LLM parce que deux natures partageaient une
# table.
#
# La jonction avec la mémoire n'est donc PAS le stockage, c'est la PROJECTION : un fil clos
# pourra produire un `MemoryItem` de provenance `assistant`, non approuvé par défaut
# (`WAMA_MEMORY.md §6`). Elle n'est pas faite ici — elle viendra quand elle aura un usage.
#
# CE QUE ÇA REMPLACE : l'historique vivait CHEZ LE CLIENT — `localStorage` côté web (perdu
# en changeant de navigateur, invisible depuis un autre appareil) et un dict EN MÉMOIRE DU
# PROCESS côté passerelle (perdu à chaque redémarrage, non partagé entre process).


class Conversation(models.Model):
    """
    Un fil de dialogue avec l'assistant, quelle que soit la surface qui le porte.

    L'IDENTITÉ D'UN FIL est `(user, surface, thread_key)` : c'est ce qui permet à un DM
    Discord, un salon Matrix et un onglet de navigateur d'être trois conversations
    distinctes sans que le moteur ait à le savoir. La passerelle a déjà cette clé
    (`gateway/core.py::_thread_key`) ; le web fournit un identifiant d'onglet.
    """

    SURFACES = [
        ('web', 'Navigateur'),
        ('api', 'API'),
        ('discord', 'Discord'),
        ('matrix', 'Tchap / Matrix'),
    ]

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                             related_name='conversations')
    surface = models.CharField(max_length=16, choices=SURFACES, default='web',
                               verbose_name='Surface')
    #: Identifiant du fil DANS sa surface (id de salon Discord, id d'onglet web…).
    #: Vide = fil unique de cette surface pour cet utilisateur.
    thread_key = models.CharField(max_length=255, blank=True, default='',
                                  verbose_name='Clé de fil')
    #: Titre lisible — dérivé du premier message si personne ne le fixe.
    title = models.CharField(max_length=200, blank=True, default='', verbose_name='Titre')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'
        ordering = ['-updated_at']
        constraints = [
            # Un fil par (utilisateur, surface, clé). Sans cette contrainte, deux messages
            # simultanés du même salon créeraient deux fils et l'historique se scinderait
            # EN SILENCE — le genre de défaut qui ne se voit qu'au bout de trois semaines.
            models.UniqueConstraint(fields=['user', 'surface', 'thread_key'],
                                    name='conversation_unique_fil'),
        ]
        indexes = [models.Index(fields=['user', 'surface', 'thread_key'])]

    def __str__(self):
        return self.title or f"{self.get_surface_display()} #{self.pk}"

    def titre_auto(self, message: str) -> str:
        """Pose un titre depuis le premier message, si le fil n'en a pas encore."""
        if self.title or not message:
            return self.title
        propre = ' '.join(message.split())[:80]
        self.title = propre + ('…' if len(propre) == 80 else '')
        self.save(update_fields=['title'])
        return self.title


class ConversationTurn(models.Model):
    """
    Un tour de conversation — ce que l'utilisateur a dit, ou ce que l'assistant a répondu.

    `tool_steps` porte les outils réellement exécutés pendant le tour : c'est la trace qui
    rend une conversation VÉRIFIABLE après coup (« qu'a-t-il lancé, avec quels arguments ? »),
    et elle ne se reconstitue pas depuis le texte de la réponse.
    """

    ROLES = [('user', 'Utilisateur'), ('assistant', 'Assistant')]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE,
                                     related_name='turns')
    role = models.CharField(max_length=16, choices=ROLES)
    content = models.TextField()
    #: Étapes d'outil du tour (liste de {tool, args, result}) — vide pour un tour utilisateur.
    tool_steps = models.JSONField(default=list, blank=True)
    #: Modèle ayant produit la réponse — permet de comparer deux moteurs a posteriori.
    model = models.CharField(max_length=120, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tour de conversation'
        verbose_name_plural = 'Tours de conversation'
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['conversation', 'created_at'])]

    def __str__(self):
        return f"{self.role}: {self.content[:60]}"
