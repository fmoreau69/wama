"""
Adaptateur DISCORD — traduit le protocole, ne décide rien.

Tout ce qui est une décision (qui est l'utilisateur, a-t-il le droit, que répondre, que
faire d'une pièce jointe) vit dans `gateway/core.py` et est partagé avec les futurs
adaptateurs. Ce fichier ne contient donc que : écouter, traduire, répondre.

MODÈLE D'USAGE ARRÊTÉ PAR FABIEN (2026-08-21) : **WAMA n'entre PAS dans les canaux du
laboratoire.** Il a SON canal sur le serveur, et les échanges se font en tête-à-tête — DM,
ou ce canal dédié. Le labo n'acceptera pas autre chose tant que l'outil n'a pas fait ses
preuves, et c'est la position prudente.

CE QUI EST DÉLIBÉRÉMENT RESTREINT :
  • `WAMA_DISCORD_ALLOWED_CHANNELS` borne les salons servis (patron `allowed_room_ids`
    recommandé par la doc DINUM pour Tchap — la garde est bonne partout). Avec le seul
    canal WAMA déclaré, le bot ne PEUT structurellement pas répondre ailleurs ;
  • dans un salon NON déclaré, le bot ne répond QUE s'il est mentionné — un bot qui lit
    tout un salon de labo est une aspiration de données que personne n'a demandée ;
  • dans le canal DÉDIÉ (déclaré), il répond sans mention : exiger `@WAMA` à chaque message
    dans un salon qui lui appartient serait une friction absurde ;
  • aucune réponse à un autre bot, ni à soi-même (boucles de bots).

⚠ CE QU'UN CANAL DÉDIÉ PARTAGÉ N'EST PAS. Les conversations y restent séparées par
utilisateur (un fil = `user` + salon, cf. `conversation_store`), mais les RÉPONSES y sont
lisibles par tous ceux qui voient le salon. Pour des données de recherche, le tête-à-tête
en DM reste le mode sûr ; le canal dédié convient aux demandes anodines et à la découverte.

⚠ Discord est propriétaire et hors UE. Pour des données de recherche sensibles, c'est
Tchap qui est la cible ; Discord sert d'abord le confort d'usage du labo et le
développement de la passerelle (ni compte mail, ni E2EE, ni renouvellement annuel).
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from django.conf import settings

from ..core import IncomingMessage, Attachment, handle_message

logger = logging.getLogger(__name__)

CANAL = 'discord'

#: Limite dure d'un message Discord. Au-delà, la réponse est découpée.
LIMITE_DISCORD = 2000

#: Plafond de taille d'une pièce jointe ENTRANTE, en Mo. Une passerelle ne doit pas
#: permettre de remplir le disque du serveur depuis une messagerie.
MAX_ENTREE_MO = 25


def _chunk_text(text: str, limite: int = LIMITE_DISCORD):
    """Découpe une réponse longue en messages, en coupant de préférence sur un saut de ligne."""
    text = text or '(réponse vide)'
    morceaux = []
    while len(text) > limite:
        coupe = text.rfind('\n', 0, limite)
        if coupe < limite // 2:          # pas de saut de ligne exploitable
            coupe = limite
        morceaux.append(text[:coupe])
        text = text[coupe:].lstrip('\n')
    morceaux.append(text)
    return morceaux


def build_client():
    """Construit le client Discord. Import TARDIF : sans la dépendance, WAMA tourne normalement."""
    try:
        import discord
    except ImportError as e:  # pragma: no cover — dépend de l'environnement
        raise RuntimeError(
            "discord.py n'est pas installé. `pip install 'discord.py>=2.4'` "
            "(déclaré dans requirements.txt)."
        ) from e

    intents = discord.Intents.default()
    # Le CONTENU des messages est un intent privilégié : il doit AUSSI être coché dans le
    # portail développeur Discord (Bot → Privileged Gateway Intents → Message Content).
    # Sans ça le bot reçoit les événements mais `message.content` arrive VIDE — panne
    # silencieuse classique, qui ressemble à un bot qui « ignore » les messages.
    intents.message_content = True

    client = discord.Client(intents=intents)
    salons_autorises = _allowed_channels()

    @client.event
    async def on_ready():
        logger.info("[gateway/discord] connecté comme %s (%s salon(s) autorisé(s))",
                    client.user, len(salons_autorises) or 'tous')

    @client.event
    async def on_message(message):
        if message.author.bot:                       # soi-même et les autres bots
            return

        prive = isinstance(message.channel, discord.DMChannel)
        mentionne = client.user in getattr(message, 'mentions', [])
        # Salon DÉDIÉ = salon explicitement déclaré dans WAMA_DISCORD_ALLOWED_CHANNELS.
        # C'est le modèle d'usage retenu : WAMA a SON canal, on n'y écrit pas `@WAMA` à
        # chaque message. Ailleurs, la mention reste obligatoire.
        dedie = (not prive) and str(message.channel.id) in salons_autorises

        if not prive and not dedie and not mentionne:
            return

        # Salon ni dédié ni autorisé → on se tait, même mentionné. La liste blanche prime
        # sur la mention : n'importe qui peut mentionner un bot depuis n'importe où.
        if salons_autorises and not prive and not dedie:
            logger.debug("[gateway/discord] salon %s non autorisé", message.channel.id)
            return

        text = message.content or ''
        if mentionne:                                # retirer la mention du texte utile
            text = text.replace(f'<@{client.user.id}>', '').replace(
                f'<@!{client.user.id}>', '').strip()

        pieces = await _recuperer_pieces_jointes(message)

        entrant = IncomingMessage(
            channel=CANAL,
            external_id=str(message.author.id),      # identifiant STABLE, jamais le pseudo
            external_label=getattr(message.author, 'display_name', '') or str(message.author),
            text=text,
            thread=str(message.channel.id),             # un salon/DM = une conversation
            attachments=pieces,
        )

        async with message.channel.typing():
            # ⚠ DANS UN THREAD : le tour d'assistant est bloquant (dizaines de secondes) et
            # touche l'ORM. L'appeler dans la boucle d'événements figerait le bot pour TOUS
            # les utilisateurs pendant qu'une seule personne attend son résultat.
            reponse = await asyncio.to_thread(handle_message, entrant)

        await _publier(message, reponse)

    return client


async def _recuperer_pieces_jointes(message) -> list:
    """Télécharge les pièces jointes, en refusant celles qui dépassent le plafond."""
    pieces = []
    for piece in getattr(message, 'attachments', []):
        if piece.size > MAX_ENTREE_MO * 1024 * 1024:
            logger.info("[gateway/discord] pièce jointe refusée (%.1f Mo) : %s",
                        piece.size / 1024 / 1024, piece.filename)
            continue
        try:
            pieces.append(Attachment(name=piece.filename, content=await piece.read()))
        except Exception:
            logger.exception("[gateway/discord] téléchargement impossible : %s", piece.filename)
    return pieces


async def _publier(message, reponse):
    """Publie la réponse : texte tronçonné, puis les fichiers demandés."""
    import discord

    # Une réponse privée (code d'appariement) ne doit JAMAIS être publiée dans un salon.
    cible = message.author if reponse.private else message.channel
    try:
        for morceau in _chunk_text(reponse.text):
            await cible.send(morceau)
    except discord.Forbidden:
        # DM fermés : on ne re-publie pas un contenu privé dans le salon — on le dit.
        await message.channel.send(
            "⛔ Je ne peux pas vous écrire en privé (messages directs fermés), et ce "
            "contenu ne doit pas être publié ici. Ouvrez vos DM puis réessayez."
        )
        return

    for chemin_relatif in reponse.files:
        chemin = Path(settings.MEDIA_ROOT) / chemin_relatif
        if not chemin.exists():
            continue
        try:
            await cible.send(file=discord.File(str(chemin), filename=chemin.name))
        except Exception:
            logger.exception("[gateway/discord] envoi de fichier impossible : %s", chemin)


def bot_token() -> str:
    """Jeton du bot — variable d'environnement UNIQUEMENT, jamais un réglage versionné."""
    valeur = os.environ.get('WAMA_DISCORD_TOKEN') or getattr(
        settings, 'WAMA_DISCORD_TOKEN', '')
    if not valeur:
        raise RuntimeError(
            "WAMA_DISCORD_TOKEN absent. Créez une application sur "
            "https://discord.com/developers/applications (onglet Bot), copiez le bot_token, "
            "puis renseignez-le dans le fichier .env — jamais dans le dépôt."
        )
    return valeur


def _allowed_channels() -> set:
    """Salons servis (ids séparés par des virgules). Vide = tous les salons où le bot est."""
    brut = os.environ.get('WAMA_DISCORD_ALLOWED_CHANNELS', '') or getattr(
        settings, 'WAMA_DISCORD_ALLOWED_CHANNELS', '')
    return {s.strip() for s in brut.split(',') if s.strip()}
