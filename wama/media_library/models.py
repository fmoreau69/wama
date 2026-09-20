"""
WAMA Media Library — Modèles
Gestion centralisée des assets réutilisables cross-apps.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from wama.common.utils.media_paths import UploadToUserPath
from wama.common.utils.secret_crypto import EncryptedTextField

User = get_user_model()

# ── Tout ce qui suit DÉRIVE de la déclaration des natures (`natures.py`, construction A′,
# 2026-09-13). Ces trois tables étaient écrites ici à la main, et recopiées une 4ᵉ fois côté
# JS (formats, libellés, icônes — sans `object3d`). Une nature = une entrée dans `ASSET_NATURES` ;
# rien ne s'ajoute ici.
from .natures import ASSET_NATURES, normalize_attributes

ASSET_TYPES = [(k, n.label) for k, n in ASSET_NATURES.items()]
ALLOWED_EXTENSIONS = {k: list(n.extensions) for k, n in ASSET_NATURES.items()}

# Union de toutes les extensions pour le FileExtensionValidator
_ALL_EXTENSIONS = sorted({ext for exts in ALLOWED_EXTENSIONS.values() for ext in exts})

# Rattachement des ASSET_TYPES (fins, propres à Media Library) au vocabulaire de catégories
# UNIQUE de WAMA (`app_registry.MEDIA_CATEGORIES` — déjà utilisé par le typage des ports studio
# et par `media_probe.probe_media`). Media Library ne réinvente PAS ses propres noms de
# catégories : elle mappe ses types fins dessus (plusieurs ASSET_TYPES → une même catégorie).
from wama.common.app_registry import MEDIA_CATEGORIES

ASSET_TYPE_CATEGORY = {k: n.category for k, n in ASSET_NATURES.items()}


class _AttributesMixin:
    """`attributes` normalisé À CHAQUE `save()` sur la déclaration de la nature — et un
    `asset_type` hors vocabulaire est REFUSÉ ici, parce que Django ne vérifie `choices` qu'en
    `full_clean()` : c'est ainsi qu'une ligne `asset_type='audio'` (une catégorie, pas un
    type) a pu entrer en base (`MEDIA_STORAGE_TIERING §9.2`)."""

    def save(self, *args, **kwargs):
        try:
            self.attributes = normalize_attributes(self.asset_type, self.attributes)
        except KeyError:
            raise ValueError(f"asset_type {self.asset_type!r} hors du vocabulaire des natures "
                             f"({', '.join(ASSET_NATURES)})")
        fields = kwargs.get('update_fields')
        if fields is not None and 'attributes' not in fields:
            kwargs['update_fields'] = list(fields) + ['attributes']
        super().save(*args, **kwargs)

# Alias logiques → liste de vraies valeurs ASSET_TYPES (bug 2026-07-09 : le picker/les modes d'app
# passent des types « larges » — 'all' (défaut `_new_item_card.html`), 'audio' (transcriber +
# `app_modes.py` accept='audio') — qui ne correspondent à AUCUNE valeur ASSET_TYPES exacte. Un
# `.filter(asset_type=asset_type)` littéral sur ces alias ne matchait donc JAMAIS rien (recherche
# toujours vide, quel que soit le texte tapé). Résolu ici, en un seul endroit, consommé par
# `views.py::api_list` — toute app appelant `MediaPicker.open({type: 'audio'|'image'|'all'|…})`
# en profite sans rien changer côté app. Clés = catégories de MEDIA_CATEGORIES (pas un 2e
# vocabulaire local) ; 'all' reste le seul alias propre à Media Library (pas de filtre).
TYPE_GROUPS = {'all': None}
for _cat in MEDIA_CATEGORIES:
    _members = [t for t, c in ASSET_TYPE_CATEGORY.items() if c == _cat]
    if _members:
        TYPE_GROUPS[_cat] = _members
del _cat, _members


from wama.common.models import ScopedManager, ScopedVisibility


class UserAsset(_AttributesMixin, ScopedVisibility, models.Model):
    """Asset personnel d'un utilisateur, réutilisable dans toutes les apps.
    Hérite de ScopedVisibility : privé par défaut, promouvable vers une unité
    (labo/dépt/université) ou public (médiathèque partagée). Voir §MONDES."""

    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_assets')
    name       = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    file       = models.FileField(
        upload_to=UploadToUserPath('media_library', 'assets'),
        validators=[FileExtensionValidator(allowed_extensions=_ALL_EXTENSIONS)],
    )
    # Ce que l'asset EST, au-delà de son type : clés DÉCLARÉES par sa nature (`natures.py` —
    # une voix : language/age/gender/variant ; un objet 3D : format/rigged/units…). Même
    # construction que `AIModel.capabilities` : une colonne, un vocabulaire, pas de SQL par nature.
    attributes = models.JSONField(default=dict, blank=True,
                                  help_text="Attributs déclarés par la nature (voir natures.py)")
    mime_type  = models.CharField(max_length=100, blank=True)
    file_size  = models.PositiveBigIntegerField(default=0)         # bytes
    duration   = models.FloatField(null=True, blank=True)          # secondes (voix, vidéo)
    description = models.TextField(blank=True)
    tags       = models.CharField(max_length=500, blank=True)      # CSV "tag1,tag2"
    # ── Attribution ────────────────────────────────────────────────────────────
    # Les 6 fournisseurs (Wikimedia, Openverse, Jamendo, Freesound, Pixabay, Pexels) rendent
    # DÉJÀ `license` et `author` (providers/base.Asset:18-19) ; l'import les entassait dans
    # `tags` et dans le texte libre de `description`. Une licence à attribution y devenait
    # donc ni interrogeable ni fiable, alors que citer l'auteur est justement ce que CC-BY
    # EXIGE. Champs ajoutés le 2026-08-12 ; `tags` garde les siens (recherche plein texte).
    license    = models.CharField(max_length=100, blank=True, help_text="CC0, CC-BY, etc.")
    author     = models.CharField(max_length=200, blank=True,
                                  help_text="Auteur à créditer (obligatoire pour les licences à attribution).")
    source_url = models.URLField(blank=True, max_length=1000,
                                 help_text="Page d'origine — la citation complète l'exige aussi.")
    # ── Provenance d'une SORTIE D'APP rangée (2026-09-14, demande de Fabien) ────────
    # L'élément d'app dont cet asset est la sortie (`services.export_item_to_library`). C'est ce
    # qui permet au menu « … » de la card de DIRE « déjà dans la médiathèque » (une coche) et
    # d'offrir le RETRAIT sans aller dans la médiathèque. Le nom ne le permettait pas : il est
    # renommable, et deux éléments peuvent rendre un fichier de même nom. Vide pour un dépôt
    # direct ou un import de fournisseur.
    source_app = models.CharField(max_length=50, blank=True, default='')
    source_pk  = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ⚠ Le mixin de visibilité était posé depuis des mois, mais le MANAGER manquait : sans lui,
    # `UserAsset.objects.visible_to(user)` n'existe pas, et TOUTES les lectures filtraient par
    # propriétaire. Un partage était donc écrit et jamais lu — il ne montrait rien, sans erreur
    # (mesuré le 2026-09-20). C'est exactement le mode de panne que les deux chemins nommés de
    # `common/utils/scoping.py` existent pour rendre impossible. Aucune migration : un manager
    # n'est pas un champ.
    objects = ScopedManager()

    class Meta:
        verbose_name = 'Asset utilisateur'
        verbose_name_plural = 'Assets utilisateurs'
        ordering = ['asset_type', 'name']
        unique_together = [['user', 'name', 'asset_type']]
        indexes = [
            models.Index(fields=['user', 'asset_type']),
            models.Index(fields=['created_at']),
            models.Index(fields=['user', 'source_app', 'source_pk']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_asset_type_display()}) — {self.user.username}"

    @property
    def file_size_display(self):
        """Taille lisible (Ko, Mo)."""
        if self.file_size < 1024:
            return f"{self.file_size} o"
        if self.file_size < 1024 ** 2:
            return f"{self.file_size / 1024:.1f} Ko"
        return f"{self.file_size / 1024 ** 2:.1f} Mo"

    @property
    def duration_display(self):
        if not self.duration:
            return ''
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"


class SystemAsset(_AttributesMixin, models.Model):
    """
    Asset générique partagé par tous les utilisateurs.
    Géré par les admins ou par téléchargement automatique.
    Non supprimable par les utilisateurs finaux.
    """

    name       = models.CharField(max_length=200, unique=True)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPES)
    file       = models.FileField(upload_to='media_library/system/')
    attributes = models.JSONField(default=dict, blank=True,
                                  help_text="Attributs déclarés par la nature (voir natures.py)")
    mime_type  = models.CharField(max_length=100, blank=True)
    file_size  = models.PositiveBigIntegerField(default=0)
    duration   = models.FloatField(null=True, blank=True)
    description = models.TextField(blank=True)
    tags       = models.CharField(max_length=500, blank=True)
    source_url = models.URLField(blank=True, help_text="URL d'origine pour re-téléchargement")
    license    = models.CharField(max_length=100, blank=True, help_text="CC0, CC-BY, etc.")
    # Les 6 fournisseurs renseignent DÉJÀ `author` (providers/base.Asset:19) et l'enregistrement
    # le jetait : on stockait « CC-BY » sans le nom à créditer, alors que l'attribution est
    # précisément ce que cette licence EXIGE. Champ ajouté le 2026-08-12.
    author     = models.CharField(max_length=200, blank=True,
                                  help_text="Auteur à créditer (obligatoire pour les licences à attribution).")
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Asset système'
        verbose_name_plural = 'Assets système'
        ordering = ['asset_type', 'name']
        indexes = [
            models.Index(fields=['asset_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_asset_type_display()}) [système]"

    @property
    def file_size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} o"
        if self.file_size < 1024 ** 2:
            return f"{self.file_size / 1024:.1f} Ko"
        return f"{self.file_size / 1024 ** 2:.1f} Mo"

    @property
    def duration_display(self):
        if not self.duration:
            return ''
        m, s = divmod(int(self.duration), 60)
        return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Phase 3 — Providers (sources externes)
# ---------------------------------------------------------------------------

class MediaProvider(models.Model):
    """
    Catalogue des connecteurs/sources media disponibles (Wikimedia, Pixabay, Freesound, …).
    Créé via data migration — ne pas modifier manuellement en prod.
    """
    slug        = models.SlugField(unique=True)
    name        = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # JSON list of asset_type values this provider supports, e.g. ['image', 'video']
    supported_types  = models.JSONField(default=list)
    requires_api_key = models.BooleanField(default=True)
    # Where the user can obtain an API key
    api_key_help_url = models.URLField(blank=True)
    # Label displayed on the profile page
    api_key_label    = models.CharField(max_length=100, blank=True, default='Clé API')
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fournisseur media'
        verbose_name_plural = 'Fournisseurs media'
        ordering = ['name']

    def __str__(self):
        return self.name


class UserProviderConfig(models.Model):
    """Clé API personnelle d'un utilisateur pour un provider donné."""
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='provider_configs')
    provider = models.ForeignKey(MediaProvider, on_delete=models.CASCADE, related_name='user_configs')
    # Chiffrée au repos depuis le 2026-09-15 (elle l'était en CLAIR). Les vues lisent toujours
    # `cfg.api_key` en clair : le champ déchiffre. Aucune recherche sur la valeur, sauf le vide.
    api_key  = EncryptedTextField(blank=True)
    is_active   = models.BooleanField(default=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Config provider utilisateur'
        verbose_name_plural = 'Configs providers utilisateurs'
        unique_together = [['user', 'provider']]

    def __str__(self):
        return f"{self.user.username} — {self.provider.name}"


class PromptKeyword(models.Model):
    """
    Mot-clé réutilisable pour enrichir un prompt (chips cliquables).
    Vit dans la médiathèque : `user=None` = TRONC COMMUN partagé (seedé) ; sinon = perso utilisateur.
    Pas un asset fichier → modèle dédié (texte). Surfacé via la palette commune + l'UI médiathèque.
    """
    CATEGORY_CHOICES = [
        ('quality', 'Qualité'),
        ('style', 'Style'),
        ('light', 'Lumière'),
        ('mood', 'Ambiance'),
        ('camera', 'Caméra / objectif'),
        ('render', 'Rendu / époque'),
        ('domain', 'Domaine'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name='prompt_keywords',
        help_text="null = tronc commun partagé (système) ; sinon = mot-clé perso de l'utilisateur",
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='style', db_index=True)
    text = models.CharField(max_length=120, help_text="Le mot-clé inséré dans le prompt")
    domain = models.CharField(
        max_length=30, blank=True, default='',
        help_text="Optionnel : domaine d'application (ex. 'image', 'video', 'transport')",
    )
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mot-clé de prompt'
        verbose_name_plural = 'Mots-clés de prompt'
        ordering = ['category', 'order', 'text']
        unique_together = [['user', 'category', 'text']]

    def __str__(self):
        scope = 'commun' if self.user_id is None else self.user.username
        return f"[{self.category}/{scope}] {self.text}"

    def to_dict(self):
        return {'id': self.id, 'category': self.category, 'text': self.text,
                'domain': self.domain, 'shared': self.user_id is None}
