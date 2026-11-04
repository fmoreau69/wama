"""L'ACCÈS à une app du bac à sable : la décision, la demande, l'accord, le retrait (2026-11-02).

Décisions de Fabien, le même jour :
  - *« Une seule règle partout, un dev ne voit que ses propres apps. Admin toutes. »* ;
  - *« Un utilisateur simple ne doit même pas voir le bac à sable pour le moment. S'il souhaite y
    accéder ou développer une application dans WAMA, il demande à devenir développeur. »* ;
  - *« Dans la logique du partage, on est censé pouvoir surcharger l'accès à une app via le
    partage »* — *« créateur et admin accordent, aux devs seulement, pour le moment :
    utiliser/tester. »*

La DÉCISION vit dans `permissions._app_accessible` (le point unique) ; elle lit ici les faits du
bac à sable (`sandbox_facts`). Le DROIT est une ligne `accounts.AccessGrant` — la demande et le
droit sont la même ligne, comme pour une card partagée (`common.services.access_requests`).
Chaque geste prévient dans WAMA (`notify_in_app`) ; la page de la demande est celle des demandes
d'accès (`common/access_request.html`).
"""
from django.db import transaction
from django.utils import timezone

from wama.accounts.models import AccessGrant

KIND_APP = 'app'


class AppAccessRefused(Exception):
    """Refus MOTIVÉ : le motif est destiné à l'utilisateur."""


# ── Les faits du bac à sable ───────────────────────────────────────────────────────────────────

def sandbox_owners() -> dict:
    """`{label: (développeurs…)}` des apps du registre des bacs à sable — son créateur puis ceux
    qui ont pris part à sa génération (`sandbox.entry_contributors`) ; `()` : ligne de commande.
    Une lecture du registre (mise en cache sur son horodatage, `sandbox.load_registry`)."""
    try:
        from wama.common.sandbox import entry_contributors, load_registry
        return {e.get('label'): tuple(entry_contributors(e)) for e in load_registry()
                if isinstance(e, dict) and e.get('label')}
    except Exception:
        return {}


def granted_apps(user) -> set:
    """Les apps que `user` a le DROIT d'utiliser par une ligne en vigueur."""
    if not getattr(user, 'pk', None):
        return set()
    return set(AccessGrant.in_force().filter(
        subject_type=AccessGrant.SUBJECT_USER, subject_id=user.pk, kind=KIND_APP,
        effect=AccessGrant.EFFECT_ALLOW).values_list('element_id', flat=True))


def sandbox_facts(user) -> tuple:
    """`(propriétaires, apps accordées à user)` — ce que la décision lit pour une app du bac à
    sable ; `accessible_apps` le lit UNE fois pour une liste."""
    return sandbox_owners(), granted_apps(user)


def sandbox_decision(user, app_id, owners, granted):
    """None si `app_id` n'est pas au bac à sable ; sinon la décision : un administrateur, toutes ;
    un développeur, celles qu'il a créées — seul ou avec d'autres — ou qu'on lui a ouvertes ;
    personne d'autre."""
    if app_id not in owners:
        return None
    from wama.accounts.permissions import is_admin_tier, is_developer
    if is_admin_tier(user):
        return True
    if not is_developer(user):
        return False
    return getattr(user, 'username', None) in owners[app_id] or app_id in granted


# ── Qui accorde, à qui ─────────────────────────────────────────────────────────────────────────

def _is_sandbox(app_id) -> bool:
    return app_id in sandbox_owners()


def developers_of(app_id) -> list:
    """Les comptes DÉVELOPPEURS d'une app du bac à sable (créateur d'abord), ceux qui existent."""
    from django.contrib.auth import get_user_model
    names = list(sandbox_owners().get(app_id) or ())
    found = {u.username: u for u in get_user_model().objects.filter(username__in=names)}
    return [found[n] for n in names if n in found]


def can_grant(user, app_id) -> bool:
    """Un DÉVELOPPEUR de l'app (son créateur ou un participant) qui l'est encore, ou un
    administrateur."""
    from wama.accounts.permissions import is_admin_tier, is_developer
    if not _is_sandbox(app_id) or not getattr(user, 'pk', None):
        return False
    if is_admin_tier(user):
        return True
    return bool(is_developer(user) and user.get_username() in sandbox_owners().get(app_id, ()))


def can_develop(user, app_id) -> bool:
    """DÉVELOPPER une app du bac à sable (la régénérer, revenir en arrière, la retirer) : son
    créateur et les administrateurs. Un accès ACCORDÉ ne donne que l'usage (« utiliser / tester,
    sans risque », décision de Fabien du 2026-11-02) — c'est la même règle que celle de l'accord."""
    return can_grant(user, app_id)


def granters_of(app_id) -> list:
    """Ceux qu'une demande prévient : les développeurs de l'app qui le sont encore, et les
    administrateurs."""
    from wama.accounts.permissions import administrators, is_developer
    found = list(administrators())
    for developer in reversed(developers_of(app_id)):
        if is_developer(developer) and developer not in found:
            found.insert(0, developer)
    return found


