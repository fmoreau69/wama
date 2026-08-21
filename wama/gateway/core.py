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

#: Historique de conversation EN MÉMOIRE, par (canal, identifiant de fil).
#: ⚠ VOLATILE ET PROVISOIRE — la persistance serveur est différée (décision Fabien
#: 2026-08-20, en attente de la jonction avec la brique mémoire/RAG). Conséquences assumées
#: tant qu'elle n'existe pas : l'historique est perdu au redémarrage de la passerelle, et il
#: ne serait pas partagé entre deux process. C'est le « store du bot » annoncé dans
#: `ROADMAP.md` §19.0 — à REMPLACER par un vrai modèle `Conversation`, pas à étoffer.
_HISTORIQUES: dict[tuple[str, str], list] = {}

#: Tours conservés par fil (10 échanges). Le moteur retronque de son côté ; cette borne-ci
#: existe pour que la mémoire du process ne croisse pas indéfiniment.
MAX_TOURS = 20

#: Longueur au-delà de laquelle une réponse est coupée par l'adaptateur. Chaque protocole a
#: sa propre limite (Discord : 2000 caractères) — la valeur réelle est celle de l'adaptateur,
#: celle-ci n'est qu'un repli.
LIMITE_TEXTE = 2000


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


def _cle_fil(msg: MessageEntrant) -> tuple[str, str]:
    """Un fil = une conversation. À défaut de fil déclaré, l'identité fait office de fil."""
    return (msg.channel, msg.fil or msg.external_id)


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

    # ── Le tour d'assistant : MÊME moteur que la page web ───────────────────────
    from wama.common.services.assistant_engine import run_assistant_turn

    cle = _cle_fil(msg)
    historique = _HISTORIQUES.get(cle, [])

    invite = texte
    if deposes:
        liste = ', '.join(f"`{d['path']}`" for d in deposes)
        entete = f"[Fichiers déposés dans mon espace WAMA : {liste}]"
        invite = f"{entete}\n{texte}" if texte else f"{entete}\nQue puis-je en faire ?"

    resultat = run_assistant_turn(user, invite, history=historique)

    if 'error' in resultat:
        return Reponse(texte=f"⚠ {resultat['error']}")

    reponse = resultat.get('response') or '(réponse vide)'
    _HISTORIQUES[cle] = (historique + [
        {'role': 'user', 'content': invite},
        {'role': 'assistant', 'content': reponse},
    ])[-MAX_TOURS:]

    return Reponse(texte=reponse)


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
