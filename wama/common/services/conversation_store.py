"""
Store de conversation — l'historique de l'assistant, côté SERVEUR.

CE QU'IL REMPLACE. Jusqu'ici l'historique vivait chez le client : `localStorage` côté web
(perdu en changeant de navigateur, invisible depuis un autre appareil) et un dictionnaire
en mémoire du process côté passerelle (perdu à chaque redémarrage, non partagé entre
process). Un même utilisateur ne pouvait donc ni reprendre une conversation ailleurs, ni
en tenir plusieurs de front. Cf. `ROADMAP.md` §19.5.

⚠ Livré le 20/08 mais adopté par la seule passerelle Discord jusqu'au 2026-09-15 : la page web
gardait son `localStorage` et l'API son historique fourni par le client (mesuré par la
cartographie de l'assistant, `WAMA_LLM.md`). Depuis, le web (surface `web`) et l'API (surface `api`,
sauf client qui fournit son `history`) passent par `conversation_turn`.

CE QUI NE CHANGE PAS — et c'est délibéré. `run_assistant_turn` continue d'accepter un
`history` explicite : le moteur reste une fonction sans état, testable sans base de
données, et les clients qui gèrent eux-mêmes leur historique (un script, un harnais) ne
sont pas cassés. Le store est une COUCHE AU-DESSUS, jamais une dépendance du moteur.

UN FIL = `(user, surface, thread_key)`. C'est la clé que la passerelle possède déjà
(`gateway/core.py::_thread_key`) : un DM Discord, un salon Matrix et un onglet de navigateur
sont trois fils distincts, sans que le moteur ait à en connaître l'existence.
"""
from __future__ import annotations

import logging

from django.db import transaction

from wama.common.models import Conversation, ConversationTurn

logger = logging.getLogger(__name__)

#: Tours renvoyés au moteur par défaut (10 échanges). Le moteur retronque de son côté ;
#: cette borne-ci évite de charger un fil entier depuis la base à chaque message.
MAX_TOURS = 20


def thread(user, surface: str = 'web', thread_key: str = '') -> Conversation:
    """Le fil de cet utilisateur pour cette surface — créé au besoin."""
    conversation, _ = Conversation.objects.get_or_create(
        user=user, surface=surface, thread_key=(thread_key or '')[:255])
    return conversation


def history(conversation, limite: int = MAX_TOURS) -> list:
    """
    Les derniers tours du fil, au format attendu par `run_assistant_turn`.

    Rend les tours dans l'ORDRE CHRONOLOGIQUE même si on n'en prend que la fin : une
    conversation servie à l'envers produit des réponses incohérentes, et le défaut est
    difficile à voir depuis l'extérieur.
    """
    if conversation is None:
        return []
    derniers = list(conversation.turns.order_by('-created_at', '-pk')[:limite])
    return [{'role': t.role, 'content': t.content} for t in reversed(derniers)]


@transaction.atomic
def record_exchange(conversation, message: str, resultat: dict) -> None:
    """
    Enregistre le tour utilisateur ET la réponse de l'assistant, en une transaction.

    Les deux ensemble, jamais séparément : un fil où la question est enregistrée mais pas
    la réponse (ou l'inverse) désaligne tout l'historique servi ensuite au modèle.

    Best-effort côté appelant : si le store est indisponible, la conversation doit
    continuer — l'assistant qui répond compte plus que la trace de sa réponse.
    """
    if conversation is None:
        return

    ConversationTurn.objects.create(
        conversation=conversation, role='user', content=message or '')
    ConversationTurn.objects.create(
        conversation=conversation, role='assistant',
        content=resultat.get('response', '') or '',
        tool_steps=resultat.get('tool_steps') or [],
        model=(resultat.get('model') or '')[:120],
    )
    conversation.titre_auto(message)
    # `updated_at` porte l'ordre d'affichage de la liste des conversations : le toucher
    # explicitement, car créer des tours ne modifie pas le fil lui-même.
    conversation.save(update_fields=['updated_at'])


def display_entries(conversation, limite: int = 60) -> list:
    """Les derniers tours du fil au format d'AFFICHAGE d'une surface : les étapes d'outils
    précèdent la réponse, comme au moment où elle a été reçue.

    [{'type': 'user'|'assistant'|'tool_steps', 'content'?, 'steps'?, 'model'?}]
    """
    if conversation is None:
        return []
    entries = []
    derniers = list(conversation.turns.order_by('-created_at', '-pk')[:limite])
    for t in reversed(derniers):
        if t.role == 'assistant' and t.tool_steps:
            entries.append({'type': 'tool_steps', 'steps': t.tool_steps})
        entry = {'type': t.role, 'content': t.content}
        if t.role == 'assistant' and t.model:
            entry['model'] = t.model
        entries.append(entry)
    return entries


def conversations_of(user, limite: int = 50) -> list:
    """Fils d'un utilisateur, le plus récemment actif d'abord (liste d'UI)."""
    return list(Conversation.objects.filter(user=user)[:limite])


def clear(user, conversation_id: int) -> bool:
    """
    Supprime UN fil — uniquement l'un des SIENS.

    Le filtre porte sur `user` autant que sur l'identifiant : sans lui, un identifiant
    deviné suffirait à effacer la conversation de quelqu'un d'autre.
    """
    n, _ = Conversation.objects.filter(pk=conversation_id, user=user).delete()
    return n > 0
