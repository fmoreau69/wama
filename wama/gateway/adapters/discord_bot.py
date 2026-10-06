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
import io
import logging
import os
from pathlib import Path

from django.conf import settings

from ..core import (FOLLOW_UP_INTERVAL_S, Attachment, IncomingMessage, collect_job_follow_ups,
                    handle_message, record_follow_up)

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
    relays = []

    @client.event
    async def on_ready():
        logger.info("[gateway/discord] connecté comme %s (%s salon(s) autorisé(s))",
                    client.user, len(salons_autorises) or 'tous')
        # ⚠ `on_ready` revient à CHAQUE reconnexion : une seule relève, jamais deux en parallèle.
        if not relays:
            relays.append(asyncio.create_task(_relay_job_follow_ups(client)))

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

        await _publish(message, reponse)

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


async def _relay_job_follow_ups(client):
    """La relève des fins de tâche (`core.collect_job_follow_ups`) : toutes les
    `FOLLOW_UP_INTERVAL_S` secondes, poster dans leur fil d'origine celles que le cœur a retenues.
    Le cœur décide QUOI et OÙ ; l'adaptateur ne fait que publier. Une relève qui échoue est
    journalisée et la suivante repart — un bot ne s'arrête pas sur une notification."""
    while not client.is_closed():
        try:
            # ORM + outil de statut : dans un thread, comme un tour d'assistant (cf. on_message).
            follow_ups = await asyncio.to_thread(collect_job_follow_ups, CANAL)
            for follow_up in follow_ups:
                await _deliver_follow_up(client, follow_up)
        except Exception:
            logger.exception("[gateway/discord] relève des fins de tâche en échec")
        await asyncio.sleep(FOLLOW_UP_INTERVAL_S)


async def _deliver_follow_up(client, follow_up):
    """Poste UNE fin de tâche dans son fil, puis l'enregistre au fil de conversation."""
    import dataclasses

    import discord

    try:
        channel = client.get_channel(int(follow_up.thread)) or \
            await client.fetch_channel(int(follow_up.thread))
    except (ValueError, discord.DiscordException):
        logger.warning("[gateway/discord] fil %s injoignable — fin de tâche non postée",
                       follow_up.thread)
        return
    reply = follow_up.reply
    if not isinstance(channel, discord.DMChannel):
        # Dans un salon partagé, un message du bot ne prévient personne : on MENTIONNE la
        # personne qui a demandé la tâche (en DM, la notification de Discord suffit).
        reply = dataclasses.replace(reply, text=f"<@{follow_up.external_id}> {reply.text}")
    await _publish_to(channel, reply)
    await asyncio.to_thread(record_follow_up, follow_up)


async def _publish(message, reply):
    """Publie la réponse à un message reçu."""
    await _publish_to(message.channel, reply, author=message.author)


async def _publish_to(channel, reply, author=None):
    """Publie une réponse dans un salon : texte tronçonné, puis les fichiers demandés — le geste
    COMMUN à la réponse à un message et à la fin de tâche postée dans son fil (2026-10-06)."""
    import discord

    # Une réponse privée (code d'appariement) ne doit JAMAIS être publiée dans un salon.
    target = author if (reply.private and author is not None) else channel
    try:
        for chunk in _chunk_text(reply.text):
            await target.send(chunk)
    except discord.Forbidden:
        # DM fermés : on ne re-publie pas un contenu privé dans le salon — on le dit.
        await channel.send(
            "⛔ Je ne peux pas vous écrire en privé (messages directs fermés), et ce "
            "contenu ne doit pas être publié ici. Ouvrez vos DM puis réessayez."
        )
        return

    # Pièces SORTANTES en mémoire (QR d'appariement…) : `discord.File` accepte un flux,
    # rien n'est écrit sur disque — un secret temporaire ne laisse pas de trace.
    for piece in reply.attachments:
        try:
            await target.send(file=discord.File(io.BytesIO(piece.content),
                                                filename=piece.name))
        except Exception:
            logger.exception("[gateway/discord] envoi de pièce impossible : %s", piece.name)

    for relative_path in reply.files:
        path = Path(settings.MEDIA_ROOT) / relative_path
        if not path.exists():
            continue
        try:
            sent = await target.send(file=discord.File(str(path), filename=path.name))
            await _caption_original(sent, path)
        except Exception:
            logger.exception("[gateway/discord] envoi de fichier impossible : %s", path)


async def _caption_original(message, path):
    """Ajoute au message le lien vers le fichier ORIGINAL, une fois qu'il est téléversé.

    ⚠⚠ POURQUOI (mesuré par Fabien le 2026-09-27). L'image apparaît dans le fil, on clique
    « enregistrer »… et on obtient un **webp de 75 Ko** quand WAMA a envoyé un **JPEG de
    445 203 octets**. Rien n'est recompressé de notre côté (`discord.File` lit le fichier tel
    quel) : ce qu'on enregistre depuis l'APERÇU est le proxy d'images de Discord, redimensionné
    et ré-encodé. L'original, lui, est la pièce jointe elle-même.
    *Un aperçu et un fichier se ressemblent à l'écran et ne pèsent pas la même chose.*

    L'URL de la pièce jointe n'existe qu'APRÈS le téléversement : on édite donc le message
    qu'on vient d'envoyer plutôt que d'en poster un second — un fil de résultats doit rester
    lisible. C'est aussi le « lien de téléchargement » qui manquait : il ne demande ni
    `WAMA_PUBLIC_URL` (absente à ce jour), ni de faire circuler un secret WAMA dans une
    messagerie — ce que la doctrine d'appariement refuse.

    ⚠ Ces URL de CDN portent une signature à durée de vie courte : le lien vaut pour la
    session de lecture, il n'est pas une adresse pérenne. Le dire plutôt que le laisser croire.
    """
    attached = next(iter(getattr(message, 'attachments', []) or []), None)
    if attached is None:
        return
    mb = path.stat().st_size / (1024 * 1024)
    try:
        await message.edit(content=(
            f"📥 **[{path.name}]({attached.url})** — {mb:.1f} Mo, fichier ORIGINAL "
            f"(l'aperçu ci-dessous est une version compressée par Discord ; lien temporaire)"))
    except Exception:
        # Une légende manquante ne doit jamais faire perdre la pièce jointe, qui est partie.
        logger.warning("[gateway/discord] légende d'original non posée : %s", path.name,
                       exc_info=True)


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
