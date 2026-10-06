"""
Notifications utilisateur (email) — brique commune, métadonnée/préférence-driven.

`notify_job_end(item, app_id, app_label, item_name, success, ...)` est LE point de fin d'un
traitement (squelette de tâche commun, signal de l'imager) : e-mail et notification dans WAMA
au propriétaire selon ses préférences, puis aux collaborateurs — **fail-safe** (n'interrompt
jamais la tâche). `notify_job` n'en est que le canal e-mail. Le transport email est piloté par
`settings` (SMTP UGE / console).
"""
import logging

logger = logging.getLogger(__name__)

#: Délai MAXIMAL d'un échange SMTP (secondes). « Fail-safe » ne suffit pas : sans délai, un
#: serveur qui ne répond plus fait attendre l'envoi INDÉFINIMENT — une exception ne vient jamais.
#: Vécu le 2026-09-29 : le worker gpu, bloqué 4 h dans la notification de fin d'une card
#: (connexion SMTP établie, aucune réponse), n'a plus rien traité. `settings.EMAIL_TIMEOUT`
#: prime s'il est posé.
SMTP_TIMEOUT_SECONDS = 30


def notify_emails(recipients, subject, body, html=None):
    """Envoie un email à une liste d'ADRESSES (pas forcément des Users) — ex. modérateurs.
    Fail-safe (jamais d'exception), transport piloté par settings. Point d'envoi commun.
    Répondre à un mail de WAMA écrit au support (`WAMA_SUPPORT_EMAIL`) : l'expéditeur est un
    no-reply."""
    try:
        recipients = list(dict.fromkeys(e for e in (recipients or []) if e))
        if not recipients:
            return False
        from django.core.mail import EmailMultiAlternatives, get_connection
        from django.conf import settings
        support = getattr(settings, 'WAMA_SUPPORT_EMAIL', '') or ''
        timeout = getattr(settings, 'EMAIL_TIMEOUT', None) or SMTP_TIMEOUT_SECONDS
        msg = EmailMultiAlternatives(subject, body,
                                     getattr(settings, 'DEFAULT_FROM_EMAIL', None), recipients,
                                     reply_to=[support] if support else None,
                                     connection=get_connection(fail_silently=True, timeout=timeout))
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


#: Les types de notification qui SONNENT dans WAMA, et le son de chacun (2026-10-06, décision de
#: Fabien : les fins de traitement seulement — ce sont celles qu'on attend ; une demande d'accès
#: ou la mort d'un worker restent muettes). Lu par la route que relève la cloche du web
#: (`common.views.api_notifications_recent`) : le navigateur JOUE ce que dit le serveur, il ne
#: connaît aucun type. Un nouveau type sonore = une entrée ici.
SOUND_BY_KIND = {'job_done': 'done', 'job_failed': 'failed'}


def notification_sound(notification, user) -> str:
    """Le son d'une notification pour cet utilisateur : `'done'`, `'failed'`, ou `''` (muette —
    type non sonore, ou son coupé dans son profil)."""
    profile = getattr(user, 'profile', None)
    if profile is None or not getattr(profile, 'notify_sound', True):
        return ''
    return SOUND_BY_KIND.get(getattr(notification, 'kind', ''), '')


