"""
Modération des nouveaux comptes + journal d'accès (point 1 MONDES/accès).

- Nouvel utilisateur LDAP → inactif (WamaLDAPBackend) → email aux modérateurs.
- Activation par un admin (is_active False→True) → email de bienvenue.
- Journal des connexions/déconnexions (`AccessLog`).

Tolérant aux pannes : un échec d'email ne bloque JAMAIS le login/l'activation.
Connecté via `accounts/apps.py::ready`.
"""
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.signals import (user_logged_in, user_logged_out,
                                         user_login_failed)
from django.core.mail import send_mail
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _moderator_emails():
    """Destinataires des notifications de modération : WAMA_MODERATOR_EMAILS,
    sinon les emails des superusers actifs."""
    emails = list(getattr(settings, 'WAMA_MODERATOR_EMAILS', []) or [])
    if not emails:
        emails = list(User.objects.filter(is_superuser=True, is_active=True)
                      .exclude(email='').values_list('email', flat=True))
    return [e for e in emails if e]


def _safe_send(subject, body, recipients):
    """Envoi email best-effort (jamais bloquant)."""
    recipients = [r for r in (recipients or []) if r]
    if not recipients:
        logger.info('email « %s » non envoyé : aucun destinataire', subject)
        return
    try:
        send_mail(subject, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                  recipients, fail_silently=False)
    except Exception:
        logger.warning('envoi email « %s » échoué', subject, exc_info=True)


# ── Modération : nouvel utilisateur en attente ────────────────────────────────

@receiver(post_save, sender=User)
def _notify_new_pending(sender, instance, created, **kwargs):
    if created and getattr(instance, '_wama_new_pending', False):
        instance._wama_new_pending = False
        name = instance.get_full_name() or instance.get_username()
        _safe_send(
            f'[WAMA] Nouveau compte à valider : {name}',
            f"Un nouvel utilisateur s'est connecté et attend votre validation.\n\n"
            f"Identifiant : {instance.get_username()}\n"
            f"Nom : {name}\nEmail : {instance.email or '—'}\n\n"
            f"Activez le compte depuis l'admin Django (Utilisateurs → cocher « Actif »).",
            _moderator_emails())
        logger.info('modération : notification envoyée pour %s', instance.get_username())


# ── Email de bienvenue à l'activation (is_active False → True) ─────────────────

@receiver(pre_save, sender=User)
def _capture_old_active(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_active = User.objects.get(pk=instance.pk).is_active
        except User.DoesNotExist:
            instance._old_active = None


@receiver(post_save, sender=User)
def _welcome_on_activation(sender, instance, created, **kwargs):
    if created:
        return
    if getattr(instance, '_old_active', None) is False and instance.is_active:
        if instance.email:
            _safe_send(
                '[WAMA] Votre compte est activé',
                f"Bonjour {instance.get_full_name() or instance.get_username()},\n\n"
                f"Votre compte WAMA a été validé. Vous pouvez maintenant vous connecter.\n",
                [instance.email])
        logger.info('compte %s activé → email de bienvenue', instance.get_username())


# ── Journal d'accès ───────────────────────────────────────────────────────────

def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')) or None


def _log(user, event, request):
    try:
        from .models import AccessLog
        AccessLog.objects.create(
            user=user if getattr(user, 'pk', None) else None,
            username=getattr(user, 'username', '') if user else '',
            event=event, ip=_client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT', '')[:256] if request else ''))
    except Exception:
        logger.debug('AccessLog échoué', exc_info=True)


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    _log(user, 'login', request)


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    _log(user, 'logout', request)


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    # Tentative sur un compte inactif (en attente de modération) ou identifiants faux.
    uname = (credentials or {}).get('username', '')
    if uname:
        _log(None, 'login_denied', request)