def _check_beneficiary(user, app_id):
    """« Aux devs seulement, pour le moment » : un DÉVELOPPEUR, qui n'a pas déjà l'accès."""
    from wama.accounts.permissions import is_admin_tier, is_developer
    if not _is_sandbox(app_id):
        raise AppAccessRefused(f"« {app_id} » n'est pas une app du bac à sable")
    if not is_developer(user):
        raise AppAccessRefused("l'accès au bac à sable s'ouvre aux développeurs : demander "
                               "d'abord à devenir développeur")
    if is_admin_tier(user):
        raise AppAccessRefused('un administrateur a déjà accès à tout le bac à sable')
    owners, granted = sandbox_facts(user)
    if sandbox_decision(user, app_id, owners, granted):
        raise AppAccessRefused(f"{user.get_username()} a déjà accès à « {app_id} »")


def app_title(app_id) -> str:
    from wama.common.app_registry import app_identity
    return app_identity(app_id).get('label') or app_id


def request_url(grant) -> str:
    return f'/accounts/app-access/{grant.pk}/'


# ── Les gestes ─────────────────────────────────────────────────────────────────────────────────

def request_access(user, app_id, reason: str = '') -> AccessGrant:
    """Un développeur DEMANDE à utiliser une app du bac à sable. Une demande déjà en attente est
    rendue, pas recréée. Le créateur et les administrateurs sont prévenus."""
    from wama.common.utils.notifications import notify_in_app
    _check_beneficiary(user, app_id)
    pending = AccessGrant.objects.filter(
        subject_type=AccessGrant.SUBJECT_USER, subject_id=user.pk, kind=KIND_APP,
        element_id=app_id, state=AccessGrant.STATE_REQUESTED).first()
    if pending is not None:
        return pending
    grant = AccessGrant.objects.create(subject_type=AccessGrant.SUBJECT_USER, subject_id=user.pk,
                                       kind=KIND_APP, element_id=app_id,
                                       reason=(reason or '')[:2000])
    notify_in_app(granters_of(app_id), 'access_request',
                  f"{user.get_username()} demande à utiliser « {app_title(app_id)} »",
                  body="App du bac à sable — utiliser / tester. Acceptez ou refusez la demande.",
                  url=request_url(grant), app=app_id)
    return grant


def grant_access(granter, app_id, beneficiary, expires_at=None) -> AccessGrant:
    """Le créateur ou un administrateur OUVRE l'app à un développeur, sans attendre sa demande ;
    une demande en attente de ce développeur est accordée par le même geste."""
    from wama.common.utils.notifications import notify_in_app
    if not can_grant(granter, app_id):
        raise AppAccessRefused("seuls les développeurs de l'app et les administrateurs accordent l'accès")
    _check_beneficiary(beneficiary, app_id)
    now = timezone.now()
    with transaction.atomic():
        grant = AccessGrant.objects.filter(
            subject_type=AccessGrant.SUBJECT_USER, subject_id=beneficiary.pk, kind=KIND_APP,
            element_id=app_id, state=AccessGrant.STATE_REQUESTED).first()
        if grant is None:
            grant = AccessGrant(subject_type=AccessGrant.SUBJECT_USER, subject_id=beneficiary.pk,
                                kind=KIND_APP, element_id=app_id)
        grant.state, grant.granted_by, grant.answered_at = AccessGrant.STATE_GRANTED, granter, now
        grant.expires_at = expires_at
        grant.save()
    notify_in_app([beneficiary], 'access_granted',
                  f"{granter.get_username()} vous ouvre « {app_title(app_id)} »",
                  body="App du bac à sable : vous pouvez l'utiliser et la tester.",
                  url=_app_url(app_id), app=app_id)
    return grant


def answer(granter, grant: AccessGrant, accept: bool) -> dict:
    """Le créateur ou un administrateur accepte ou refuse une demande en attente."""
    from wama.common.utils.notifications import notify_in_app
    if grant.kind != KIND_APP or not can_grant(granter, grant.element_id):
        raise AppAccessRefused("seuls les développeurs de l'app et les administrateurs répondent")
    if grant.state != AccessGrant.STATE_REQUESTED:
        raise AppAccessRefused('cette demande a déjà reçu une réponse')
    beneficiary = grant.subject_user()
    if beneficiary is None:
        raise AppAccessRefused("le compte demandeur n'existe plus")
    if accept:
        return {'state': grant_access(granter, grant.element_id, beneficiary).state}
    grant.state, grant.granted_by, grant.answered_at = (AccessGrant.STATE_REFUSED, granter,
                                                        timezone.now())
    grant.save(update_fields=['state', 'granted_by', 'answered_at'])
    notify_in_app([beneficiary], 'access_request_refused',
                  f"{granter.get_username()} a refusé votre demande",
                  body=f"« {app_title(grant.element_id)} » (bac à sable) reste fermée.",
                  url=request_url(grant), app=grant.element_id)
    return {'state': grant.state}


