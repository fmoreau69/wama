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


# ── L'ÉTAT d'un compte ────────────────────────────────────────────────────────

#: L'état d'un compte, clé → libellé — LA lecture de la page des utilisateurs, de la lecture de
#: l'annuaire par unité (`directory.with_account_state`) et de la constellation. Un compte
#: inactif n'est pas « inactif » tout court : PRÉ-INSCRIT, personne n'a rien demandé (un
#: administrateur l'a préparé depuis l'annuaire) ; EN ATTENTE, sa titulaire est venue et attend ;
#: DÉSACTIVÉ, il a servi et un administrateur l'a fermé (2026-11-25).
STATE_ACTIVE, STATE_PENDING, STATE_PREREGISTERED, STATE_DISABLED = (
    'active', 'pending', 'preregistered', 'disabled')
ACCOUNT_STATES = {STATE_ACTIVE: 'Actif', STATE_PENDING: 'En attente',
                  STATE_PREREGISTERED: 'Pré-inscrit', STATE_DISABLED: 'Désactivé'}


def accounts_that_asked(user_ids) -> set:
    """Parmi `user_ids`, les comptes dont la titulaire est VENUE sans pouvoir entrer : une demande
    de modération existe (lue ou non), ou le journal garde un refus où elle avait prouvé son
    identité (`pending_login` — la ligne porte le compte ; un mot de passe faux, lui, ne laisse
    qu'un nom, et ne fait pas d'un compte pré-inscrit un compte en attente)."""
    from wama.common.models import Notification

    from .models import AccessLog
    ids = list(user_ids)
    if not ids:
        return set()
    asked = {int(pk) for pk in Notification.objects.filter(
        kind=ACCOUNT_PENDING_KIND, object_type='User', object_id__in=[str(pk) for pk in ids],
    ).values_list('object_id', flat=True) if str(pk).isdigit()}
    asked.update(AccessLog.objects.filter(user_id__in=ids, event='login_denied')
                 .values_list('user_id', flat=True))
    return asked


def account_states(users) -> dict:
    """`{pk: état}` pour `users` — deux lectures en base pour toute la liste, quel que soit son
    nombre. Pré-inscrit : un compte d'ANNUAIRE (`permissions.is_directory_account`), inactif,
    jamais entré, et que personne n'a demandé."""
    from .permissions import is_directory_account
    users = list(users)
    never_came = [u for u in users if not u.is_active and u.last_login is None]
    asked = accounts_that_asked(u.pk for u in never_came)
    states = {}
    for user in users:
        if user.is_active:
            states[user.pk] = STATE_ACTIVE
        elif user.last_login is not None:
            states[user.pk] = STATE_DISABLED
        elif user.pk in asked:
            states[user.pk] = STATE_PENDING
        elif is_directory_account(user):
            states[user.pk] = STATE_PREREGISTERED
        else:
            states[user.pk] = STATE_DISABLED
    return states


def account_state(user) -> str:
    """L'état d'UN compte (`account_states`)."""
    return account_states([user])[user.pk]


def activate_accounts(users, *, protected=()) -> dict:
    """Active chaque compte INACTIF de `users` — le geste « Activer » d'une ligne, pour une
    sélection. Rend `{'activated': […], 'skipped': […]}` (identifiants). Un compte de service
    pour visiteur et les comptes `protected` (celui de l'administrateur qui agit) ne se touchent
    pas ; un compte déjà actif est laissé tel quel. Chaque activation envoie le message de
    bienvenue (`_welcome_on_activation`), comme le bouton de la ligne."""
    from .permissions import is_guest_account
    spared = {getattr(u, 'pk', u) for u in protected}
    report = {'activated': [], 'skipped': []}
    for user in users:
        if user.is_active or user.pk in spared or is_guest_account(user):
            report['skipped'].append(user.get_username())
            continue
        user.is_active = True
        user.save()
        report['activated'].append(user.get_username())
    if report['activated']:
        logger.info('activation en lot : %s compte(s)', len(report['activated']))
    return report


# ── Email de bienvenue à l'activation (is_active False → True) ─────────────────

#: Ce que lit, à l'activation, une personne qui n'a RIEN demandé (compte pré-inscrit) : c'est son
#: premier contact avec WAMA. Elle apprend que le compte existe, ce qu'il porte, d'où cela vient
#: et comment s'y opposer (décision de Fabien, 2026-11-25).
PREREGISTERED_WELCOME = (
    "Bonjour {name},\n\n"
    "Un compte WAMA a été préparé pour vous par un administrateur de la plateforme, et il vient "
    "d'être activé. WAMA est la plateforme de traitement de médias et d'IA de votre laboratoire. "
    "Vous pouvez vous y connecter avec vos identifiants habituels de l'établissement{address}.\n\n"
    "Ce que ce compte enregistre aujourd'hui, repris de l'annuaire de l'établissement : votre "
    "identifiant, votre prénom, votre nom, votre adresse électronique et votre unité de "
    "rattachement. Rien d'autre : à votre première connexion, WAMA vous montrera ce que "
    "l'annuaire peut y ajouter, et c'est vous qui choisirez — y compris de retirer votre unité.\n\n"
    "Vous n'avez rien à faire si vous ne souhaitez pas vous en servir. Pour faire supprimer ce "
    "compte et ces informations, ou pour toute question, {contact}.\n")


