"""Un RÔLE MÉTIER se demande : la personne le déclare, un administrateur valide (2026-11-25,
décision de Fabien — `PROFILES_PERMISSIONS.md §1.12`).

Aucun rôle n'est posé par défaut sur un compte. Une personne DEMANDE le métier qui est le sien
(`permissions.ROLES`) ; les administrateurs en sont prévenus et répondent. La demande est une
ligne `accounts.AccessGrant` (`kind='role'`), comme une demande d'accès à une app du bac à sable
(`accounts/app_access.py`) : même page (`common/access_request.html`), mêmes états, même réponse.

⚠ Le DROIT, lui, reste où il a toujours été : l'appartenance au groupe `role:<clé>`, que lit
`permissions.user_roles` et que la page des utilisateurs bascule. La ligne garde la DEMANDE et sa
réponse ; elle ne décide de rien. Un administrateur qui pose le rôle à la main sur la page des
utilisateurs répond du même coup à la demande en attente (`give`, le seul geste qui pose un rôle).
"""
from django.contrib.auth.models import Group
from django.utils import timezone

from .app_access import AccessRefused, request_url     # la page d'une demande : la même adresse
from .models import AccessGrant
from .permissions import GROUP_PREFIX, ROLES

KIND_ROLE = 'role'


class RoleRequestRefused(AccessRefused):
    """Refus MOTIVÉ : le motif est destiné à l'utilisateur."""


def _requests(**filters):
    return AccessGrant.objects.filter(subject_type=AccessGrant.SUBJECT_USER, kind=KIND_ROLE,
                                      **filters)


def can_grant(user, role=None) -> bool:
    """Qui répond à une demande de rôle : un administrateur — celui qui pose les rôles sur la
    page des utilisateurs."""
    from .permissions import is_admin_tier
    return bool(getattr(user, 'pk', None)) and is_admin_tier(user)


def role_label(role) -> str:
    return ROLES.get(role, role)


def _waiting(user, role):
    """La demande EN ATTENTE de `user` pour `role`, ou None."""
    return _requests(subject_id=user.pk, element_id=role,
                     state=AccessGrant.STATE_REQUESTED).first()


def request_summary(grant) -> dict:
    """Ce que la page d'une demande dit de celle-ci (`common/access_request.html`)."""
    return {'what': f"Le rôle métier « {role_label(grant.element_id)} »",
            'label': role_label(grant.element_id), 'app': '',
            'waiting': "d'un administrateur"}


def requestable_roles(user) -> list:
    """Les métiers du catalogue, pour la personne : `{key, label, description, held, pending}` —
    `pending` : l'identifiant de sa demande en attente."""
    from .permissions import ROLE_DESCRIPTIONS, user_roles
    held = set(user_roles(user))
    waiting = dict(_requests(subject_id=user.pk, state=AccessGrant.STATE_REQUESTED)
                   .values_list('element_id', 'pk'))
    return [{'key': key, 'label': label, 'description': ROLE_DESCRIPTIONS.get(key, ''),
             'held': key in held, 'pending': waiting.get(key)}
            for key, label in ROLES.items()]


def pending_by_user() -> dict:
    """`{compte: {rôle: identifiant de la demande}}` des demandes en attente — ce que la page des
    utilisateurs montre sur la ligne de chacun."""
    found = {}
    for user_id, role, pk in _requests(state=AccessGrant.STATE_REQUESTED).values_list(
            'subject_id', 'element_id', 'pk'):
        found.setdefault(user_id, {})[role] = pk
    return found


