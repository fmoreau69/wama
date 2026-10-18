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
import time
from pathlib import Path

from django.conf import settings

from ..core import (FOLLOW_UP_INTERVAL_S, Attachment, IncomingMessage, collect_job_follow_ups,
                    handle_message, told_follow_ups)

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
    #: Dernier message TRAITÉ par salon (id Discord) — le point de reprise du rattrapage.
    last_seen: dict = {}

    # `undelivered_since` (2026-10-18) : depuis quand une fin RACONTÉE au fil peut manquer au salon
    # (envoi échoué, ou démarrage — un arrêt a pu tomber entre l'enregistrement et la publication).
    # La relève confronte alors le fil à l'historique des salons et publie l'écart, au retour.
    health = {'tick': time.monotonic(), 'disconnected_since': None, 'undelivered_since': None}

    @client.event
    async def on_ready():
        logger.info("[gateway/discord] connecté comme %s (%s salon(s) autorisé(s))",
                    client.user, len(salons_autorises) or 'tous')
        health['disconnected_since'] = None
        # ⚠ `on_ready` revient à CHAQUE reconnexion : une seule relève, jamais deux en parallèle.
        if not relays:
            _mark_undelivered(health, _startup_window_start())
            relays.append(asyncio.create_task(_relay_job_follow_ups(client, health)))
            relays.append(asyncio.create_task(_loop_heartbeat(health)))
            _start_watchdog(health)
        elif last_seen:
            # NOUVELLE SESSION après une coupure (une simple reprise passe par `on_resumed`) :
            # Discord ne rejoue PAS ce qui a été écrit pendant la coupure. Mesuré le 2026-10-12
            # (fil #43) : deux sessions renouvelées, 14:58 et 15:16, et deux messages de Fabien
            # (14:54, 15:09) restés sans réponse ni trace — « tu disparais quand tu lances des
            # tâches ». On relit l'historique des salons actifs et on traite ce qui manque.
            logger.warning("[gateway/discord] session RENOUVELÉE après coupure — rattrapage "
                           "de %d salon(s)", len(last_seen))
            asyncio.create_task(_catch_up(client, last_seen, on_message))

    @client.event
    async def on_disconnect():
        logger.warning("[gateway/discord] connexion à Discord perdue")
        if health['disconnected_since'] is None:
            health['disconnected_since'] = time.monotonic()

    @client.event
    async def on_resumed():
        logger.info("[gateway/discord] session reprise (Discord rejoue les messages manqués)")
        health['disconnected_since'] = None

    @client.event
    async def on_message(message, missed: bool = False):
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

        # Point de reprise du rattrapage — seulement pour un message que le bot SERT.
        if last_seen.get(message.channel.id, 0) >= message.id:
            return                                   # déjà traité (rattrapage ∩ reprise)
        last_seen[message.channel.id] = message.id
        if missed:
            # Le DIRE : l'utilisateur a vu le bot absent, la réponse arrive en retard.
            await message.channel.send(
                f"↩️ Message de {message.created_at.astimezone():%H:%M} reçu pendant une coupure "
                f"de ma connexion à Discord — je le traite maintenant.")

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

        try:
            await _reply_to_message(message, reponse)
        except Exception:
            # La réponse a pu porter des fins de tâche RACONTÉES pendant le tour (`tell`, déjà au
            # fil) : la relève les publiera au retour du canal, après lecture de l'historique.
            _mark_undelivered(health, None)
            raise

    return client


# ── Le CHIEN DE GARDE de la passerelle (2026-10-12, fil #43) ─────────────────────────────────
# Deux sessions Discord renouvelées en vingt minutes, deux messages perdus, et aucune ligne pour
# dire pourquoi. Un fil SÉPARÉ de la boucle d'événements la surveille : si elle cesse de battre,
# il écrit la pile de TOUS les fils dans le journal — la cause, enfin lisible — puis relance le
# process si elle ne repart pas ; et il relance aussi une passerelle restée déconnectée.

#: Battement de la boucle d'événements (s).
HEARTBEAT_S = 5
#: Sans battement depuis tant de secondes, la boucle est GELÉE : pile des fils au journal.
LOOP_FROZEN_S = 60
#: Gelée depuis tant de secondes : le process se relance lui-même.
RESTART_FROZEN_S = 300
#: Déconnectée de Discord depuis tant de secondes : relance aussi (la bibliothèque n'y arrive plus).
RESTART_DISCONNECTED_S = 600


def watchdog_verdict(now: float, last_tick: float, disconnected_since) -> str:
    """`'ok'`, `'frozen'` (boucle sans battement) ou `'restart'`."""
    if now - last_tick > RESTART_FROZEN_S:
        return 'restart'
    if disconnected_since is not None and now - disconnected_since > RESTART_DISCONNECTED_S:
        return 'restart'
    if now - last_tick > LOOP_FROZEN_S:
        return 'frozen'
    return 'ok'


