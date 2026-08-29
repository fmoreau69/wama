"""
Passerelle de canaux — appariement d'identité et résolution du compte.

C'est le point d'entrée que TOUT adaptateur de canal appelle (Matrix/Tchap, Discord, et les
suivants) : un adaptateur traduit un protocole, il ne décide jamais qui est l'utilisateur.
Cette règle est ce qui garantit qu'ajouter un canal ne rouvre pas la question de sécurité.

Trois gestes, et trois seulement :
  • `request_link()`  — le canal propose ; rend un code à afficher dans la discussion.
  • `confirm_link()` — WAMA (session authentifiée) dispose ; scelle la liaison.
  • `account_for()`       — à chaque message : « de quel compte s'agit-il ? » ou None.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .models import CHANNEL_CHOICES, MAX_TENTATIVES, ChannelLink, _generate_code

logger = logging.getLogger(__name__)

CANAUX_CONNUS = {cle for cle, _ in CHANNEL_CHOICES}


class PairingError(Exception):
    """Refus d'appariement — le message est destiné à l'utilisateur final."""


def request_link(channel: str, external_id: str, external_label: str = '') -> ChannelLink:
    """
    Enregistre (ou renouvelle) une demande de liaison et rend la ligne portant le code.

    Renouveler plutôt qu'empiler : une même identité qui redemande une liaison obtient un
    NOUVEAU code et voit ses tentatives remises à zéro. Sans ça, une personne qui s'est
    trompée trois fois resterait bloquée jusqu'à expiration sans comprendre pourquoi.

    ⚠ Ne touche JAMAIS une liaison déjà confirmée : on ne peut pas se réapproprier une
    identité de canal en redemandant simplement un code.
    """
    if channel not in CANAUX_CONNUS:
        raise PairingError(f"Canal inconnu : {channel!r}.")
    if not (external_id or '').strip():
        raise PairingError("Identifiant de canal manquant.")

    with transaction.atomic():
        lien, cree = ChannelLink.objects.select_for_update().get_or_create(
            channel=channel, external_id=external_id.strip(),
            defaults={'external_label': external_label or ''},
        )
        if lien.is_confirmed:
            raise PairingError(
                "Cette identité est déjà reliée à un compte WAMA. "
                "Utilisez « délier » depuis WAMA avant d'en créer une autre."
            )
        # Demande renouvelée : code neuf, compteur remis à zéro, horloge relancée.
        lien.code = _generate_code()
        lien.tentatives = 0
        lien.created_at = timezone.now()
        if external_label:
            lien.external_label = external_label
        lien.save(update_fields=['code', 'tentatives', 'created_at', 'external_label'])

    logger.info("[gateway] demande de liaison %s:%s (%s)", channel, external_id,
                'nouvelle' if cree else 'renouvelée')
    return lien


def confirm_link(user, code: str) -> ChannelLink:
    """
    Scelle la liaison au profit de `user` — appelé DEPUIS WAMA, session authentifiée.

    C'est ici que la preuve d'identité est apportée : le compte lié est celui de l'appelant,
    jamais un compte nommé dans le canal. Un code volé dans une discussion ne sert donc qu'à
    se lier SOI-MÊME à l'identité de canal du voleur — ce qui ne donne aucun accès.

    Les tentatives sont comptées sur la ligne visée, et une ligne pilonnée devient
    définitivement inutilisable (il faut redemander un code depuis le canal).
    """
    code = (code or '').strip().upper()
    if not code:
        raise PairingError("Code manquant.")

    with transaction.atomic():
        lien = ChannelLink.objects.select_for_update().filter(code=code).first()
        if lien is None:
            # Aucune ligne à incrémenter : on ne révèle pas si le code a existé.
            raise PairingError("Code invalide ou expiré.")

        if lien.is_confirmed:
            raise PairingError("Ce code a déjà été utilisé.")

        lien.tentatives += 1
        if lien.code_expired or lien.tentatives > MAX_TENTATIVES:
            lien.save(update_fields=['tentatives'])
            raise PairingError("Code invalide ou expiré.")

        lien.user = user
        lien.confirmed_at = timezone.now()
        lien.save(update_fields=['user', 'confirmed_at', 'tentatives'])

    logger.info("[gateway] liaison confirmée %s:%s → %s", lien.channel, lien.external_id, user)
    return lien


def account_for(channel: str, external_id: str):
    """
    Compte WAMA d'une identité de canal, ou None.

    Appelé à CHAQUE message entrant : c'est la garde qui fait qu'un inconnu n'obtient
    rien. Un `None` doit se traduire par une invitation à se lier, jamais par un
    traitement « en anonyme » — le piège mesuré sur `/filemanager/api/upload/`, dont le
    `get_user()` retombait silencieusement sur l'utilisateur anonyme partagé.
    """
    lien = (ChannelLink.objects
            .filter(channel=channel, external_id=(external_id or '').strip())
            .exclude(user__isnull=True)
            .exclude(confirmed_at__isnull=True)
            .select_related('user')
            .first())
    if lien is None:
        return None
    # Trace de vivacité — utile pour purger les liaisons dormantes ; jamais bloquant.
    ChannelLink.objects.filter(pk=lien.pk).update(last_seen_at=timezone.now())
    return lien.user


def unlink(user, channel: str, external_id: str) -> bool:
    """Supprime une liaison — uniquement une des SIENNES. Rend True si quelque chose a sauté."""
    n, _ = ChannelLink.objects.filter(
        user=user, channel=channel, external_id=(external_id or '').strip()).delete()
    return n > 0
