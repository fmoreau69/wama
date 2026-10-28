"""
Context processors du socle commun.

`volet_defaut` garantit que `volet` est TOUJOURS un dict complet dans les gabarits, y compris
pour les pages qui ne déclarent rien — c'est ce qui rend le défaut « les trois sections »
sûr sans obliger les 10 apps à écrire quoi que ce soit. Une page du COMPTE n'a pas ce défaut
(2026-10-20). Voir `wama/common/utils/volet.py`.
"""
from __future__ import annotations

from wama.common.utils.volet import VOLET_DEFAUT


def volet_defaut(request):
    """Déclaration de volet par DÉFAUT ; une vue qui passe `volet` la remplace (elle est
    empilée au-dessus du contexte des processors).

    Une page du COMPTE (`app_registry.register_account_page` : journal, partages, notifications,
    catalogues…) n'a PAS de défaut : elle déclare les sections qu'elle remplit, et sans
    déclaration elle n'en a aucune (Fabien, 2026-10-20 : « on met les champs en fonction du
    contenu de la page, pas de champ par défaut »). Les pages d'APP gardent les trois sections,
    que `app_modern_base.html` remplit : elles n'ont rien à écrire."""
    from functools import partial

    from wama.common.app_registry import account_page_of
    from wama.common.utils.volet import VOLET_AUCUN, layout_config
    match = getattr(request, 'resolver_match', None)
    url_name = getattr(match, 'view_name', '') if match is not None else ''
    # La disposition du volet en briques (2026-10-28) : une fonction, que le gabarit n'appelle
    # (et ne fait lire en base) que pour un volet rendu et disposable.
    return {'volet': VOLET_AUCUN if account_page_of(url_name) else VOLET_DEFAUT,
            'panel_layout': partial(layout_config, request)}


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


def theme(request):
    """Le THÈME de la page (`common/themes.py`), posé par `base.html` sur `<html>` : ses tokens
    (`wama-theme.css`) et le mode de Bootstrap en découlent. Lu sur toute page, sans compte aussi.
    `theme_choice` est le choix du compte (« Automatique » compris) ; `theme_declared`, ce que
    `wama-theme.js` lit pour résoudre « Automatique » avant le premier rendu. `theme_logos` : les
    thèmes qui ont un logo, tous posés dans la barre du haut — la feuille ne montre que celui du
    thème actif, qui peut changer sans recharger (Profil, « Automatique »). `theme_font_sheets` :
    les feuilles des polices que les chartes font servir (`themes.font_stylesheets`).
    `theme_generated_css` : le bloc GÉNÉRÉ d'un thème personnalisé choisi — ses graines, ou celles
    de la charte choisie (`themes.account_generated_css`)."""
    from wama.common import themes as declared
    from wama.common.themes import THEMES, declared_for_pages, resolve, theme_choice
    user = getattr(request, 'user', None)
    choice = theme_choice(user)
    generated = getattr(declared, 'account_generated_css', None)
    return {'theme': resolve(choice), 'theme_choice': choice,
            'theme_declared': declared_for_pages(choice),
            # `getattr` : un worker recyclé peut lire ce module neuf avec un `themes` déjà importé
            # d'avant `Theme.logo` (vécu le 2026-10-19 : toutes les pages en 500 jusqu'au rechargement)
            'theme_logos': [t for t in THEMES if getattr(t, 'logo', '')],
            'theme_font_sheets': getattr(declared, 'font_stylesheets', list)(),
            'theme_generated_css': generated(user, choice) if generated else ''}


def public_address(request):
    """L'adresse PUBLIQUE de l'instance (`settings.WAMA_PUBLIC_URL`, lue par
    `navigation.absolute_url` et rien d'autre), '' si elle n'est pas déclarée. `base.html` la
    donne à la capture caméra / micro (`common/js/wama-capture.js`), qui la cite à qui est en http
    — jusqu'au 2026-10-26 une adresse écrite en dur dans le JS, fausse sur toute autre instance."""
    from wama.common.services.navigation import absolute_url
    return {'wama_public_url': absolute_url('')}


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
