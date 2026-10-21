"""
Modération des nouveaux comptes + journal d'accès (point 1 MONDES/accès).
Doc : `PROFILES_PERMISSIONS.md §Modération à la première connexion`.

- Nouvel utilisateur LDAP → inactif (WamaLDAPBackend) → demande de modération : email aux
  modérateurs ET notification DANS WAMA aux administrateurs (`request_moderation`).
- Le compte en attente qui se reconnecte apprend qu'il attend (formulaire de connexion), la
  tentative est journalisée, et la demande est reposée si elle s'était perdue (`pending_login`).
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
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

# Brique commune d'envoi (fail-safe, transport centralisé) — ne PAS réinventer.
from wama.common.utils.notifications import notify_user, notify_emails

logger = logging.getLogger(__name__)


def _moderator_emails():
    """Destinataires des notifications de modération : WAMA_MODERATOR_EMAILS,
    sinon les emails des ADMINISTRATEURS actifs (`permissions.administrators`, le niveau du
    profil — il lisait le drapeau superutilisateur, une autre définition, 2026-10-21)."""
    from wama.accounts.permissions import administrators
    emails = list(getattr(settings, 'WAMA_MODERATOR_EMAILS', []) or [])
    if not emails:
        emails = [u.email for u in administrators() if u.email]
    return [e for e in emails if e]


# ── Modération : nouvel utilisateur en attente ────────────────────────────────

#: Type de la notification DANS WAMA d'un compte à valider (`common.Notification.kind`).
ACCOUNT_PENDING_KIND = 'account_pending'

#: Ce que lit le compte en attente qui se connecte : il n'a pas fait d'erreur.
PENDING_MESSAGE = ("Votre compte WAMA est en attente de validation par un administrateur, qui en "
                   "est prévenu. Vous pourrez vous connecter dès qu'il l'aura activé.")


def account_moderators():
    """Les comptes qui peuvent ACTIVER un compte — le prédicat de la vue qui le fait
    (`views.user_toggle_active`, `@admin_required` → `views.is_admin`), pour que la demande
    n'arrive qu'à ceux qui peuvent y répondre. La lecture commune des administrateurs
    (`permissions.administrators`), celle de la promotion aussi (2026-10-21)."""
    from wama.accounts.permissions import administrators
    return administrators()


def request_moderation(user) -> dict:
    """Demande aux modérateurs de valider le compte `user` : notification DANS WAMA (cloche, page
    des notifications) aux administrateurs, email aux adresses de modération. Rend
    `{'in_app': n, 'email': bool}`.

    Une fois par compte : une notification NON LUE existe déjà → rien de plus (le compte qui
    retente sa connexion ne relance pas tout le monde). La voie DANS WAMA est celle qui ne se perd
    pas — le 2026-10-20, deux comptes attendaient sans que personne le sache : l'email seul était
    parti nulle part (compte d'envoi sans mot de passe, refus avalé par `fail_silently`)."""
    from django.urls import reverse

    from wama.common.models import Notification
    from wama.common.utils.notifications import notify_in_app
    if Notification.objects.filter(kind=ACCOUNT_PENDING_KIND, object_type='User',
                                   object_id=str(user.pk), read_at__isnull=True).exists():
        return {'in_app': 0, 'email': False}
    name = user.get_full_name() or user.get_username()
    url = reverse('accounts:user-management')
    body = (f"Un nouvel utilisateur s'est connecté et attend votre validation.\n\n"
            f"Identifiant : {user.get_username()}\n"
            f"Nom : {name}\nEmail : {user.email or '—'}\n\n"
            f"Activez le compte depuis la page Utilisateurs de WAMA ({url}).")
    created = notify_in_app(account_moderators(), ACCOUNT_PENDING_KIND,
                            f'Nouveau compte à valider : {name}', body=body, url=url,
                            object_type='User', object_id=user.pk)
    sent = notify_emails(_moderator_emails(), f'[WAMA] Nouveau compte à valider : {name}', body)
    logger.info('modération de %s demandée : %s notification(s), email %s',
                user.get_username(), created, 'parti' if sent else 'NON parti')
    return {'in_app': created, 'email': sent}


@receiver(post_save, sender=User)
def _notify_new_pending(sender, instance, created, **kwargs):
    if created and getattr(instance, '_wama_new_pending', False):
        instance._wama_new_pending = False
        request_moderation(instance)


def pending_login(user, request=None) -> None:
    """Un compte EN ATTENTE vient de prouver son identité (l'annuaire a accepté son mot de passe)
    et ne peut pas entrer. La tentative est journalisée — Django n'émet pas `user_login_failed`
    quand le moteur rend un compte inactif, elle n'apparaissait nulle part — et la demande de
    modération est reposée si elle n'attend plus aucun administrateur."""
    _log(user, 'login_denied', request, reason='inactive')
    request_moderation(user)


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
        notify_user(
            instance, '[WAMA] Votre compte est activé',
            f"Bonjour {instance.get_full_name() or instance.get_username()},\n\n"
            f"Votre compte WAMA a été validé. Vous pouvez maintenant vous connecter.\n")
        logger.info('compte %s activé → email de bienvenue', instance.get_username())


# ── Journal d'accès ───────────────────────────────────────────────────────────

def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')) or None


def access_kind(user, request, username: str = '') -> str:
    """Ce qu'une ligne du journal DIT de son auteur : compte de test, visiteur sans compte,
    script (aucune adresse NI navigateur : `force_login`, session fabriquée, appel sans
    requête), ou personne. L'ordre compte : un compte de test piloté par un navigateur reste
    un compte de test."""
    from wama.common.services.nightly_tests import TEST_USERNAMES

    from .models import AccessLog
    from .permissions import is_guest_account
    name = getattr(user, 'username', '') or username or ''
    if name in TEST_USERNAMES:
        return AccessLog.KIND_TEST
    if user is not None and is_guest_account(user):
        return AccessLog.KIND_VISITOR
    agent = request.META.get('HTTP_USER_AGENT', '') if request is not None else ''
    if not _client_ip(request) and not agent:
        return AccessLog.KIND_SCRIPT
    return AccessLog.KIND_PERSON


def _backend_name(user) -> str:
    """`ldap` ou `local` — par où l'identité a été vérifiée (attribut posé par `authenticate`)."""
    path = getattr(user, 'backend', '') or ''
    if not path:
        return ''
    return 'ldap' if 'LDAP' in path else 'local'


def denial_reason(username: str) -> str:
    """Pourquoi `username` n'a pas pu se connecter, d'après ce que WAMA SAIT de ce compte.
    Un compte de l'annuaire jamais venu est « inconnu de WAMA » : on ne peut pas distinguer
    ici une faute de frappe d'un mot de passe faux, et on ne le prétend pas."""
    account = User.objects.filter(username__iexact=username).only('is_active').first()
    if account is None:
        return 'unknown_account'
    return 'bad_credentials' if account.is_active else 'inactive'


def _log(user, event, request, *, username: str = '', reason: str = ''):
    try:
        from .models import AccessLog
        AccessLog.objects.create(
            user=user if getattr(user, 'pk', None) else None,
            username=(getattr(user, 'username', '') if user else username)[:150],
            event=event, ip=_client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT', '')[:256] if request else ''),
            kind=access_kind(user, request, username), reason=reason,
            auth_backend=_backend_name(user))
    except Exception:
        logger.debug('AccessLog échoué', exc_info=True)


def purge_access_log(*, days: int = None, dry_run: bool = False) -> dict:
    """Supprime les lignes du journal plus vieilles que la durée de conservation
    (`WAMA_ACCESS_LOG_RETENTION_DAYS`, six mois — décision de Fabien, 2026-10-05). Le journal
    porte des données personnelles (compte, adresse, navigateur, horaires) : il ne se garde
    pas sans limite. Rend `{'cutoff', 'purged'}`."""
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from .models import AccessLog
    days = int(days if days is not None else getattr(settings, 'WAMA_ACCESS_LOG_RETENTION_DAYS', 183))
    cutoff = timezone.now() - timedelta(days=days)
    stale = AccessLog.objects.filter(timestamp__lt=cutoff)
    count = stale.count()
    if count and not dry_run:
        stale.delete()
    return {'cutoff': cutoff.isoformat(), 'purged': count, 'dry_run': dry_run}


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    _log(user, 'login', request)


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    _log(user, 'logout', request)


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    # Tentative sur un compte inactif (en attente de modération) ou identifiants faux.
    # Le NOM tenté et le MOTIF sont gardés (jusqu'au 2026-10-05 la ligne s'écrivait sans nom :
    # un refus ne disait ni qui ni pourquoi). Le mot de passe, lui, ne quitte jamais ce dict.
    uname = (credentials or {}).get('username', '')
    if uname:
        _log(None, 'login_denied', request, username=uname, reason=denial_reason(uname))
