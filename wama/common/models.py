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
# Voir docs/VISION_STATUS.md §MONDES, memory/project_wama_mondes.md.
# ─────────────────────────────────────────────────────────────────────────────

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
    code = models.CharField(max_length=64, unique=True, db_index=True,
                            help_text='supannCodeEntite (identifiant annuaire).')
    name = models.CharField(max_length=192)
    unit_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default='autre')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='children')
    source = models.CharField(max_length=16, default='ldap')   # 'ldap' | 'manual'

    class Meta:
        ordering = ['name']
        verbose_name = 'Unité organisationnelle'

    def __str__(self):
        return f'{self.name} ({self.get_unit_type_display()})'

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
    for u in OrgUnit.objects.filter(code__in=set(codes)):
        ids.update(u.self_and_ancestor_ids())
    return ids


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