async def _loop_heartbeat(health: dict):
    while True:
        health['tick'] = time.monotonic()
        await asyncio.sleep(HEARTBEAT_S)


def _dump_threads(reason: str):
    """La pile de TOUS les fils dans le journal de la passerelle (sa sortie d'erreur)."""
    import faulthandler
    import sys

    logger.error("[gateway/discord] %s — pile des fils dans gateway-discord.log", reason)
    try:
        sys.stderr.write(f"\n===== {reason} =====\n")
        sys.stderr.flush()
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    except Exception:
        logger.exception("[gateway/discord] pile des fils impossible")


def _start_watchdog(health: dict):
    import sys
    import threading

    def watch():
        dumped = False
        while True:
            time.sleep(HEARTBEAT_S * 3)
            verdict = watchdog_verdict(time.monotonic(), health['tick'],
                                       health['disconnected_since'])
            if verdict == 'ok':
                dumped = False
            elif verdict == 'frozen' and not dumped:
                _dump_threads(f"boucle d'événements GELÉE depuis plus de {LOOP_FROZEN_S} s")
                dumped = True
            elif verdict == 'restart':
                _dump_threads("passerelle relancée par son chien de garde")
                # Même process (pid, journaux redirigés), code et connexion neufs.
                os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=watch, name='gateway-watchdog', daemon=True).start()


#: Au-delà de cet âge, un message manqué n'est plus rattrapé : y répondre des heures plus tard
#: surprendrait plus qu'il n'aiderait. Et un plafond de messages par salon.
CATCH_UP_MAX_AGE_S = 3600
CATCH_UP_MAX_MESSAGES = 20


async def _catch_up(client, last_seen: dict, handle) -> int:
    """Traite, dans l'ordre, les messages écrits pendant une coupure dans les salons ACTIFS
    (ceux où le bot a déjà répondu dans ce process). `handle(message, missed=True)` est le
    `on_message` du client : mêmes filtres, même tour — rien n'est dupliqué. Rend le nombre de
    messages repris. Une erreur de lecture d'un salon n'arrête pas les autres."""
    from datetime import datetime, timedelta, timezone

    import discord

    oldest = datetime.now(timezone.utc) - timedelta(seconds=CATCH_UP_MAX_AGE_S)
    count = 0
    for channel_id, last_id in list(last_seen.items()):
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            async for message in channel.history(after=discord.Object(id=last_id),
                                                 oldest_first=True,
                                                 limit=CATCH_UP_MAX_MESSAGES):
                if message.author.bot or message.created_at < oldest:
                    continue
                await handle(message, missed=True)
                count += 1
        except Exception:
            logger.exception("[gateway/discord] rattrapage impossible pour le salon %s", channel_id)
    if count:
        logger.warning("[gateway/discord] %d message(s) manqué(s) rattrapé(s)", count)
    return count


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


#: Marge (s) sous l'heure d'un récit pour le chercher dans l'historique du salon : les horloges
#: de WAMA et de Discord ne sont pas la même.
SHOWN_MARGIN_S = 60
#: Messages lus, au plus, après un récit pour savoir s'il a été montré.
SHOWN_SCAN_MESSAGES = 50


def _startup_window_start():
    """Au démarrage, la fenêtre à vérifier : celle du rattrapage des messages (`CATCH_UP_MAX_AGE_S`)
    — au-delà, publier une fin de tâche surprendrait plus qu'elle n'aiderait."""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) - timedelta(seconds=CATCH_UP_MAX_AGE_S)


def _mark_undelivered(health, since):
    """Une fin RACONTÉE au fil peut manquer au salon depuis `since` (None = maintenant, moins la
    marge) : la relève confrontera le fil à l'historique du salon au prochain passage."""
    from datetime import datetime, timedelta, timezone
    since = since or datetime.now(timezone.utc) - timedelta(seconds=SHOWN_MARGIN_S)
    current = health.get('undelivered_since')
    health['undelivered_since'] = since if current is None else min(current, since)


async def _relay_job_follow_ups(client, health=None):
    """La relève des fins de tâche (`core.collect_job_follow_ups`) : toutes les
    `FOLLOW_UP_INTERVAL_S` secondes, poster dans leur fil d'origine celles que le cœur a retenues.
    Le cœur décide QUOI et OÙ ; l'adaptateur ne fait que publier. Une relève qui échoue est
    journalisée et la suivante repart — un bot ne s'arrête pas sur une notification.

    Un envoi qui échoue (Discord en panne, refus ponctuel) marque `health['undelivered_since']` ;
    dès que le client est de nouveau prêt, la relève publie ce que le fil a raconté et que le salon
    ne montre pas (`_redeliver_follow_ups`) — puis efface la marque."""
    health = health if health is not None else {}
    while not client.is_closed():
        try:
            since = health.get('undelivered_since')
            if since is not None and getattr(client, 'is_ready', lambda: True)():
                if await _redeliver_follow_ups(client, since):
                    health['undelivered_since'] = None
            # ORM + outil de statut : dans un thread, comme un tour d'assistant (cf. on_message).
            follow_ups = await asyncio.to_thread(collect_job_follow_ups, CANAL)
            for follow_up in follow_ups:
                if not await _deliver_follow_up(client, follow_up):
                    _mark_undelivered(health, follow_up.told_at)
        except Exception:
            logger.exception("[gateway/discord] relève des fins de tâche en échec")
        await asyncio.sleep(FOLLOW_UP_INTERVAL_S)


