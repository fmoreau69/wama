"""
Passerelle de canaux — le cœur, celui qui ne connaît AUCUN protocole.

RÈGLE FONDATRICE DE CE MODULE : un adaptateur traduit un protocole, il ne décide jamais
rien. Tout ce qui est une décision — qui est l'utilisateur, a-t-il le droit, que répondre,
que faire d'une pièce jointe — vit ICI, une seule fois, et vaut pour Discord comme pour
Tchap/Matrix comme pour le canal suivant. C'est la seule manière d'ajouter un canal sans
rouvrir la question de sécurité à chaque fois : un adaptateur qui n'a pas de logique n'a
pas de faille propre.

Un adaptateur n'a donc que trois obligations :
  1. traduire un événement du protocole en `IncomingMessage` ;
  2. appeler `handle_message()` ;
  3. rendre la `Reply` dans les termes de son protocole (text, files).

⚠ `handle_message()` est SYNCHRONE et BLOQUANTE (un tour d'assistant peut prendre des
dizaines de secondes). Les bibliothèques de bots sont asynchrones : un adaptateur doit
l'appeler dans un thread (`asyncio.to_thread`), jamais directement dans la boucle
d'événements — sinon le bot cesse de répondre à tout le monde pendant qu'un utilisateur
attend son résultat. Cela règle aussi l'accès ORM, interdit en contexte async.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .services import (PairingError, account_for, linked_identity, pairing_url, unlink,
                       request_link)

logger = logging.getLogger(__name__)

#: LES CANAUX SERVIS — domicile unique. Un canal = un module dans `gateway/adapters/` ;
#: ajouter un canal, c'est ajouter une entrée ici et ce module, sans toucher au cœur.
#: Deux consommateurs : `run_gateway` (choix de la commande) et le moteur de l'assistant, qui
#: y lit quelles SURFACES joignent les fichiers produits — c'est la passerelle qui les joint,
#: elle seule sait pour qui. ⚠ `Conversation.SURFACES` est une autre liste et le reste : elle
#: dit quelles surfaces EXISTENT (web et api comprises), pas lesquelles sont un canal.
CHANNELS = ('discord',)

#: Longueur au-delà de laquelle une réponse est coupée par l'adaptateur. Chaque protocole a
#: sa propre limite (Discord : 2000 caractères) — la valeur réelle est celle de l'adaptateur,
#: celle-ci n'est qu'un repli.
TEXT_LIMIT = 2000

# L'historique de conversation vivait ici, dans un dict EN MÉMOIRE DU PROCESS
# (`_HISTORIQUES`) : perdu à chaque redémarrage de la passerelle, non partagé entre process,
# et invisible depuis le web. Il est REMPLACÉ (2026-08-21) par le store commun
# `common/services/conversation_store.py` — le même que la surface web, de sorte qu'un fil
# ouvert dans Discord et la liste des conversations du navigateur parlent enfin de la même
# chose. Le geste de la passerelle se résume désormais à nommer son fil (`_thread_key`).


@dataclass
class Attachment:
    """Une pièce jointe EN MÉMOIRE — entrante (déjà téléchargée par l'adaptateur) ou
    sortante (à publier par lui, sans jamais passer par le disque)."""
    name: str
    content: bytes


@dataclass
class IncomingMessage:
    """Ce qu'un adaptateur doit produire, quel que soit le protocole."""
    channel: str                    # 'discord' | 'matrix'
    external_id: str                # identifiant STABLE de la personne (jamais son pseudo)
    text: str
    external_label: str = ''        # pseudo affiché, confort de lecture seulement
    thread: str = ''                   # identifiant du fil/salon → une conversation par fil
    attachments: list = field(default_factory=list)


@dataclass
class Reply:
    """Ce que l'adaptateur doit rendre dans son protocole."""
    text: str
    #: Chemins relatifs à MEDIA_ROOT que l'adaptateur doit joindre. Vide la plupart du temps.
    files: list = field(default_factory=list)
    #: `Attachment` sortants, EN MÉMOIRE (QR d'appariement…) — jamais écrits sur disque :
    #: un secret temporaire n'a pas à laisser de trace dans MEDIA_ROOT, et `media/` ne
    #: loge que les entrées/sorties des utilisateurs (doctrine des emplacements).
    attachments: list = field(default_factory=list)
    #: True quand la réponse ne doit PAS être publiée dans un salon (code d'appariement…).
    private: bool = False


HELP_TEXT = (
    "**WAMA** — ce que je sais faire ici :\n"
    "• `!lier` — relier ce compte de discussion à votre compte WAMA (obligatoire)\n"
    "• `!delier` — supprimer la liaison\n"
    "• `!code <question>` — déléguer une question SUR LE DÉPÔT à Claude Code "
    "(développeurs/admins ; consomme l'abonnement)\n"
    "• `!oublier` — effacer la conversation de ce fil et repartir de zéro\n"
    "• `!aide` — ce message\n"
    "Sinon, écrivez simplement ce que vous voulez faire : « transcris le fichier que je "
    "viens d'envoyer », « où en est ma transcription ? ». Les pièces jointes sont déposées "
    "dans votre espace WAMA."
)


def _thread_key(msg: IncomingMessage) -> str:
    """
    Clé du fil DANS sa surface — un salon/DM = une conversation.

    À défaut de fil déclaré par l'adaptateur, l'identité de la personne fait office de fil :
    un canal qui n'a pas la notion de salon reste ainsi une conversation par interlocuteur,
    jamais un fil global où tout le monde se mélangerait.
    """
    return msg.thread or msg.external_id


def handle_message(msg: IncomingMessage) -> Reply:
    """
    Traite UN message entrant et rend ce que l'adaptateur doit publier.

    Ne lève pas : toute erreur devient une réponse lisible. Un bot qui plante sur un message
    cesse de servir tous les autres utilisateurs du salon.
    """
    try:
        return _handle(msg)
    except PairingError as e:
        return Reply(text=f"⛔ {e}", private=True)
    except Exception:
        logger.exception("[gateway] échec de traitement (%s:%s)", msg.channel, msg.external_id)
        return Reply(text="⚠ Une erreur interne est survenue. Elle a été journalisée.")


def _handle(msg: IncomingMessage) -> Reply:
    texte = (msg.text or '').strip()
    commande = texte.split()[0].lower() if texte else ''

    if commande in ('!aide', '!help'):
        return Reply(text=HELP_TEXT)

    user = account_for(msg.channel, msg.external_id)

    # ── Appariement ──────────────────────────────────────────────────────────────
    if commande == '!lier':
        if user is not None:
            return Reply(text=f"✅ Ce compte est déjà relié à **{user.username}**.", private=True)
        lien = request_link(msg.channel, msg.external_id, msg.external_label)
        texte = (
            f"🔑 Code d'appariement : **{lien.code}**\n"
            "Connectez-vous à WAMA, puis saisissez ce code dans votre profil.\n"
            "_Il expire dans 15 minutes. Ne le communiquez à personne : c'est la session "
            "WAMA qui saisit le code qui obtiendra l'accès à ce compte de discussion._"
        )
        pieces = _pairing_qr(lien.code)
        if pieces:
            texte += (
                "\n_Ou scannez le QR joint : il ouvre votre page de profil avec le code "
                "prérempli — la validation reste le bouton « Relier », connecté à WAMA._"
            )
        return Reply(private=True, text=texte, attachments=pieces)

    if commande == '!delier':
        if user is None:
            return Reply(text="Ce compte n'est relié à aucun compte WAMA.", private=True)
        unlink(user, msg.channel, msg.external_id)
        return Reply(text="🔓 Liaison supprimée.", private=True)

    # ── Garde : un inconnu n'obtient RIEN ────────────────────────────────────────
    # ⚠ Ne JAMAIS retomber sur un traitement « en anonyme » : c'est exactement le piège
    # mesuré sur `/filemanager/api/upload/`, dont le `get_user()` basculait silencieusement
    # sur l'utilisateur anonyme partagé. Ici, l'absence de compte est une FIN de parcours.
    if user is None:
        return Reply(private=True, text=(
            "👋 Je ne sais pas encore qui vous êtes dans WAMA.\n"
            "Envoyez `!lier` pour obtenir un code d'appariement."
        ))

    # ── Repartir d'un fil vierge ─────────────────────────────────────────────────
    # Le « Effacer » du chat web, pour un canal (2026-10-05) : un fil où une fabrication est
    # entrée la resservait au modèle à chaque tour (`WAMA_LLM.md` §2026-10-05). Même brique que
    # le web (`conversation_store.clear_thread`) ; seul CE fil part, jamais les autres.
    if commande in ('!oublier', '!forget'):
        from wama.common.services import conversation_store
        if conversation_store.clear_thread(user, surface=msg.channel,
                                           thread_key=_thread_key(msg)):
            return Reply(private=True, text="🧹 Conversation effacée : je repars de zéro.")
        return Reply(private=True, text="Il n'y avait rien à effacer dans ce fil.")

    # ── Délégation au dépôt via Claude Code — geste EXPLICITE ────────────────────
    # ⚠ POURQUOI UN GESTE, et pas « le modèle décidera » : en Discord le tour part sur le
    # fournisseur LOCAL (défaut `wama-dev-ai` de `conversation_turn`), donc ce serait à un
    # PETIT modèle de décider d'appeler `ask_claude_code` — jamais mesuré, et structurellement
    # fragile. Le geste rend le chemin déterministe et VISIBLE (il est dans `!aide`) : c'était
    # le trou réel du chantier §19.3, qui était d'ergonomie et non de câblage.
    # La GARDE reste celle de l'outil (`subscription_allowed`, domicile unique) : on l'APPELLE,
    # on ne la réimplémente pas ici — une garde recopiée est une garde qui dérive.
    if commande == '!code':
        question = texte[len('!code'):].strip()
        # ⚠ `private=True` sur TOUTES les issues de ce geste (aligné sur `!lier`/`!delier`) :
        # une réponse sur le CODE du dépôt n'a pas à être publiée dans un salon partagé, et
        # un refus « réservé aux développeurs » annonce publiquement qui n'a pas le droit.
        if not question:
            return Reply(private=True,
                         text="Usage : `!code <votre question sur le dépôt>`\n"
                              "_Exemple : `!code où est décidé le nom d'un fichier de sortie ?`_")
        from wama.tool_api import ask_claude_code
        resultat = ask_claude_code(user, question)
        if 'error' in resultat:
            return Reply(private=True,
                         text=f"⛔ {resultat.get('detail') or resultat['error']}")
        cout = resultat.get('cost_usd')
        # Le coût est AFFICHÉ : ce chemin n'est pas gratuit en crédit mensuel, et un chemin
        # dont on ne voit jamais le prix finit par être pris pour du bavardage.
        pied = (f"\n\n_~{cout:.3f} $ d'équivalent-API imputés à l'abonnement "
                f"(cache chaud ≈ 0,03 $, froid ≈ 0,5 $)._") if cout else ''
        return Reply(private=True,
                     text=f"{resultat.get('response') or '(réponse vide)'}{pied}")

    # ── Pièces jointes → espace WAMA de l'utilisateur ────────────────────────────
    deposes = _store_attachments(user, msg.attachments)

    if not texte and not deposes:
        return Reply(text=HELP_TEXT)

    # ── Le tour d'assistant : MÊME moteur ET MÊME store que la page web ─────────
    from wama.common.services.assistant_engine import conversation_turn

    invite = texte
    if deposes:
        liste = ', '.join(f"`{d['path']}`" for d in deposes)
        entete = f"[Fichiers déposés dans mon espace WAMA : {liste}]"
        invite = f"{entete}\n{texte}" if texte else f"{entete}\nQue puis-je en faire ?"

    # L'historique est résolu et persisté SERVEUR (plus de dict en mémoire du process) :
    # la passerelle n'a qu'à nommer son fil.
    resultat = conversation_turn(user, invite, surface=msg.channel,
                                    thread_key=_thread_key(msg))

    if 'error' in resultat:
        return Reply(text=f"⚠ {resultat['error']}")

    # Les fichiers PRODUITS pendant le tour repartent avec la réponse : sans ça, le code
    # d'envoi des adaptateurs est mort et l'utilisateur reçoit un lien `/media/…` protégé
    # par session, inutilisable hors WAMA (défaut mesuré 2026-08-29, WAMA_LLM §Vérification).
    return _reply_with_outputs(resultat.get('response') or '(réponse vide)',
                               resultat.get('tool_steps'))


def _reply_with_outputs(body: str, tool_steps) -> Reply:
    """La réponse et les fichiers produits que portent ces étapes d'outils — UN geste pour la
    réponse à un message et pour la fin de tâche postée dans le fil (2026-10-06)."""
    sendable, oversized = _produced_files({'tool_steps': tool_steps or []})
    if oversized:
        # Le DIRE plutôt que de laisser l'utilisateur devant une réponse « c'est terminé »
        # sans pièce jointe. Le texte part avec la réponse, donc il vaut pour TOUT canal.
        details = ' · '.join(f"{name} ({mb:.1f} Mo)" for name, mb in oversized)
        body += (f"\n\n⚠ Trop volumineux pour ce canal : {details}. "
                 f"Le fichier est bien produit — récupérez-le dans WAMA.")
    return Reply(text=body, files=sendable)


def _pairing_qr(code: str) -> list:
    """
    QR joint au code d'appariement — même geste, retape en moins.

    Le QR encode l'URL de la page de profil avec le code prérempli (`pairing_url`) : le
    smartphone qui le scanne arrive sur la page, l'utilisateur SE CONNECTE, et c'est
    toujours le clic « Relier » de la session authentifiée qui scelle — le QR ne change
    RIEN au modèle « le canal propose, WAMA dispose ».

    Deux replis, aucun MUET (« ce qui ne plante pas ne se signale pas ») :
      • URL publique absente → pas de QR, dit en DEBUG (configuration assumée) ;
      • échec de génération → pas de QR, dit en WARNING (défaut réel à voir).
    Dans les deux cas le code TEXTE part : le QR est un confort, jamais le chemin.
    """
    url = pairing_url(code)
    if not url:
        logger.debug("[gateway] WAMA_PUBLIC_URL absent — code d'appariement sans QR")
        return []
    try:
        from wama.common.utils.qr import qr_png
        return [Attachment(name='wama-appariement.png', content=qr_png(url))]
    except Exception:
        logger.warning("[gateway] QR d'appariement non généré — le code seul est envoyé",
                       exc_info=True)
        return []


#: Clés de résultat d'outil qui désignent une sortie fichier (contrat des triades tool_api).
_OUTPUT_KEYS = ('output_urls', 'output_url', 'file_url', 'video_url', 'audio_url', 'image_url')
#: Bornes d'envoi : nombre de pièces, et octets par pièce (limite Discord la plus basse).
_MAX_OUTPUT_FILES = 5
_MAX_OUTPUT_BYTES = 24 * 1024 * 1024
#: Profondeur de descente dans un résultat d'outil. MESURÉE, pas choisie : les dix
#: `get_<app>_status` rendent `{"jobs": [{…, "output_url": …}]}` (`tool_api.py:320-328`,
#: `:503-512`, et la triade générée `:3523`) — la clé de sortie est au 2ᵉ niveau
#: (dict → liste → dict). 4 laisse la marge d'un `detail` imbriqué (`get_item_detail`) sans
#: ouvrir une descente illimitée dans une structure qu'un outil compose librement.
_MAX_OUTPUT_DEPTH = 4


def _produced_files(resultat) -> list:
    """Chemins MEDIA_ROOT-relatifs des sorties produites pendant le tour (lus des tool_steps).

    Seules les URLs `/media/…` résolues SOUS MEDIA_ROOT sont retenues — un résultat d'outil
    est une donnée, pas une autorisation de lire le disque. Bornés en nombre et en taille.

    ⚠⚠ CE QUI ÉTAIT FAUX JUSQU'AU 2026-09-23. Cette fonction ne lisait que le PREMIER niveau
    du résultat (`contenu.get('output_url')`), forme qu'AUCUN outil de WAMA ne produit : les
    dix `get_<app>_status` nichent la sortie sous `jobs[]`. `Reply.files` restait donc vide
    quoi qu'il arrive, et le code d'envoi des adaptateurs était mort — le défaut même que le
    correctif du 29/08 croyait avoir levé. Il a survécu parce que ses trois tests
    construisaient une forme SYNTHÉTIQUE (`{'output_urls': [...]}` à plat) au lieu de la
    forme mesurée des outils : *une mesure qui ignore une forme rend un verdict inverse.*
    Mesuré le 2026-09-23 sur un tour Discord réel (conversation #11, 22/09 20:42).

    ⚠ UN SEUL ÉLÉMENT PAR LISTE DE CONTENEURS. Un `get_<app>_status` rend les DIX derniers
    jobs, triés `-id` (vérifié : les dix outils et la triade générée trient tous ainsi) —
    descendre dans tous republierait à CHAQUE question de statut cinq sorties déjà
    récupérées. Le premier élément est le plus récent, c'est-à-dire celui dont on parle. Une
    liste trouvée SOUS une clé de sortie (`output_urls` d'une génération à N images) garde,
    elle, tous ses éléments : ce sont les sorties d'un même item.
    """
    from pathlib import Path

    from django.conf import settings

    media_url = getattr(settings, 'MEDIA_URL', '/media/') or '/media/'
    vus, sendable, oversized = set(), [], []

    def _keep(valeur):
        if len(sendable) >= _MAX_OUTPUT_FILES or not isinstance(valeur, str):
            return
        if not valeur.startswith(media_url):
            return
        rel = valeur[len(media_url):].split('?')[0]
        if not rel or rel in vus:
            return
        from wama.common.utils.media_paths import OutsideMediaRoot, resolve_under_media_root
        try:
            chemin, _ = resolve_under_media_root(rel, must_exist=False)
        except OutsideMediaRoot:
            return
        if not chemin.is_file():
            return
        if chemin.stat().st_size > _MAX_OUTPUT_BYTES:
            # ⚠⚠ ÉCARTÉ, MAIS PLUS EN SILENCE (2026-09-27, question de Fabien sur le lien de
            # téléchargement). Pour une image le plafond est théorique ; pour une VIDÉO
            # anonymisée c'est le cas NORMAL — l'utilisateur recevait « c'est terminé », sans
            # pièce jointe et sans explication. *Ce qui ne plante pas ne se signale pas.*
            vus.add(rel)
            oversized.append((chemin.name, chemin.stat().st_size / (1024 * 1024)))
            return
        vus.add(rel)
        sendable.append(rel)

    def _keep_output(value):
        if isinstance(value, (list, tuple)):
            for element in value:
                _keep(element)
        else:
            _keep(value)

    def _walk(node, depth=0):
        if depth > _MAX_OUTPUT_DEPTH or len(sendable) >= _MAX_OUTPUT_FILES:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _OUTPUT_KEYS:
                    _keep_output(value)
                else:
                    _walk(value, depth + 1)
        elif isinstance(node, (list, tuple)) and node:
            _walk(node[0], depth + 1)                 # le plus récent — cf. docstring

    for etape in (resultat or {}).get('tool_steps') or []:
        _walk(etape.get('result'))
    return sendable, oversized


def _store_attachments(user, pieces) -> list:
    """
    Dépose les pièces jointes dans l'espace de l'utilisateur et rend leurs descriptions.

    Réutilise le geste PARTAGÉ avec la vue web et l'API v1
    (`filemanager.services.enregistrer_fichier_utilisateur`) — la passerelle n'a pas son
    propre chemin d'écriture, sinon les trois surfaces divergeraient.
    """
    if not pieces:
        return []

    from django.core.files.uploadedfile import SimpleUploadedFile

    from wama.filemanager.services import enregistrer_fichier_utilisateur

    deposes = []
    for piece in pieces:
        try:
            fichier = SimpleUploadedFile(piece.name, piece.content)
            deposes.append(enregistrer_fichier_utilisateur(user, fichier))
        except Exception:
            logger.exception("[gateway] dépôt impossible : %s", piece.name)
    return deposes


# ── Fin de tâche dans le fil d'origine (ROADMAP §19.2, 2026-10-06) ───────────────────────
# Le moteur promettait « vous serez notifié dès la fin » ; rien ne partait vers un canal. La
# passerelle relève désormais les notifications de fin de tâche (`notify_job_end`, qui désigne
# l'élément) comme la cloche du web relève les siennes, et poste le résultat dans le fil d'où la
# tâche a été demandée. Rien n'est inventé pour cela :
#   • la FILE est `common.Notification` — un curseur par canal (`ChannelCursor`) en est le
#     « dernier vu », comme celui du navigateur ;
#   • l'ORIGINE est LUE dans le store de conversation : l'étape d'outil qui a créé ou lancé
#     l'élément (`tool_api.items_of_step`, contrat méta-app) — aucune table de suivi de plus ;
#   • le RÉSULTAT rejoue le geste « statut » (`get_<famille>_status` → `_produced_files`), celui
#     qui joint le fichier quand l'utilisateur demande « quel est le statut ? ».
# Une tâche lancée depuis le web n'a pas de fil d'origine : rien n'est posté (décision de Fabien,
# la cloche de WAMA la signale déjà).

#: Les notifications que la passerelle relaie : les deux issues d'un traitement.
JOB_NOTICE_KINDS = ('job_done', 'job_failed')
#: Intervalle de relève (s). Le web relève toutes les 60 s ; une conversation attend plus vite.
FOLLOW_UP_INTERVAL_S = 15
#: Bornes d'une relève : notifications traitées, tours remontés pour trouver l'origine.
_MAX_NOTICES_PER_ROUND = 50
_ORIGIN_SCAN_TURNS = 200


@dataclass
class FollowUp:
    """Une fin de tâche à poster : où (`thread`), à qui (`external_id`), quoi (`reply`), et ce qui
    s'enregistre au fil une fois posté (`notice`, l'étape d'outil RÉELLEMENT jouée)."""
    channel: str
    thread: str
    external_id: str
    reply: Reply
    conversation_id: int
    notice: str
    step: dict


def collect_job_follow_ups(channel: str) -> list:
    """Les fins de tâche à poster sur ce canal depuis la dernière relève.

    Le curseur avance AVANT l'envoi : au plus une fois — un arrêt entre la relève et l'envoi perd
    un message de fil (la cloche de WAMA le garde), il n'en double jamais. À sa création, il se
    pose sur la dernière notification existante : rien d'ancien n'est rejoué.
    """
    from django.db import transaction
    from django.db.models import Max

    from wama.common.models import Notification

    from .models import ChannelCursor

    with transaction.atomic():
        cursor = ChannelCursor.objects.select_for_update().filter(channel=channel).first()
        if cursor is None:
            latest = Notification.objects.aggregate(m=Max('pk'))['m'] or 0
            ChannelCursor.objects.create(channel=channel, last_notification_id=latest)
            return []
        notes = list(Notification.objects
                     .filter(pk__gt=cursor.last_notification_id, kind__in=JOB_NOTICE_KINDS)
                     .exclude(object_id='')
                     .select_related('recipient')
                     .order_by('pk')[:_MAX_NOTICES_PER_ROUND])
        if not notes:
            return []
        cursor.last_notification_id = notes[-1].pk
        cursor.save(update_fields=['last_notification_id', 'updated_at'])

    follow_ups = []
    for note in notes:
        try:
            follow_up = _follow_up(note, channel)
        except Exception:
            logger.exception("[gateway] fin de tâche non relayée (notification #%s)", note.pk)
            continue
        if follow_up is not None:
            follow_ups.append(follow_up)
    return follow_ups


def _follow_up(note, channel: str):
    """La fin de tâche d'UNE notification, ou None : personne reliée sur ce canal, ou tâche qui
    n'a pas été demandée depuis l'un de ses fils."""
    user = note.recipient
    external_id = linked_identity(user, channel)
    if not external_id:
        return None
    conversation = _origin_conversation(note, channel)
    if conversation is None:
        return None

    from wama.tool_api import execute_tool
    status_tool = f'get_{note.app}_status'
    result = execute_tool(status_tool, {}, user)
    jobs = (result.get('jobs') or []) if isinstance(result, dict) else []
    job = next((j for j in jobs if str(j.get('id')) == note.object_id), None)

    lines = [f"{'✅' if note.kind == 'job_done' else '⚠'} {note.title}"]
    if note.body:
        lines.append(note.body)
    reply = _reply_with_outputs('\n'.join(lines),
                                [{'result': {'jobs': [job]}}] if job else [])
    return FollowUp(channel=channel, thread=conversation.thread_key, external_id=external_id,
                    reply=reply, conversation_id=conversation.pk, notice=note.title,
                    step={'tool': status_tool, 'args': {}, 'result': result})


def _origin_conversation(note, channel: str):
    """Le fil de CE canal où l'élément de la notification a été créé ou lancé — lu dans les
    étapes d'outils persistées (`tool_api.items_of_step`), du plus récent au plus ancien.

    L'élément est désigné par sa FAMILLE (clé du `DetailRegistry` : `audio_enhancer` et `enhancer`
    sont deux modèles d'une même app) et son id ; la famille doit bien porter le modèle nommé par
    la notification — sinon deux éléments de même numéro dans deux modèles se confondraient."""
    from wama.common.models import ConversationTurn
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.tool_api import items_of_step

    entry = DetailRegistry.get(note.app)
    if entry is None or entry['model'].__name__ != note.object_type:
        return None
    try:
        wanted = (note.app, int(note.object_id))
    except (TypeError, ValueError):
        return None
    turns = (ConversationTurn.objects
             .filter(conversation__user_id=note.recipient_id, conversation__surface=channel,
                     role='assistant', created_at__lte=note.created_at)
             .exclude(tool_steps=[])
             .select_related('conversation')
             .order_by('-created_at', '-pk')[:_ORIGIN_SCAN_TURNS])
    for turn in turns:
        for step in turn.tool_steps or []:
            if not isinstance(step, dict):
                continue
            if wanted in items_of_step(str(step.get('tool') or ''), step.get('args'),
                                       step.get('result')):
                return turn.conversation
    return None


def record_follow_up(follow_up: FollowUp) -> None:
    """Enregistre au fil la fin de tâche POSTÉE — après l'envoi, par l'adaptateur.

    Un échange comme un autre (`conversation_store.record_exchange`) : la notification côté
    utilisateur, la réponse avec l'étape d'outil RÉELLEMENT jouée côté assistant. L'historique
    resservi au modèle garde ainsi un « terminé » APPUYÉ sur un outil — un « terminé » sans outil
    est précisément l'exemple qui lui faisait inventer des résultats (`WAMA_LLM.md` §2026-10-05).
    """
    from wama.common.models import Conversation
    from wama.common.services import conversation_store

    conversation = Conversation.objects.filter(pk=follow_up.conversation_id).first()
    if conversation is None:
        return
    conversation_store.record_exchange(
        conversation, f"[Notification WAMA] {follow_up.notice}",
        {'response': follow_up.reply.text, 'tool_steps': [follow_up.step],
         'model': 'notification WAMA'})
