"""Ce que le PANNEAU de la cloche montre d'une notification (`WAMA_COLLABORATION.md §2.3`,
2026-10-13, demande de Fabien : *« quand je clique sur la cloche, une petite fenêtre… je veux
pouvoir interagir avec les notifications directement dans la petite fenêtre »*).

Le navigateur ne connaît AUCUN type de notification : le serveur lui dit, pour chacune, son icône,
son ton et les gestes qu'elle offre — comme il lui dit déjà le son à jouer
(`utils.notifications.SOUND_BY_KIND`). Un type qui gagne un geste = une entrée dans
`ACTIONS_BY_KIND`, aucune ligne de JS.
"""
import re

from django.urls import reverse

#: Icône Font Awesome et ton (couleur de l'icône) par type. Un type absent prend la cloche.
STYLE_BY_KIND = {
    'job_done': ('fa-check-circle', 'success'),
    'job_failed': ('fa-times-circle', 'danger'),
    'worker_died': ('fa-server', 'warning'),
    'worker_tasks_interrupted': ('fa-exclamation-triangle', 'warning'),
    'access_request': ('fa-user-lock', 'info'),
    # Un compte créé à la première connexion attend sa validation (`accounts.moderation`).
    'account_pending': ('fa-user-clock', 'warning'),
    'access_granted': ('fa-user-check', 'success'),
    'access_request_refused': ('fa-user-times', 'danger'),
    'access_revoked': ('fa-user-slash', 'warning'),
    'share_received': ('fa-share-alt', 'info'),
    # « Demander la promotion » d'un élément d'auteur (`ownership.request_promotion`, 2026-10-20).
    'promotion_requested': ('fa-arrow-up-from-bracket', 'info'),
    'promotion_refused': ('fa-arrow-rotate-left', 'warning'),
}
DEFAULT_STYLE = ('fa-bell', 'neutral')

_REQUEST_URL = re.compile(r'^/common/requests/(\d+)/$')


def _access_request_actions(notification, user) -> list:
    """« Accorder / Refuser » une demande d'accès — au PROPRIÉTAIRE de l'élément, tant que la
    demande attend. La réponse passe par la route de la page de la demande
    (`access_request_answer`), dont le contrat (`done`, `reason`, `consent_required` +
    `statement`) est celui que le panneau sait lire."""
    match = _REQUEST_URL.match(notification.url or '')
    if not match:
        return []
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import target
    grant = ObjectGrant.objects.filter(pk=int(match.group(1)),
                                       state=ObjectGrant.STATE_REQUESTED).first()
    obj = target(grant) if grant is not None else None
    if obj is None or getattr(obj, 'user_id', None) != user.pk:
        return []
    url = reverse('common:access_request_answer', args=[grant.pk])
    return [
        {'label': 'Accorder', 'icon': 'fa-check', 'tone': 'success',
         'post': url, 'data': {'accept': '1'}, 'done': 'Demande accordée'},
        {'label': 'Refuser', 'icon': 'fa-times', 'tone': 'danger',
         'post': url, 'data': {'accept': '0'}, 'done': 'Demande refusée'},
    ]


#: Les gestes qu'un type de notification offre dans le panneau : `fonction(notification, user)`
#: → `[{label, icon, tone, post, data, done}]`. Rien pour un type absent (Ouvrir, lu / non lu et
#: supprimer valent pour toutes).
ACTIONS_BY_KIND = {
    'access_request': _access_request_actions,
}


def notification_actions(notification, user) -> list:
    builder = ACTIONS_BY_KIND.get(notification.kind)
    if builder is None:
        return []
    try:
        return builder(notification, user)
    except Exception:       # un geste qu'on ne sait pas calculer ne cache pas la notification
        return []


def notification_payload(notification, user) -> dict:
    """La notification telle que le panneau la rend : texte, état, style, gestes."""
    icon, tone = STYLE_BY_KIND.get(notification.kind, DEFAULT_STYLE)
    return {
        'id': notification.pk,
        'kind': notification.kind,
        'title': notification.title,
        'body': notification.body,
        'app': notification.app,
        # « Ouvrir » passe par la route qui MARQUE LUE avant de mener au lien (2026-10-07).
        'open_url': (reverse('common:notification_open', args=[notification.pk])
                     if notification.url else ''),
        'created_at': notification.created_at.isoformat() if notification.created_at else '',
        'read': notification.read_at is not None,
        'icon': icon,
        'tone': tone,
        'actions': notification_actions(notification, user),
    }


#: Ce que le panneau de la cloche montre au plus (la page complète en garde 200).
PANEL_MAX = 50


def notification_list(user, *, unread_only: bool = False, limit: int = 20) -> dict:
    """Les notifications de `user`, les plus récentes d'abord : `{'unread', 'total', 'items'}`.
    Une lecture pour le panneau de la cloche (`views.api_notifications_list`) et pour
    l'assistant (`tool_api.list_my_notifications`, 2026-10-14) — ils montrent la même chose.
    `limit` est borné à `PANEL_MAX`."""
    from wama.common.models import Notification
    mine = Notification.objects.filter(recipient=user)
    unread = mine.filter(read_at__isnull=True)
    shown = unread if unread_only else mine
    limit = max(1, min(PANEL_MAX, int(limit or 20)))
    rows = list(shown.order_by('-created_at', '-pk')[:limit])
    return {'unread': unread.count(), 'total': shown.count(),
            'items': [notification_payload(n, user) for n in rows]}
