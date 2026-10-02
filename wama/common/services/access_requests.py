"""DEMANDER un niveau d'accès sur une card reçue — et y RÉPONDRE (2026-10-03, décision de Fabien).

*« Si c'est une card partagée, une ligne permettant les demandes d'appropriation par niveau de
partage : elle affiche l'état coché (lecture seule par exemple) ; s'il coche "demande de
modification", notification à l'utilisateur qui a partagé ; idem pour la collaboration. »* Et :
*« modes grisés, et oui pour la demande de propriété »*.

La demande vit dans `common.ObjectGrant` — *la demande ET le droit sont la même ligne*
(`WAMA_COLLABORATION §4.3`) : `requested`, puis `granted` ou `refused` par le propriétaire.

Ce qui est HONORABLE aujourd'hui : la seule PROPRIÉTÉ — l'accepter déclenche « Transférer à… »
(`card_transfer`, ses gardes et son consentement compris). Modification et collaboration sont
déclarées (`sharing.SHARE_MODES`, `available=False`) et refusées ici avec leur motif : une demande
que le propriétaire ne pourrait pas accorder serait un faux choix.

Coordonnées : celles du partage (`surface` + pk + `nature` élément | lot). Prévenir : une
notification DANS WAMA (`notify_in_app`) — la cloche de l'en-tête et la fenêtre en bas à droite.
"""
from django.db import transaction
from django.utils import timezone

from wama.common.models import ObjectGrant


class AccessRequestRefused(Exception):
    """Refus MOTIVÉ : le motif est destiné à l'utilisateur."""


def _mode(key):
    from wama.common.services.sharing import SHARE_MODES
    return next((m for m in SHARE_MODES if m['key'] == key), None)


def target_of(obj):
    """(object_type, object_id) d'une card ou d'un lot."""
    return obj._meta.label, obj.pk


def pending_for(user, obj) -> dict:
    """{niveau: id de la demande} des demandes EN ATTENTE de `user` sur cet élément."""
    object_type, object_id = target_of(obj)
    return dict(ObjectGrant.objects.filter(
        beneficiary=user, object_type=object_type, object_id=object_id,
        state=ObjectGrant.STATE_REQUESTED).values_list('level', 'pk'))


def access_state(user, obj) -> dict:
    """Ce que le menu « Mon accès » d'une card REÇUE affiche : le mode courant (coché), les modes
    déclarés (grisés s'ils n'existent pas encore), et les demandes déjà en attente."""
    from wama.common.services.reception import owner_label
    from wama.common.services.sharing import CURRENT_SHARE_MODE, SHARE_MODES
    return {
        'owner': owner_label(obj),
        'mode': CURRENT_SHARE_MODE['key'],
        'modes': [dict(m) for m in SHARE_MODES],
        'pending': pending_for(user, obj),
    }


def request_access(user, obj, level: str, surface: str = '') -> ObjectGrant:
    """`user` DEMANDE `level` sur `obj` (une card ou un lot qu'on lui a partagé). Une demande déjà
    en attente n'est pas recréée : elle est rendue. Le propriétaire est prévenu dans WAMA."""
    from wama.common.services.reception import NotReceived, _check_received
    from wama.common.utils.notifications import notify_in_app
    if level != ObjectGrant.LEVEL_OWN:
        mode = _mode(level)
        if mode is None:
            raise AccessRequestRefused('niveau inconnu')
        if not mode['available']:
            raise AccessRequestRefused(f"le mode « {mode['label']} » n'existe pas encore")
    try:
        _check_received(user, obj)
    except NotReceived as exc:
        raise AccessRequestRefused(str(exc)) from exc
    object_type, object_id = target_of(obj)
    existing = ObjectGrant.objects.filter(beneficiary=user, object_type=object_type,
                                          object_id=object_id, level=level,
                                          state=ObjectGrant.STATE_REQUESTED).first()
    if existing is not None:
        return existing
    grant = ObjectGrant.objects.create(object_type=object_type, object_id=object_id,
                                       surface=surface, beneficiary=user, level=level)
    what = 'en devenir propriétaire' if level == ObjectGrant.LEVEL_OWN else f'le mode {level}'
    notify_in_app([obj.user], 'access_request',
                  f"{user.username} demande à {what}",
                  body=f"« {_label(obj)} » ({obj._meta.app_label}). Acceptez ou refusez la demande.",
                  url=f'/common/requests/{grant.pk}/')
    return grant


def target(grant):
    """L'élément que vise une demande, ou None s'il a disparu."""
    from django.apps import apps
    try:
        model = apps.get_model(grant.object_type)
    except (LookupError, ValueError):
        return None
    return model._default_manager.filter(pk=grant.object_id).first()


def answer(owner, grant: ObjectGrant, accept: bool, consent: bool = False) -> dict:
    """Le PROPRIÉTAIRE accepte ou refuse. Accepter la propriété CÈDE l'élément au demandeur
    (`card_transfer`) — ses gardes valent : rien en cours, consentement si l'élément porte une
    personne (`TransferConsentRequired` remonte, la page le fait valider). Rend un compte-rendu."""
    from wama.common.services.card_transfer import transfer_card, transfer_lot
    from wama.common.utils.batch_common import batch_model_for_app
    from wama.common.utils.notifications import notify_in_app
    from wama.common.utils.preview_registry import PreviewRegistry
    obj = target(grant)
    if obj is None:
        raise AccessRequestRefused("l'élément demandé n'existe plus")
    if getattr(obj, 'user_id', None) != owner.pk:
        raise AccessRequestRefused('seul le propriétaire répond à une demande')
    if grant.state != ObjectGrant.STATE_REQUESTED:
        raise AccessRequestRefused('cette demande a déjà reçu une réponse')
    report = {}
    if accept:
        if grant.level != ObjectGrant.LEVEL_OWN:
            raise AccessRequestRefused("ce mode n'existe pas encore : la demande ne peut être accordée")
        is_lot = batch_model_for_app(grant.surface) is type(obj) if grant.surface else False
        if is_lot:
            report = transfer_lot(owner, obj, PreviewRegistry.get_model(grant.surface),
                                  grant.beneficiary, consent=consent)
        else:
            report = transfer_card(owner, obj, grant.beneficiary, consent=consent)
    with transaction.atomic():
        grant.state = ObjectGrant.STATE_GRANTED if accept else ObjectGrant.STATE_REFUSED
        grant.granted_by = owner
        grant.answered_at = timezone.now()
        grant.save(update_fields=['state', 'granted_by', 'answered_at'])
    if not accept:
        notify_in_app([grant.beneficiary], 'access_request_refused',
                      f"{owner.username} a refusé votre demande",
                      body=f"« {_label(obj)} » ({obj._meta.app_label}) reste à {owner.username}.",
                      url=f'/{obj._meta.app_label}/')
    return {'state': grant.state, **report}


def _label(obj) -> str:
    from wama.common.services.card_transfer import _label as transfer_label
    return transfer_label(obj)