def notify_in_app(users, kind, title, body='', url='', *, app='', item=None):
    """Crée une notification DANS WAMA pour chaque utilisateur (`common.Notification`, badge de
    l'en-tête + page `/common/notifications/`). Fail-safe ; rend le nombre créé.

    `app` + `item` : l'ÉLÉMENT dont elle parle (convention `RunOutcome` — type = nom de classe).
    """
    try:
        from wama.common.models import Notification
        element = {'app': app or '',
                   'object_type': type(item).__name__ if item is not None else '',
                   'object_id': str(getattr(item, 'pk', '') or '') if item is not None else ''}
        rows = [Notification(recipient=u, kind=kind, title=title[:255], body=body or '',
                             url=url or '', **element)
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


#: Niveau de compte de chaque audience du staff, et le réglage de son adresse fonctionnelle.
STAFF_AUDIENCES = {
    'admin': ('admin', 'WAMA_ADMIN_EMAILS'),
    'dev': ('developpeur', 'WAMA_DEV_EMAILS'),
}


def staff_emails(audiences=('admin', 'dev')):
    """Adresses d'envoi pour une ou plusieurs audiences du staff : l'adresse FONCTIONNELLE
    déclarée (`WAMA_ADMIN_EMAILS`, `WAMA_DEV_EMAILS` — alias wama-admin@ / wama-dev@) ; à défaut,
    l'adresse de chaque compte actif de ce niveau (`user_tier`). Sans doublon."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from wama.accounts.permissions import user_tier
    out = []
    for audience in audiences:
        tier, setting = STAFF_AUDIENCES[audience]
        declared = list(getattr(settings, setting, []) or [])
        if declared:
            out += declared
            continue
        out += [u.email for u in get_user_model().objects.filter(is_active=True).exclude(email='')
                if user_tier(u) == tier]
    return list(dict.fromkeys(out))


def notify_admins(kind, subject, body, url='', audiences=('admin', 'dev')):
    """Prévient le staff technique DANS WAMA (chaque compte qui administre l'infrastructure) et
    par e-mail (adresses fonctionnelles des `audiences`, cf. `staff_emails`). Une alerte
    d'exploitation (worker mort) concerne admins ET développeurs. Fail-safe ; rend
    (notifications créées, e-mail envoyé)."""
    try:
        admins = infrastructure_admins()
        emails = staff_emails(audiences)
    except Exception as e:  # pragma: no cover
        logger.warning("notify_admins : destinataires illisibles (%s)", e)
        return 0, False
    created = notify_in_app(admins, kind, subject, body, url)
    sent = notify_emails(emails, f"[WAMA] {subject}", body)
    return created, sent


def _job_title(app_label, item_name, success):
    """Le titre d'une fin de traitement — UN libellé, pour le propriétaire comme pour ceux qui
    collaborent (et pour le fil d'un canal, qui le relaie)."""
    return f"{app_label} — « {item_name} » {'terminé' if success else 'a échoué'}"


def _job_url(item, app_id=''):
    """La page de file de l'élément : `journal.app_queue_url` (le domicile commun du journal et du
    calendrier) quand l'app est connue ; à défaut, la racine de son paquet."""
    if app_id:
        from wama.common.services.journal import app_queue_url
        url = app_queue_url(app_id)
        if url:
            return url
    return f'/{item._meta.app_label}/'


def notify_job_collaborators(item, app_label, item_name, success, detail='', app_id=''):
    """La fin d'un traitement, aussi pour ceux qui COLLABORENT sur l'élément (E3, décision de
    Fabien 2026-10-03 : *« la relance reste celle de la card, la fin est notifiée aux deux »*). Le
    propriétaire l'est par `notify_job_end` ; chaque collaborateur reçoit la notification dans
    WAMA, et l'e-mail selon SES préférences. Fail-safe ; rend le nombre de collaborateurs prévenus."""
    try:
        from wama.common.services.access_requests import collaborators_of
        people = [u for u in collaborators_of(item) if u.pk != getattr(item, 'user_id', None)]
        if not people:
            return 0
        notify_in_app(people, 'job_done' if success else 'job_failed',
                      _job_title(app_label, item_name, success),
                      body=(detail or '') + ("\n" if detail else '') +
                           "Card en collaboration : le résultat est aussi celui de son propriétaire.",
                      url=_job_url(item, app_id), app=app_id, item=item)
        for person in people:
            notify_job(person, app_label, item_name, success, detail=detail)
        return len(people)
    except Exception as e:  # pragma: no cover
        logger.warning("notify_job_collaborators a échoué : %s", e)
        return 0


def notify_job_end(item, app_id, app_label, item_name, success, detail=''):
    """LA fin d'un traitement — le point unique des tâches (squelette commun, signal de l'imager).

    Pour le PROPRIÉTAIRE : l'e-mail (`notify_job`, préférences `notify_email` + `notify_on`) et,
    depuis le 2026-10-06, la notification DANS WAMA (`notify_on` seul, `wants_in_app_notification`)
    — jusque-là seuls les collaborateurs la recevaient : le propriétaire n'avait que l'e-mail, et
    sans SMTP, rien. Elle DÉSIGNE l'élément (`app`, `item`) : c'est ce que relève la passerelle de
    canaux pour poster la fin dans le fil d'où la tâche a été demandée (`ROADMAP §19.2`).
    Puis ceux qui COLLABORENT (E3). Fail-safe : une notification ne fait jamais échouer une tâche.
    """
    try:
        user = getattr(item, 'user', None)
        notify_job(user, app_label, item_name, success, detail=detail)
        profile = getattr(user, 'profile', None)
        if profile is not None and profile.wants_in_app_notification(success):
            notify_in_app([user], 'job_done' if success else 'job_failed',
                          _job_title(app_label, item_name, success), body=detail or '',
                          url=_job_url(item, app_id), app=app_id, item=item)
        notify_job_collaborators(item, app_label, item_name, success, detail=detail or '',
                                 app_id=app_id)
    except Exception as e:  # pragma: no cover
        logger.warning("notify_job_end a échoué : %s", e)


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