def request_role(user, role, reason: str = '') -> AccessGrant:
    """La personne DEMANDE le rôle `role`. Une demande déjà en attente est rendue, pas recréée ;
    les administrateurs sont prévenus."""
    from wama.common.utils.notifications import notify_in_app

    from .permissions import account_kind, administrators, user_roles
    if not getattr(user, 'pk', None) or account_kind(user) != 'person':
        raise RoleRequestRefused('un rôle se demande depuis un compte de personne')
    if role not in ROLES:
        raise RoleRequestRefused(f"« {role} » n'est pas un rôle métier : "
                                 + ', '.join(ROLES))
    if role in user_roles(user):
        raise RoleRequestRefused(f"vous avez déjà le rôle « {role_label(role)} »")
    waiting = _waiting(user, role)
    if waiting is not None:
        return waiting
    grant = AccessGrant.objects.create(subject_type=AccessGrant.SUBJECT_USER, subject_id=user.pk,
                                       kind=KIND_ROLE, element_id=role,
                                       reason=(reason or '')[:2000])
    notify_in_app(administrators(), 'access_request',
                  f"{user.get_username()} demande le rôle « {role_label(role)} »",
                  body="Rôle métier : il ouvre les applications de ce métier. Acceptez ou "
                       "refusez la demande.",
                  url=request_url(grant))
    return grant


def _close(grant, state, granter):
    grant.state, grant.granted_by, grant.answered_at = state, granter, timezone.now()
    grant.save(update_fields=['state', 'granted_by', 'answered_at'])


def answer(granter, grant: AccessGrant, accept: bool) -> dict:
    """Un administrateur accepte (le rôle est posé) ou refuse une demande en attente ; la personne
    en est prévenue."""
    from wama.common.utils.notifications import notify_in_app
    if grant.kind != KIND_ROLE or not can_grant(granter):
        raise RoleRequestRefused('seul un administrateur répond à une demande de rôle')
    if grant.state != AccessGrant.STATE_REQUESTED:
        raise RoleRequestRefused('cette demande a déjà reçu une réponse')
    beneficiary = grant.subject_user()
    if beneficiary is None:
        raise RoleRequestRefused("le compte demandeur n'existe plus")
    if accept:
        give(beneficiary, grant.element_id, granter)
        grant.refresh_from_db()
    else:
        _close(grant, AccessGrant.STATE_REFUSED, granter)
        notify_in_app([beneficiary], 'access_request_refused',
                      f"{granter.get_username()} a refusé votre demande",
                      body=f"Le rôle « {role_label(grant.element_id)} » ne vous est pas donné.",
                      url=request_url(grant))
    return {'state': grant.state}


def give(user, role, granter) -> bool:
    """POSE le rôle `role` sur `user` — LE geste : celui de la page des utilisateurs (la case du
    métier) comme celui d'une demande acceptée. La demande en attente de cette personne pour ce
    rôle, s'il y en a une, est accordée du même coup, et elle en est prévenue. Rend True si une
    demande a été soldée."""
    from wama.common.utils.notifications import notify_in_app
    group, _ = Group.objects.get_or_create(name=GROUP_PREFIX + role)
    user.groups.add(group)
    waiting = _waiting(user, role)
    if waiting is None:
        return False
    _close(waiting, AccessGrant.STATE_GRANTED, granter)
    notify_in_app([user], 'access_granted',
                  f"{granter.get_username()} vous a donné le rôle « {role_label(role)} »",
                  body="Les applications de ce métier vous sont ouvertes.",
                  url=request_url(waiting))
    return True


def grant_row(grant) -> dict:
    user = grant.subject_user()
    return {'id': grant.pk, 'role': grant.element_id, 'role_label': role_label(grant.element_id),
            'who': user.get_username() if user else f'#{grant.subject_id}',
            'state': grant.state, 'state_label': grant.get_state_display(),
            'reason': grant.reason, 'created_at': grant.created_at, 'url': request_url(grant)}


def overview(user) -> dict:
    """Les demandes de rôle qui concernent `user` : les siennes (`mine`), et pour un
    administrateur celles qui attendent sa réponse (`to_answer`)."""
    if not getattr(user, 'pk', None):
        return {'mine': [], 'to_answer': []}
    mine = [grant_row(g) for g in _requests(subject_id=user.pk).order_by('-created_at')[:20]]
    waiting = ([grant_row(g) for g in _requests(state=AccessGrant.STATE_REQUESTED)]
               if can_grant(user) else [])
    return {'mine': mine, 'to_answer': waiting}