def revoke(granter, grant: AccessGrant) -> AccessGrant:
    """Le créateur ou un administrateur RETIRE un accès accordé : effet immédiat (la décision lit
    les droits à chaque geste), un traitement déjà lancé va à son terme."""
    from wama.common.utils.notifications import notify_in_app
    if grant.kind != KIND_APP or not can_grant(granter, grant.element_id):
        raise AppAccessRefused("seuls les développeurs de l'app et les administrateurs retirent un accès")
    if grant.state != AccessGrant.STATE_GRANTED:
        raise AppAccessRefused("cet accès n'est pas en vigueur")
    grant.state, grant.answered_at = AccessGrant.STATE_REVOKED, timezone.now()
    grant.save(update_fields=['state', 'answered_at'])
    beneficiary = grant.subject_user()
    if beneficiary is not None:
        notify_in_app([beneficiary], 'access_revoked',
                      f"{granter.get_username()} a retiré votre accès à « {app_title(grant.element_id)} »",
                      body="Un traitement déjà lancé va à son terme.", app=grant.element_id)
    return grant


def _app_url(app_id) -> str:
    from django.urls import NoReverseMatch, reverse
    from wama.common.app_registry import APP_CATALOG
    try:
        return reverse((APP_CATALOG.get(app_id) or {}).get('url_name') or f'{app_id}:index')
    except NoReverseMatch:
        return ''


# ── Ce que les pages montrent ──────────────────────────────────────────────────────────────────

#: Le MODE d'un accès accordé à une app, sous la forme des modes de partage (`sharing.SHARE_MODES`)
#: — le niveau se lit au mot ET au signe sur la page « Partages ».
USE_MODE = {'key': AccessGrant.LEVEL_USE, 'label': 'Utiliser / tester', 'icon': '🧪',
            'available': True}


def grant_row(grant) -> dict:
    user = grant.subject_user()
    return {'id': grant.pk, 'app': grant.element_id, 'app_label': app_title(grant.element_id),
            'who': user.get_username() if user else f'#{grant.subject_id}',
            'level': grant.get_level_display(), 'state': grant.state,
            'state_label': grant.get_state_display(), 'reason': grant.reason,
            'created_at': grant.created_at, 'since': grant.answered_at or grant.created_at,
            'expires_at': grant.expires_at, 'granted_by': (grant.granted_by.get_username()
                                                           if grant.granted_by else ''),
            'url': request_url(grant)}


def overview(user) -> dict:
    """Pour la page « Partages » : les apps du bac à sable que `user` OUVRE (créateur, ou
    administrateur : toutes) et à qui ; celles qu'on LUI a ouvertes ; les demandes à traiter et
    les siennes en attente."""
    if not getattr(user, 'pk', None):
        return {'shared': [], 'received': [], 'incoming': [], 'outgoing': []}
    owners = sandbox_owners()
    mine = [a for a in owners if can_grant(user, a)]
    rows = AccessGrant.objects.filter(kind=KIND_APP, subject_type=AccessGrant.SUBJECT_USER)
    live = AccessGrant.in_force().filter(kind=KIND_APP, subject_type=AccessGrant.SUBJECT_USER)
    shared = []
    for app_id in mine:
        persons = [grant_row(g) for g in live.filter(element_id=app_id).order_by('created_at')]
        if persons:
            shared.append({'app': app_id, 'app_label': app_title(app_id), 'persons': persons,
                           'url': _app_url(app_id)})
    received = [{'app': g.element_id, 'app_label': app_title(g.element_id),
                 'owner': ', '.join(owners.get(g.element_id) or ()) or 'administration',
                 'grant': grant_row(g),
                 'url': _app_url(g.element_id)}
                for g in live.filter(subject_id=user.pk)]
    pending = rows.filter(state=AccessGrant.STATE_REQUESTED)
    return {'shared': shared, 'received': received,
            'incoming': [grant_row(g) for g in pending.filter(element_id__in=mine)],
            'outgoing': [grant_row(g) for g in pending.filter(subject_id=user.pk)]}


def requestable_apps(user) -> list:
    """Les apps du bac à sable qu'un DÉVELOPPEUR peut demander (il ne les a pas), avec sa demande
    en attente s'il en a une — ce que le catalogue des apps lui montre fermées."""
    from wama.accounts.permissions import is_admin_tier, is_developer
    if not is_developer(user) or is_admin_tier(user):
        return []
    owners, granted = sandbox_facts(user)
    pending = dict(AccessGrant.objects.filter(
        subject_type=AccessGrant.SUBJECT_USER, subject_id=user.pk, kind=KIND_APP,
        state=AccessGrant.STATE_REQUESTED).values_list('element_id', 'pk'))
    return [{'app': a, 'app_label': app_title(a), 'owner': ', '.join(owners[a]) or 'administration',
             'pending': pending.get(a)}
            for a in sorted(owners) if not sandbox_decision(user, a, owners, granted)]