async def _deliver_follow_up(client, follow_up) -> bool:
    """Poste UNE fin de tâche dans son fil — déjà enregistrée au fil (`tell`). Rend False si
    l'envoi a échoué et doit être repris au retour du canal ; True s'il a eu lieu, ou si le fil est
    définitivement injoignable (supprimé, accès retiré : le reprendre ne servirait à rien)."""
    import dataclasses

    import discord

    try:
        channel = client.get_channel(int(follow_up.thread)) or \
            await client.fetch_channel(int(follow_up.thread))
    except (ValueError, discord.NotFound, discord.Forbidden):
        logger.warning("[gateway/discord] fil %s injoignable — fin de tâche non postée",
                       follow_up.thread)
        return True
    except Exception:
        logger.warning("[gateway/discord] fil %s non joint — fin de tâche reprise au retour",
                       follow_up.thread, exc_info=True)
        return False
    reply = follow_up.reply
    if not isinstance(channel, discord.DMChannel):
        # Dans un salon partagé, un message du bot ne prévient personne : on MENTIONNE la
        # personne qui a demandé la tâche (en DM, la notification de Discord suffit).
        reply = dataclasses.replace(reply, text=f"<@{follow_up.external_id}> {reply.text}")
    try:
        await _publish_to(channel, reply)
    except Exception:
        logger.warning("[gateway/discord] fin de tâche non publiée (fil %s) — reprise au retour "
                       "du canal", follow_up.thread, exc_info=True)
        return False
    return True


async def _redeliver_follow_ups(client, since) -> bool:
    """Publie les fins RACONTÉES au fil depuis `since` que le salon ne montre pas (2026-10-18).

    Rien de neuf n'est tenu : le FIL dit ce qui a été raconté (`core.told_follow_ups`), l'HISTORIQUE
    du salon ce qui a été montré — la lecture même du rattrapage des messages (`_catch_up`). Une fin
    montrée n'est jamais republiée. Bornée par `CATCH_UP_MAX_AGE_S`. Rend True quand plus rien ne
    manque."""
    follow_ups = await asyncio.to_thread(told_follow_ups, CANAL, max(since, _startup_window_start()))
    complete, published = True, 0
    for follow_up in follow_ups:
        try:
            if await _shown_in_channel(client, follow_up):
                continue
        except Exception:
            logger.warning("[gateway/discord] historique du fil %s illisible — vérifié au prochain "
                           "passage", follow_up.thread, exc_info=True)
            complete = False
            continue
        if await _deliver_follow_up(client, follow_up):
            published += 1
        else:
            complete = False
    if published:
        logger.warning("[gateway/discord] %d fin(s) de tâche republiée(s) au retour du canal", published)
    return complete


async def _shown_in_channel(client, follow_up) -> bool:
    """Le salon montre-t-il ce récit ? Un message du bot, après son heure, qui en porte la 1ʳᵉ ligne
    (la mention et les morceaux d'un long message n'y changent rien)."""
    from datetime import timedelta

    try:
        thread = int(follow_up.thread)
    except (TypeError, ValueError):
        return True                         # fil sans identifiant de salon : rien à vérifier
    first_line = (follow_up.reply.text or '').strip().splitlines()[0] if follow_up.reply.text else ''
    if not first_line or follow_up.told_at is None:
        return True
    channel = client.get_channel(thread) or await client.fetch_channel(thread)
    async for message in channel.history(after=follow_up.told_at - timedelta(seconds=SHOWN_MARGIN_S),
                                         limit=SHOWN_SCAN_MESSAGES):
        if message.author.id == client.user.id and first_line in (message.content or ''):
            return True
    return False


async def _reply_to_message(message, reply):
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
    # ⚠ L'URL entre CHEVRONS (`[nom](<url>)`) : sans eux, Discord DÉPLIE le lien en aperçu, et
    # comme il pointe sur la pièce jointe elle-même, l'image s'affichait DEUX fois sous le message
    # (relevé par Fabien le 2026-10-06). Les chevrons ne retirent que l'aperçu de CE lien.
    try:
        await message.edit(content=(
            f"📥 **[{path.name}](<{attached.url}>)** — {mb:.1f} Mo, fichier ORIGINAL "
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
