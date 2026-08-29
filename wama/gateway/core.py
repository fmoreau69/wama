"""
Passerelle de canaux — le cœur, celui qui ne connaît AUCUN protocole.

RÈGLE FONDATRICE DE CE MODULE : un adaptateur traduit un protocole, il ne décide jamais
rien. Tout ce qui est une décision — qui est l'utilisateur, a-t-il le droit, que répondre,
que faire d'une pièce jointe — vit ICI, une seule fois, et vaut pour Discord comme pour
Tchap/Matrix comme pour le canal suivant. C'est la seule manière d'ajouter un canal sans
rouvrir la question de sécurité à chaque fois : un adaptateur qui n'a pas de logique n'a
pas de faille propre.

Un adaptateur n'a donc que trois obligations :
  1. traduire un événement du protocole en `MessageEntrant` ;
  2. appeler `traiter_message()` ;
  3. rendre la `Reponse` dans les termes de son protocole (texte, fichiers).

⚠ `traiter_message()` est SYNCHRONE et BLOQUANTE (un tour d'assistant peut prendre des
dizaines de secondes). Les bibliothèques de bots sont asynchrones : un adaptateur doit
l'appeler dans un thread (`asyncio.to_thread`), jamais directement dans la boucle
d'événements — sinon le bot cesse de répondre à tout le monde pendant qu'un utilisateur
attend son résultat. Cela règle aussi l'accès ORM, interdit en contexte async.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .services import ErreurAppariement, compte_pour, delier, demander_liaison

logger = logging.getLogger(__name__)

#: Longueur au-delà de laquelle une réponse est coupée par l'adaptateur. Chaque protocole a
#: sa propre limite (Discord : 2000 caractères) — la valeur réelle est celle de l'adaptateur,
#: celle-ci n'est qu'un repli.
LIMITE_TEXTE = 2000

# L'historique de conversation vivait ici, dans un dict EN MÉMOIRE DU PROCESS
# (`_HISTORIQUES`) : perdu à chaque redémarrage de la passerelle, non partagé entre process,
# et invisible depuis le web. Il est REMPLACÉ (2026-08-21) par le store commun
# `common/services/conversation_store.py` — le même que la surface web, de sorte qu'un fil
# ouvert dans Discord et la liste des conversations du navigateur parlent enfin de la même
# chose. Le geste de la passerelle se résume désormais à nommer son fil (`_cle_fil`).


@dataclass
class PieceJointe:
    """Une pièce jointe entrante, déjà téléchargée par l'adaptateur."""
    nom: str
    contenu: bytes


@dataclass
class MessageEntrant:
    """Ce qu'un adaptateur doit produire, quel que soit le protocole."""
    channel: str                    # 'discord' | 'matrix'
    external_id: str                # identifiant STABLE de la personne (jamais son pseudo)
    texte: str
    external_label: str = ''        # pseudo affiché, confort de lecture seulement
    fil: str = ''                   # identifiant du fil/salon → une conversation par fil
    pieces_jointes: list = field(default_factory=list)


@dataclass
class Reponse:
    """Ce que l'adaptateur doit rendre dans son protocole."""
    texte: str
    #: Chemins relatifs à MEDIA_ROOT que l'adaptateur doit joindre. Vide la plupart du temps.
    fichiers: list = field(default_factory=list)
    #: True quand la réponse ne doit PAS être publiée dans un salon (code d'appariement…).
    prive: bool = False


AIDE = (
    "**WAMA** — ce que je sais faire ici :\n"
    "• `!lier` — relier ce compte de discussion à votre compte WAMA (obligatoire)\n"
    "• `!delier` — supprimer la liaison\n"
    "• `!aide` — ce message\n"
    "Sinon, écrivez simplement ce que vous voulez faire : « transcris le fichier que je "
    "viens d'envoyer », « où en est ma transcription ? ». Les pièces jointes sont déposées "
    "dans votre espace WAMA."
)


def _cle_fil(msg: MessageEntrant) -> str:
    """
    Clé du fil DANS sa surface — un salon/DM = une conversation.

    À défaut de fil déclaré par l'adaptateur, l'identité de la personne fait office de fil :
    un canal qui n'a pas la notion de salon reste ainsi une conversation par interlocuteur,
    jamais un fil global où tout le monde se mélangerait.
    """
    return msg.fil or msg.external_id


