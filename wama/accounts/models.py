from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django import forms

from wama.common.tts.constants import LANGUAGE_CHOICES
from wama.accounts.permissions import TIER_CHOICES


class UserProfile(models.Model):
    """
    WAMA-wide user preferences (cross-app).
    Distinct from anonymizer.UserSettings which is anonymizer-specific.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    preferred_language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default='fr',
        verbose_name='Langue préférée',
    )
    ui_mode = models.CharField(
        max_length=16,
        choices=[('advanced', 'Mode Avancé'), ('simple', 'Mode Simplifié')],
        default='advanced',
        verbose_name="Mode d'interface",
    )
    # Géométrie d'affichage des files (ligne = 1/rangée ; mosaïque = grille de cards hautes).
    card_layout = models.CharField(
        max_length=8,
        choices=[('list', 'Ligne'), ('grid', 'Mosaïque')],
        default='list',
        verbose_name="Disposition des cards",
    )
    # Lecture auto de l'aperçu (audio/vidéo) dans l'inspecteur au clic d'une card.
    # Défaut OFF (opt-in) le temps de valider l'absence de lag ; à basculer ON ensuite.
    inspector_autoplay = models.BooleanField(
        default=False,
        verbose_name="Lecture auto de l'aperçu dans l'inspecteur",
    )
    # Axe A — profil de compte (tier). Les rôles métier (axe B) = Django Groups 'role:*'.
    account_tier = models.CharField(
        max_length=16,
        choices=TIER_CHOICES,
        default='utilisateur',
        db_index=True,
        verbose_name='Profil de compte',
    )
    # Axe C — APPARTENANCE ORGANISATIONNELLE (remontée du LDAP/SUPANN au login).
    # Colonne vertébrale : mêmes unités que l'héritage RAG + les scopes de partage
    # médiathèque (labo/service/département/université). Voir docs/VISION_STATUS.md §MONDES.
    establishment = models.CharField(
        max_length=128, blank=True, default='',
        verbose_name='Établissement', help_text='supannEtablissement (université).')
    org_entity_code = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        verbose_name='Entité principale (code)',
        help_text='supannEntiteAffectationPrincipale (labo/service de rattachement).')
    org_entity_name = models.CharField(
        max_length=192, blank=True, default='',
        verbose_name='Entité principale', help_text='Nom lisible de l\'entité principale.')
    org_affiliations = models.JSONField(
        default=list, blank=True,
        verbose_name='Rattachements',
        help_text='supannEntiteAffectation — liste de codes (tous les rattachements).')
    org_hierarchy = models.JSONField(
        default=list, blank=True,
        verbose_name='Hiérarchie organisationnelle',
        help_text='Chaîne institut→département→labo→équipe résolue depuis ou=structures '
                  '[{code, name, type}], du plus large au plus fin.')
    ldap_affiliation = models.CharField(
        max_length=64, blank=True, default='',
        verbose_name='Affiliation LDAP',
        help_text='eduPersonPrimaryAffiliation (researcher/faculty/staff/student…) — aide au rôle.')

    def org_path(self):
        """Chaîne lisible institut → … → équipe (depuis org_hierarchy, sinon entité principale)."""
        if self.org_hierarchy:
            return ' → '.join(u.get('name') or u.get('code') for u in self.org_hierarchy)
        return self.org_entity_name or self.org_entity_code or ''

    # Notifications email (fin/échec des traitements longs).
    notify_email = models.BooleanField(default=True, verbose_name='Notifications par email')
    notify_on = models.CharField(
        max_length=12,
        choices=[('both', 'Fin et échec'), ('completion', 'Fin seulement'),
                 ('failure', 'Échec seulement'), ('none', 'Aucune')],
        default='both',
        verbose_name='Quand notifier',
    )

    # Rétention des médias (purge automatique). 0 = illimité ; bornée par WAMA_MAX_RETENTION_DAYS.
    media_retention_days = models.PositiveIntegerField(
        default=0,
        verbose_name='Conservation des médias (jours)',
        help_text="0 = illimité. Au-delà, les sorties sont purgées automatiquement.",
    )

    def effective_retention_days(self):
        """Rétention effective = min(choix user, plafond admin) ; 0 = illimité des deux côtés."""
        from django.conf import settings
        cap = int(getattr(settings, 'WAMA_MAX_RETENTION_DAYS', 0) or 0)
        user = int(self.media_retention_days or 0)
        if user and cap:
            return min(user, cap)
        return user or cap

    def wants_notification(self, success):
        """L'utilisateur veut-il être notifié pour cet événement (succès/échec) ?"""
        if not self.notify_email or self.notify_on == 'none':
            return False
        if success:
            return self.notify_on in ('both', 'completion')
        return self.notify_on in ('both', 'failure')

    def __str__(self):
        return f"Profile({self.user.username})"


class AppAccessPolicy(models.Model):
    """
    Politique d'accès d'une app (mapping app→rôles éditable dans l'interface utilisateurs).
    Source de vérité runtime de `permissions.accessible()` ; seedée depuis DEFAULT_APP_ACCESS.
    """
    app_id = models.CharField(max_length=64, unique=True, verbose_name='Application')
    roles = models.ManyToManyField(
        'auth.Group', blank=True, related_name='app_policies',
        verbose_name='Rôles métier autorisés',
        help_text="Vide = app commune (tout compte authentifié).",
    )
    public = models.BooleanField(default=False, verbose_name='Visible aux anonymes (démo)')
    min_tier = models.CharField(
        max_length=16, blank=True, default='', choices=TIER_CHOICES,
        verbose_name='Tier minimal requis',
        help_text="Vide = aucun minimum (ex. model_manager → développeur).",
    )

    class Meta:
        verbose_name = "Politique d'accès app"
        verbose_name_plural = "Politiques d'accès apps"
        ordering = ['app_id']

    def __str__(self):
        return f"AppAccessPolicy({self.app_id})"


@receiver(post_save, sender=User)
def create_user_profile_signal(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class AccessLog(models.Model):
    """Journal d'accès : trace les connexions (traçabilité recherche + responsabilité RGPD).
    Complète `User.date_joined` (inscription) et `User.last_login` déjà fournis par Django."""
    EVENT_CHOICES = [('login', 'Connexion'), ('logout', 'Déconnexion'),
                     ('login_denied', 'Connexion refusée (compte inactif)')]
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='access_logs')
    username = models.CharField(max_length=150, blank=True, default='')   # conservé si user supprimé
    event = models.CharField(max_length=16, choices=EVENT_CHOICES, default='login')
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True, default='')
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Journal d'accès"

    def __str__(self):
        return f'{self.username or self.user_id} · {self.event} · {self.timestamp:%Y-%m-%d %H:%M}'


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "User ID (forname.name)"})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': "Password"})
    )


class UserRegistrationForm(UserCreationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Nom d'utilisateur"})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': "Email"})
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': "Mot de passe"})
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': "Confirmer le mot de passe"})
    )

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Les deux mots de passe saisis ne sont pas identiques", code='password_mismatch')
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            # Optionnel : ajout automatique à un groupe
            # group = Group.objects.get(name='default_users')
            # user.groups.add(group)
        return user


def group_required(*group_names):
    """
    Checks whether the user belongs to one of the given groups, or is a superuser.
    """
    def in_groups(u):
        return u.is_authenticated and (u.is_superuser or u.groups.filter(name__in=group_names).exists())

    return user_passes_test(in_groups, login_url='accounts:signin')
