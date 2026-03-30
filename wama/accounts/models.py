from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django import forms

from wama.common.tts.constants import LANGUAGE_CHOICES


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

    def __str__(self):
        return f"Profile({self.user.username})"


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