def _welcome_text(user, asked: bool) -> str:
    name = user.get_full_name() or user.get_username()
    if asked:
        return (f"Bonjour {name},\n\n"
                f"Votre compte WAMA a été validé. Vous pouvez maintenant vous connecter.\n")
    address = (getattr(settings, 'WAMA_PUBLIC_URL', '') or '').strip()
    moderators = list(getattr(settings, 'WAMA_MODERATOR_EMAILS', []) or [])
    return PREREGISTERED_WELCOME.format(
        name=name, address=f' ({address})' if address else '',
        contact=(f'écrivez à {moderators[0]}' if moderators
                 else "adressez-vous à un administrateur de WAMA"))


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
        # Une personne jamais venue et qui n'a rien demandé ne lit pas « votre compte a été
        # validé » : elle apprend qu'il existe (`PREREGISTERED_WELCOME`).
        came = instance.last_login is not None or instance.has_usable_password()
        asked = came or instance.pk in accounts_that_asked([instance.pk])
        notify_user(instance, '[WAMA] Votre compte est activé' if asked
                    else '[WAMA] Un compte a été préparé pour vous',
                    _welcome_text(instance, asked))
        logger.info('compte %s activé → email de bienvenue', instance.get_username())


# ── Journal d'accès ───────────────────────────────────────────────────────────

def client_address(request):
    """L'adresse du client — LA lecture, pour le journal des connexions et le frein des visiteurs.

    La DERNIÈRE adresse de `X-Forwarded-For`, celle qu'ajoute le frontal (Apache AJOUTE l'adresse
    qu'il voit à ce que le client a envoyé) ; à défaut `REMOTE_ADDR`. La première est celle que le
    CLIENT écrit : la lire laissait une requête choisir son adresse — mesuré le 2026-11-06 (audit de
    sécurité), un en-tête tournant faisait passer 63 identités de visiteur sous une borne de 30.
    ⚠ Un appel DIRECT à gunicorn (sans frontal) garde un en-tête entièrement choisi par le client :
    seule l'écoute de gunicorn sur la boucle locale le ferme."""
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    last = xff.split(',')[-1].strip() if xff else ''
    return last or request.META.get('REMOTE_ADDR') or None



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
    if not client_address(request) and not agent:
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
            event=event, ip=client_address(request),
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
    clear_login_failures(user.get_username())
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
        _count_login_failure(uname)
        _log(None, 'login_denied', request, username=uname, reason=denial_reason(uname))


# ── Frein de connexion (2026-11-06, audit de sécurité) ─────────────────────────
# Aucune borne n'existait : 40 mots de passe faux de suite, puis le bon, passaient (mesuré, par le
# formulaire comme par `/api/v1/auth/token/`) — un essai illimité contre l'annuaire de l'université.
# Le compte se tient PAR IDENTIFIANT, dans le cache partagé des workers : l'adresse d'un client se
# choisit (`client_address`), l'identifiant visé non. Il s'applique à TOUTE surface, parce qu'il
# est lu par un moteur d'authentification placé en tête (`ldap_backend.LoginBrakeBackend`).
# ⚠ Contrepartie connue : un tiers peut freiner un identifiant qu'il ne connaît pas le mot de
# passe — pour la durée de la fenêtre, jamais au-delà ; une connexion réussie remet le compte à 0.

def login_failures_limit() -> int:
    return int(getattr(settings, 'WAMA_LOGIN_FAILURES_LIMIT', 10))


def login_brake_seconds() -> int:
    return int(getattr(settings, 'WAMA_LOGIN_BRAKE_SECONDS', 900))


def _brake_key(username: str) -> str:
    return f'wama_login_failures:{(username or "").strip().lower()}'


def _count_login_failure(username: str) -> None:
    from django.core.cache import cache
    key = _brake_key(username)
    if not cache.add(key, 1, timeout=login_brake_seconds()):
        try:
            cache.incr(key)
        except ValueError:                     # expirée entre `add` et `incr`
            cache.set(key, 1, timeout=login_brake_seconds())


def login_braked(username: str) -> bool:
    """Cet identifiant a-t-il atteint la borne d'échecs récents ? Lu avant toute vérification du
    mot de passe : un identifiant freiné ne se vérifie plus, même avec le bon."""
    from django.core.cache import cache
    return bool(username) and (cache.get(_brake_key(username)) or 0) >= login_failures_limit()


def clear_login_failures(username: str) -> None:
    from django.core.cache import cache
    cache.delete(_brake_key(username))
