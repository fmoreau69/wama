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
    # Axe A — profil de compte (tier). Les rôles métier (axe B) = Django Groups 'role:*'.
    account_tier = models.CharField(
        max_length=16,
        choices=TIER_CHOICES,
        default='utilisateur',
        db_index=True,
        verbose_name='Profil de compte',
    )
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