def traiter_message(msg: MessageEntrant) -> Reponse:
    """
    Traite UN message entrant et rend ce que l'adaptateur doit publier.

    Ne lève pas : toute erreur devient une réponse lisible. Un bot qui plante sur un message
    cesse de servir tous les autres utilisateurs du salon.
    """
    try:
        return _traiter(msg)
    except ErreurAppariement as e:
        return Reponse(texte=f"⛔ {e}", prive=True)
    except Exception:
        logger.exception("[gateway] échec de traitement (%s:%s)", msg.channel, msg.external_id)
        return Reponse(texte="⚠ Une erreur interne est survenue. Elle a été journalisée.")


def _traiter(msg: MessageEntrant) -> Reponse:
    texte = (msg.texte or '').strip()
    commande = texte.split()[0].lower() if texte else ''

    if commande in ('!aide', '!help'):
        return Reponse(texte=AIDE)

    user = compte_pour(msg.channel, msg.external_id)

    # ── Appariement ──────────────────────────────────────────────────────────────
    if commande == '!lier':
        if user is not None:
            return Reponse(texte=f"✅ Ce compte est déjà relié à **{user.username}**.", prive=True)
        lien = demander_liaison(msg.channel, msg.external_id, msg.external_label)
        return Reponse(prive=True, texte=(
            f"🔑 Code d'appariement : **{lien.code}**\n"
            "Connectez-vous à WAMA, puis saisissez ce code dans votre profil.\n"
            "_Il expire dans 15 minutes. Ne le communiquez à personne : c'est la session "
            "WAMA qui saisit le code qui obtiendra l'accès à ce compte de discussion._"
        ))

    if commande == '!delier':
        if user is None:
            return Reponse(texte="Ce compte n'est relié à aucun compte WAMA.", prive=True)
        delier(user, msg.channel, msg.external_id)
        return Reponse(texte="🔓 Liaison supprimée.", prive=True)

    # ── Garde : un inconnu n'obtient RIEN ────────────────────────────────────────
    # ⚠ Ne JAMAIS retomber sur un traitement « en anonyme » : c'est exactement le piège
    # mesuré sur `/filemanager/api/upload/`, dont le `get_user()` basculait silencieusement
    # sur l'utilisateur anonyme partagé. Ici, l'absence de compte est une FIN de parcours.
    if user is None:
        return Reponse(prive=True, texte=(
            "👋 Je ne sais pas encore qui vous êtes dans WAMA.\n"
            "Envoyez `!lier` pour obtenir un code d'appariement."
        ))

    # ── Pièces jointes → espace WAMA de l'utilisateur ────────────────────────────
    deposes = _deposer_pieces_jointes(user, msg.pieces_jointes)

    if not texte and not deposes:
        return Reponse(texte=AIDE)

    # ── Le tour d'assistant : MÊME moteur ET MÊME store que la page web ─────────
    from wama.common.services.assistant_engine import tour_de_conversation

    invite = texte
    if deposes:
        liste = ', '.join(f"`{d['path']}`" for d in deposes)
        entete = f"[Fichiers déposés dans mon espace WAMA : {liste}]"
        invite = f"{entete}\n{texte}" if texte else f"{entete}\nQue puis-je en faire ?"

    # L'historique est résolu et persisté SERVEUR (plus de dict en mémoire du process) :
    # la passerelle n'a qu'à nommer son fil.
    resultat = tour_de_conversation(user, invite, surface=msg.channel,
                                    thread_key=_cle_fil(msg))

    if 'error' in resultat:
        return Reponse(texte=f"⚠ {resultat['error']}")

    # Les fichiers PRODUITS pendant le tour repartent avec la réponse : sans ça, le code
    # d'envoi des adaptateurs est mort et l'utilisateur reçoit un lien `/media/…` protégé
    # par session, inutilisable hors WAMA (défaut mesuré 2026-08-29, WAMA_LLM §Vérification).
    return Reponse(texte=resultat.get('response') or '(réponse vide)',
                   fichiers=_produced_files(resultat))


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


def _deposer_pieces_jointes(user, pieces) -> list:
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
            fichier = SimpleUploadedFile(piece.nom, piece.contenu)
            deposes.append(enregistrer_fichier_utilisateur(user, fichier))
        except Exception:
            logger.exception("[gateway] dépôt impossible : %s", piece.nom)
    return deposes
