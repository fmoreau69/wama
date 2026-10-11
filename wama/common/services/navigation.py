"""
Les PAGES qu'un utilisateur peut ouvrir — ce que l'assistant propose quand on lui demande
« emmène-moi sur… » (outil `open_page`, 2026-10-11).

RIEN N'EST DÉCLARÉ ICI. Les pages viennent des deux déclarations qui font déjà le menu
« Applications » (`accounts/context_processors.py`) : les apps du catalogue (`APP_CATALOG`,
`url_name`) et les surfaces hors catalogue (`register_surface` : médiathèque, studio, Lab…),
lues ensemble par `get_app_groups()`. Le droit est la MÊME décision que celle du menu
(`accessible_apps(user, all_gated_apps())`, clé `gate` pour une surface).

⚠ CE QUI DIFFÈRE DU MENU, et pourquoi : le menu applique en plus la PRÉFÉRENCE d'affichage (une
app masquée par l'utilisateur, `subscriptions.masques`) et `nav_hide`. Ce sont des choix
d'AFFICHAGE, qui ne retirent aucun droit (`PROFILES_PERMISSIONS §8`) : demander à l'assistant
d'ouvrir une app qu'on a masquée du menu doit marcher.

⚠ CE QUI N'Y EST PAS : les pages qui ne sont déclarées NULLE PART comme pages — gestionnaire de
fichiers, journal, calendrier, catalogues de registres. Le registre des registres porte bien une
`url_name`, mais sa `permission` garde l'ACTUALISATION (une écriture), pas la lecture de la page :
s'en servir pour décider qui peut l'ouvrir serait un contresens. Les ajouter demande de les
DÉCLARER (une décision), pas de les lister ici.
"""
from __future__ import annotations

import logging
import unicodedata

logger = logging.getLogger(__name__)


def _fold(text: str) -> str:
    """Casse et accents repliés : « mediatheque » trouve « Médiathèque »."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def navigable_pages(user) -> list:
    """Les pages que `user` a le DROIT d'ouvrir : `[{'key', 'label', 'url', 'world',
    'description'}]`, dans l'ordre du menu. Une route qui ne se résout pas est omise et DITE dans
    le journal, comme au menu (leçon « WAMA Lab disparu », 2026-07-05)."""
    from django.urls import NoReverseMatch, reverse

    from wama.accounts.permissions import accessible_apps, all_gated_apps
    from wama.common.app_registry import get_app_groups

    allowed = set(accessible_apps(user, all_gated_apps()))
    pages = []

    def _add(key, spec, gate):
        if gate not in allowed:
            return
        try:
            url = reverse(spec['url_name'])
        except (KeyError, NoReverseMatch):
            logger.warning("[navigation] page '%s' (%s) omise — URL irrésolvable",
                           key, spec.get('url_name'))
            return
        pages.append({'key': key, 'label': spec.get('label') or key, 'url': url,
                      'world': spec.get('world') or '', 'description': spec.get('description') or ''})

    for group in get_app_groups():
        for name, spec in group['apps']:
            _add(name, {**spec, 'world': group['world']}, name)
        for surface in group['links']:
            _add(surface['app'], surface, surface.get('gate') or surface['app'])
    return pages


def find_page(user, page: str):
    """La page que `page` désigne (clé ou libellé, casse et accents ignorés) parmi celles que
    `user` peut ouvrir — `(page, pages)`, `page` valant None si rien ne correspond."""
    pages = navigable_pages(user)
    wanted = _fold(page)
    for entry in pages:
        if wanted in (_fold(entry['key']), _fold(entry['label'])):
            return entry, pages
    return None, pages


def absolute_url(path: str) -> str:
    """L'adresse COMPLÈTE d'une page, pour une surface hors navigateur (un canal) — '' si
    l'instance ne déclare pas son adresse publique. Lit `settings.WAMA_PUBLIC_URL` et rien
    d'autre, comme la passerelle (`gateway.services`)."""
    from django.conf import settings
    base = (getattr(settings, 'WAMA_PUBLIC_URL', '') or '').strip().rstrip('/')
    return f'{base}{path}' if base else ''
