"""
Passerelle de canaux — liaison entre une identité de canal et un compte WAMA.

LE PROBLÈME QUE CE MODULE RÉSOUT. Un message arrive de Discord ou de Tchap : la passerelle
sait seulement « l'utilisateur `@fabien:agent.dinum.tchap.gouv.fr` a écrit ceci ». Pour
exécuter quoi que ce soit, il lui faut un `User` Django — sans quoi elle ne peut ni scoper
les fichiers, ni appliquer le gating F7, ni savoir à qui appartient une file. La liaison
NE PEUT PAS être devinée (un identifiant de canal n'est pas une preuve d'identité) : elle
est PROUVÉE par un aller-retour hors canal, sur le modèle des codes d'appairage.

LE GESTE :
  1. dans le canal, la personne demande la liaison → la passerelle crée une demande et
     répond avec un CODE court ;
  2. la personne, DÉJÀ CONNECTÉE à WAMA, saisit ce code → c'est cette session authentifiée
     qui apporte la preuve d'identité, et la liaison est scellée sur SON compte.

Le canal ne choisit donc jamais le compte : il ne peut qu'en proposer la liaison, et c'est
WAMA qui la confirme. Un identifiant de canal usurpé ne mène nulle part sans un accès
authentifié à WAMA.

PAS DE `ScopedVisibility` ICI, contrairement à la plupart des modèles WAMA. Le scoping
commun sert à PARTAGER (unité, projet, public) ; or une liaison d'identité est un secret
strictement personnel — la partager n'a aucun sens et exposerait le canal privé de
quelqu'un. Le patron suivi est celui de `UserProfile` : une clé vers `auth.User`, et rien
d'autre. (Recommandation confirmée à l'exploration du 2026-08-21.)
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


#: Canaux gérés. La valeur est stable et sert de clé partout (adaptateurs, journal) ;
#: le libellé est ce que voit l'utilisateur.
CHANNEL_CHOICES = [
    ('matrix', 'Tchap / Matrix'),
    ('discord', 'Discord'),
]

#: Durée de validité d'un code d'appariement. Court par intention : le code circule dans un
#: canal de discussion, il ne doit pas y rester exploitable.
CODE_TTL = timedelta(minutes=15)

#: Alphabet du code — chiffres et majuscules SANS les caractères ambigus (0/O, 1/I/L).
#: Le code est lu à l'écran puis retapé à la main : l'ambiguïté produit des échecs que
#: l'utilisateur attribue au service, pas à la police de caractères.
_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'
CODE_LENGTH = 8

#: Au-delà, la demande est considérée comme attaquée et refusée définitivement. Le code
#: vit 15 minutes : sans plafond, un canal automatisé peut en essayer beaucoup.
MAX_TENTATIVES = 5


def _generer_code() -> str:
    """Code d'appariement — `secrets`, jamais `random` (il s'agit d'un jeton de sécurité)."""
    return ''.join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))


class ChannelLink(models.Model):
    """
    Une identité de canal rattachée (ou en cours de rattachement) à un compte WAMA.

    Deux états dans une seule table, distingués par `confirmed_at` :
      - EN ATTENTE (`user` NULL) : la demande existe, le code est vivant, rien n'est permis ;
      - CONFIRMÉE (`user` renseigné) : la passerelle peut agir au nom de ce compte.

    Une table unique plutôt que deux : l'état « en attente » et l'état « lié » portent les
    mêmes coordonnées de canal, et les séparer obligerait à recopier ces coordonnées puis à
    les tenir synchronisées.
    """

    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES,
                               verbose_name='Canal')
    #: Identifiant STABLE de la personne dans le canal (Matrix ID, Discord user id) — jamais
    #: son pseudo d'affichage, qui change et n'est pas unique.
    external_id = models.CharField(max_length=255, verbose_name="Identifiant dans le canal")
    #: Pseudo affiché au moment de la demande — confort de lecture pour la page de
    #: confirmation (« lier @Fabien ? »), JAMAIS une clé.
    external_label = models.CharField(max_length=255, blank=True, default='',
                                      verbose_name="Pseudo affiché")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             null=True, blank=True, related_name='channel_links',
                             verbose_name='Compte WAMA')

    code = models.CharField(max_length=16, default=_generer_code, db_index=True,
                            verbose_name="Code d'appariement")
    tentatives = models.PositiveSmallIntegerField(default=0,
                                                  verbose_name='Tentatives de code')

    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True,
                                        verbose_name='Liaison confirmée le')
    last_seen_at = models.DateTimeField(null=True, blank=True,
                                        verbose_name='Dernier message reçu')

    class Meta:
        verbose_name = 'Liaison de canal'
        verbose_name_plural = 'Liaisons de canal'
        # Une identité de canal ne peut être liée qu'à UN compte : sans cette contrainte,
        # deux demandes concurrentes produiraient deux liaisons confirmées et le compte
        # servi dépendrait de l'ordre des lignes.
        constraints = [
            models.UniqueConstraint(fields=['channel', 'external_id'],
                                    name='gateway_identite_canal_unique'),
        ]
        indexes = [models.Index(fields=['channel', 'external_id'])]

    def __str__(self):
        etat = f'→ {self.user}' if self.user_id else '(en attente)'
        return f'{self.get_channel_display()} {self.external_label or self.external_id} {etat}'

    # ── État ────────────────────────────────────────────────────────────────────
    @property
    def est_confirmee(self) -> bool:
        return self.user_id is not None and self.confirmed_at is not None

    @property
    def code_expire(self) -> bool:
        return timezone.now() - self.created_at > CODE_TTL

    def code_utilisable(self) -> bool:
        """Un code n'est utilisable que vivant, non consommé et pas encore pilonné."""
        return (not self.est_confirmee
                and not self.code_expire
                and self.tentatives < MAX_TENTATIVES)
