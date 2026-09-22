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


#: Ce que voit un visiteur sans compte : pas d'avatar (la vocalisation exige un compte).
_AVATAR_ABSENT = {'available': False, 'enabled': False, 'collapsed': False}


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
        return {'assistant_avatar': {'available': True,
                                     'enabled': bool(prefs.get('avatar', True)),
                                     'collapsed': bool(prefs.get('avatar_collapsed', False))}}
    except Exception:
        return {'assistant_avatar': _AVATAR_ABSENT}
