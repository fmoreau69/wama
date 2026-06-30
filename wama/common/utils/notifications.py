"""
Notifications utilisateur (email) — brique commune, métadonnée/préférence-driven.

`notify_job(user, app_label, item_name, success, ...)` est le point d'entrée pour les apps :
à appeler à la **fin/échec d'un traitement long** (dans la tâche Celery), il respecte les
préférences du profil (`UserProfile.wants_notification`) et envoie un email **fail-safe**
(n'interrompt jamais la tâche). Le transport email est piloté par `settings` (SMTP UGE / console).
"""
import logging

logger = logging.getLogger(__name__)


def notify_user(user, subject, body, html=None):
    """Envoie un email à l'utilisateur si une adresse est disponible. Fail-safe (jamais d'exception)."""
    try:
        email = getattr(user, 'email', '') or ''
        if not email:
            return False
        from django.core.mail import EmailMultiAlternatives
        from django.conf import settings
        msg = EmailMultiAlternatives(subject, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None), [email])
        if html:
            msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=True)
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("notify_user a échoué : %s", e)
        return False


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
