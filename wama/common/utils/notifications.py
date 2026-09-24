"""
Notifications utilisateur (email) — brique commune, métadonnée/préférence-driven.

`notify_job(user, app_label, item_name, success, ...)` est le point d'entrée pour les apps :
à appeler à la **fin/échec d'un traitement long** (dans la tâche Celery), il respecte les
préférences du profil (`UserProfile.wants_notification`) et envoie un email **fail-safe**
(n'interrompt jamais la tâche). Le transport email est piloté par `settings` (SMTP UGE / console).
"""
import logging

logger = logging.getLogger(__name__)


def notify_emails(recipients, subject, body, html=None):
    """Envoie un email à une liste d'ADRESSES (pas forcément des Users) — ex. modérateurs.
    Fail-safe (jamais d'exception), transport piloté par settings. Point d'envoi commun."""
    try:
        recipients = [e for e in (recipients or []) if e]
        if not recipients:
            return False
        from django.core.mail import EmailMultiAlternatives
        from django.conf import settings
        msg = EmailMultiAlternatives(subject, body,
                                     getattr(settings, 'DEFAULT_FROM_EMAIL', None), recipients)
        if html:
            msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=True)
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("notify_emails a échoué : %s", e)
        return False


def notify_user(user, subject, body, html=None):
    """Envoie un email à l'utilisateur si une adresse est disponible. Fail-safe (jamais d'exception)."""
    return notify_emails([getattr(user, 'email', '') or ''], subject, body, html)


def notify_in_app(users, kind, title, body='', url=''):
    """Crée une notification DANS WAMA pour chaque utilisateur (`common.Notification`, badge de
    l'en-tête + page `/common/notifications/`). Fail-safe ; rend le nombre créé."""
    try:
        from wama.common.models import Notification
        rows = [Notification(recipient=u, kind=kind, title=title[:255], body=body or '',
                             url=url or '')
                for u in (users or []) if getattr(u, 'pk', None)]
        Notification.objects.bulk_create(rows)
        return len(rows)
    except Exception as e:  # pragma: no cover
        logger.warning("notify_in_app a échoué : %s", e)
        return 0


def infrastructure_admins():
    """Les comptes qui administrent l'infrastructure : ceux que la politique d'accès laisse
    entrer au model manager (même point de décision que ses 52 vues, `accessible`)."""
    from django.contrib.auth import get_user_model
    from wama.accounts.permissions import accessible
    return [u for u in get_user_model().objects.filter(is_active=True)
            if accessible(u, 'app', 'model_manager')]


def notify_admins(kind, subject, body, url=''):
    """Prévient les administrateurs de l'infrastructure DANS WAMA et par e-mail. Fail-safe ;
    rend (notifications créées, e-mail envoyé)."""
    try:
        admins = infrastructure_admins()
    except Exception as e:  # pragma: no cover
        logger.warning("notify_admins : destinataires illisibles (%s)", e)
        return 0, False
    created = notify_in_app(admins, kind, subject, body, url)
    sent = notify_emails([a.email for a in admins], f"[WAMA] {subject}", body)
    return created, sent


def notify_job(user, app_label, item_name, success, detail='', url=''):
    """
    Notifie la fin (ou l'échec) d'un traitement, en respectant les préférences du profil.
    - app_label : nom lisible de l'app (ex. « Transcriber »).
    - item_name : nom de l'élément traité.
    - success   : bool.
    - detail    : message court (ex. résumé / cause d'échec).
    - url       : lien absolu vers le résultat (optionnel).
    """
    try:
        if user is None or not getattr(user, 'is_authenticated', True):
            return False
        prof = getattr(user, 'profile', None)
        if prof is None or not prof.wants_notification(success):
            return False

        state = 'terminé' if success else 'a échoué'
        subject = f"[WAMA] {app_label} — « {item_name} » {state}"
        lines = [
            f"Bonjour {getattr(user, 'username', '')},",
            "",
            f"Votre traitement {app_label} pour « {item_name} » {state}.",
        ]
        if detail:
            lines += ["", detail]
        if url:
            lines += ["", f"Résultat : {url}"]
        lines += ["", "— WAMA"]
        body = "\n".join(lines)
        return notify_user(user, subject, body)
    except Exception as e:  # pragma: no cover
        logger.warning("notify_job a échoué : %s", e)
        return False
