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


def entry_of(obj):
    """L'ENTRÉE de file d'un élément : son lot, ou lui-même sans lot (un lot est sa propre entrée).
    La COLLABORATION se donne à l'entrée — la même unité que le partage et le rangement : une card
    d'un lot partagé se partage avec son lot."""
    from wama.common.utils.batch_common import batch_of
    try:
        lot = batch_of(obj)
    except Exception:
        lot = None
    return lot or obj


def _granted(user, objects, level):
    from django.db.models import Q
    if not getattr(user, 'pk', None):
        return None
    q = Q()
    for o in objects:
        q |= Q(object_type=o._meta.label, object_id=o.pk)
    now = timezone.now()
    return (ObjectGrant.objects.filter(q, beneficiary=user, level=level,
                                       state=ObjectGrant.STATE_GRANTED)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).first())


def collaboration_grant(user, obj):
    """Le droit de COLLABORER de `user` sur cet élément (accordé, non expiré), lu sur l'élément ET
    sur son entrée — ou None. C'est la lecture que fait `scoping.editable_or_404`."""
    entry = entry_of(obj)
    objects = [obj] if entry is obj else [obj, entry]
    return _granted(user, objects, ObjectGrant.LEVEL_COLLABORATE)


def trace_collaborator(user, obj, signal: str, detail=None) -> None:
    """Le geste d'un COLLABORATEUR sur la card d'un autre, au journal des faits (`RunOutcome`) —
    E3 (« le journal garde qui a relancé ») et E4 (« le dernier enregistrement gagne, TRACÉ »).
    Rien n'est noté pour le propriétaire : c'est le partage qui rend la question « qui ? » utile.
    Best-effort : une trace manquée ne fait jamais échouer le geste."""
    if getattr(obj, 'user_id', None) == getattr(user, 'pk', None):
        return
    try:
        from wama.common.services.run_outcome import record
        record(obj._meta.app_label, obj, signal, user=user,
               detail={'collaborator': True, 'owner_id': getattr(obj, 'user_id', None),
                       **(detail or {})})
    except Exception:
        pass


def collaborators_of(obj) -> list:
    """Les personnes qui COLLABORENT sur cet élément (droit accordé sur lui ou sur son entrée)."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    entry = entry_of(obj)
    q = Q(object_type=obj._meta.label, object_id=obj.pk)
    if entry is not obj:
        q |= Q(object_type=entry._meta.label, object_id=entry.pk)
    now = timezone.now()
    ids = (ObjectGrant.objects.filter(q, level=ObjectGrant.LEVEL_COLLABORATE,
                                      state=ObjectGrant.STATE_GRANTED)
           .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
           .values_list('beneficiary_id', flat=True))
    return list(get_user_model().objects.filter(pk__in=set(ids)))


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
    mode = (ObjectGrant.LEVEL_COLLABORATE if collaboration_grant(user, obj) is not None
            else CURRENT_SHARE_MODE['key'])
    pending = pending_for(user, obj)
    entry = entry_of(obj)
    if entry is not obj:                       # une demande de collaboration vise l'entrée
        pending.update({k: v for k, v in pending_for(user, entry).items() if k not in pending})
    return {
        'owner': owner_label(obj),
        'mode': mode,
        'modes': [dict(m) for m in SHARE_MODES],
        'pending': pending,
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
    if level == ObjectGrant.LEVEL_COLLABORATE:
        if collaboration_grant(user, obj) is not None:
            raise AccessRequestRefused('vous collaborez déjà sur cet élément')
        obj = entry_of(obj)                    # la collaboration se donne à l'ENTRÉE (le lot)
    object_type, object_id = target_of(obj)
    existing = ObjectGrant.objects.filter(beneficiary=user, object_type=object_type,
                                          object_id=object_id, level=level,
                                          state=ObjectGrant.STATE_REQUESTED).first()
    if existing is not None:
        return existing
    grant = ObjectGrant.objects.create(object_type=object_type, object_id=object_id,
                                       surface=surface, beneficiary=user, level=level)
    what = ('en devenir propriétaire' if level == ObjectGrant.LEVEL_OWN
            else f"collaborer (mode « {_mode(level)['label']} »)")
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
        mode = _mode(grant.level)
        if grant.level == ObjectGrant.LEVEL_OWN:
            is_lot = batch_model_for_app(grant.surface) is type(obj) if grant.surface else False
            if is_lot:
                report = transfer_lot(owner, obj, PreviewRegistry.get_model(grant.surface),
                                      grant.beneficiary, consent=consent)
            else:
                report = transfer_card(owner, obj, grant.beneficiary, consent=consent)
        elif mode is None or not mode['available']:
            raise AccessRequestRefused("ce mode n'existe pas encore : la demande ne peut être accordée")
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
    elif grant.level == ObjectGrant.LEVEL_COLLABORATE:
        notify_in_app([grant.beneficiary], 'access_granted',
                      f"{owner.username} vous a accordé la collaboration",
                      body=(f"« {_label(obj)} » ({obj._meta.app_label}) : vous pouvez en modifier "
                            "les réglages et le relancer. La suppression reste au propriétaire."),
                      url=f'/{obj._meta.app_label}/')
    return {'state': grant.state, **report}


def revoke(owner, grant: ObjectGrant) -> ObjectGrant:
    """Le PROPRIÉTAIRE retire un droit accordé (E5, décision de Fabien 2026-10-03) : effet
    IMMÉDIAT sur les gestes suivants (les contrôles lisent les droits à chaque geste), un
    traitement déjà lancé va à son terme, le bénéficiaire est prévenu."""
    from wama.common.utils.notifications import notify_in_app
    obj = target(grant)
    if obj is None or getattr(obj, 'user_id', None) != owner.pk:
        raise AccessRequestRefused('seul le propriétaire retire un droit')
    if grant.state != ObjectGrant.STATE_GRANTED:
        raise AccessRequestRefused("ce droit n'est pas en vigueur")
    grant.state = ObjectGrant.STATE_REVOKED
    grant.answered_at = timezone.now()
    grant.save(update_fields=['state', 'answered_at'])
    notify_in_app([grant.beneficiary], 'access_revoked',
                  f"{owner.username} a retiré votre droit de {grant.get_level_display().lower()}",
                  body=(f"« {_label(obj)} » ({obj._meta.app_label}) : vous la voyez encore si elle "
                        "vous est partagée, sans pouvoir la modifier. Un traitement déjà lancé va "
                        "à son terme."),
                  url=f'/{obj._meta.app_label}/')
    return grant


def _label(obj) -> str:
    """Le nom d'un élément dans une notification ou une page. Un LOT (la cible d'une collaboration)
    se dit « lot #N (k cards) » — le libellé d'une card y donnait « #N », illisible."""
    from wama.common.services.card_transfer import _label as transfer_label
    named = any(getattr(obj, n, None) for n in ('name', 'filename', 'input_filename'))
    if not named and hasattr(obj, 'total'):        # un lot : un total, pas de nom de fichier
        total = getattr(obj, 'total', None)
        return f"lot #{obj.pk}" + (f" ({total} card{'s' if total and total > 1 else ''})"
                                   if total is not None else '')
    return transfer_label(obj)
