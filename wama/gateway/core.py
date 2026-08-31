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

from .services import PairingError, account_for, pairing_url, unlink, request_link

logger = logging.getLogger(__name__)

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
    return Reply(text=resultat.get('response') or '(réponse vide)',
                   files=_produced_files(resultat))


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


def _produced_files(resultat) -> list:
    """Chemins MEDIA_ROOT-relatifs des sorties produites pendant le tour (lus des tool_steps).

    Seules les URLs `/media/…` résolues SOUS MEDIA_ROOT sont retenues — un résultat d'outil
    est une donnée, pas une autorisation de lire le disque. Bornés en nombre et en taille.
    """
    from pathlib import Path

    from django.conf import settings

    media_root = Path(settings.MEDIA_ROOT).resolve()
    media_url = getattr(settings, 'MEDIA_URL', '/media/') or '/media/'
    vus, fichiers = set(), []

    def _keep(valeur):
        if len(fichiers) >= _MAX_OUTPUT_FILES or not isinstance(valeur, str):
            return
        if not valeur.startswith(media_url):
            return
        rel = valeur[len(media_url):].split('?')[0]
        if not rel or rel in vus:
            return
        chemin = (media_root / rel).resolve()
        if not str(chemin).startswith(str(media_root)) or not chemin.is_file():
            return
        if chemin.stat().st_size > _MAX_OUTPUT_BYTES:
            return
        vus.add(rel)
        fichiers.append(rel)

    for etape in (resultat or {}).get('tool_steps') or []:
        contenu = etape.get('result')
        if not isinstance(contenu, dict):
            continue
        for cle in _OUTPUT_KEYS:
            valeur = contenu.get(cle)
            if isinstance(valeur, (list, tuple)):
                for element in valeur:
                    _keep(element)
            else:
                _keep(valeur)
    return fichiers


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
