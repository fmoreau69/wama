"""
Context processors du socle commun.

`volet_defaut` garantit que `volet` est TOUJOURS un dict complet dans les gabarits, y compris
pour les pages qui ne déclarent rien — c'est ce qui rend le défaut « les trois sections »
sûr sans obliger les 10 apps à écrire quoi que ce soit. Voir `wama/common/utils/volet.py`.
"""
from __future__ import annotations

from wama.common.utils.volet import VOLET_DEFAUT


def volet_defaut(request):
    """Déclaration de volet par DÉFAUT ; une vue qui passe `volet` la remplace (elle est
    empilée au-dessus du contexte des processors)."""
    return {'volet': VOLET_DEFAUT}


def unread_notifications(request):
    """Nombre de notifications NON LUES du compte connecté — le badge de l'en-tête
    (`WAMA_COLLABORATION.md §2.3`). Une requête indexée (`recipient`, `read_at`) ; fail-safe."""
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'unread_notifications': 0}
    try:
        from wama.common.models import Notification
        return {'unread_notifications': Notification.objects.filter(
            recipient=user, read_at__isnull=True).count()}
    except Exception:
        return {'unread_notifications': 0}


#: Ce que voit un visiteur sans compte : pas d'avatar (la vocalisation exige un compte).
_AVATAR_ABSENT = {'available': False, 'enabled': False, 'collapsed': False, 'voice': False,
                  'compact_chat': False}


def assistant_avatar(request):
    """Préférence d'AVATAR de l'assistant, lue sur TOUTE page.

    Le conteneur de l'avatar vit dans `base.html` (`common/_assistant_avatar.html`) depuis le
    2026-09-22 — il faut donc que chaque page sache s'il doit s'afficher, et replié ou non.
    Source = les réglages DURABLES de l'assistant (`assistant_settings`, brique `user_settings`),
    les MÊMES que le modèle et le curseur : une préférence de plus, pas un mécanisme de plus.
    `available` = un compte connecté (l'anonyme n'a ni voix ni avatar) ; `enabled` est VRAI par
    défaut (décision de Fabien, 22/09) ; `collapsed` est le repli choisi.
    Fail-safe : une panne du store rend l'avatar absent, jamais une page en erreur.
    """
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'assistant_avatar': _AVATAR_ABSENT}
    try:
        from wama.common.services.assistant_engine import assistant_settings
        prefs = assistant_settings(user)
        # Le mini-chat du volet (22/09) est rendu PARTOUT sauf sur l'accueil, qui porte le chat
        # complet : deux chats sur la même page se disputeraient le même fil.
        match = getattr(request, 'resolver_match', None)
        on_home = bool(match and getattr(match, 'url_name', '') == 'home' and not match.namespace)
        return {'assistant_avatar': {'available': True,
                                     'enabled': bool(prefs.get('avatar', True)),
                                     'collapsed': bool(prefs.get('avatar_collapsed', False)),
                                     'voice': bool(prefs.get('voice', True)),
                                     'compact_chat': not on_home}}
    except Exception:
        return {'assistant_avatar': _AVATAR_ABSENT}
