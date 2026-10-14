"""
Les PAGES qu'un utilisateur peut ouvrir — ce que l'assistant propose quand on lui demande
« emmène-moi sur… » (outil `open_page`, 2026-10-11), et le menu du compte (2026-10-14).

RIEN N'EST DÉCLARÉ ICI. Les pages viennent de trois déclarations :
  • les apps du catalogue (`APP_CATALOG`, `url_name`) et les surfaces hors catalogue
    (`register_surface` : médiathèque, studio, Lab…), lues ensemble par `get_app_groups()` — ce
    qui fait déjà le menu « Applications » (`accounts/context_processors.py`). Le droit est la
    MÊME décision que celle du menu (`accessible_apps(user, all_gated_apps())`, clé `gate` pour
    une surface) ;
  • les pages du COMPTE (`register_account_page` : profil, journal, calendrier, catalogues…),
    qui font le menu du compte. Leur droit est celui de la requête RÉELLE
    (`permissions.can_open_page` : fermeture au visiteur, politique du chemin, décorateur de la
    vue).

⚠ CE QUI DIFFÈRE DU MENU APPLICATIONS, et pourquoi : il applique en plus la PRÉFÉRENCE
d'affichage (une app masquée par l'utilisateur, `subscriptions.masques`) et `nav_hide`. Ce sont
des choix d'AFFICHAGE, qui ne retirent aucun droit (`PROFILES_PERMISSIONS §8`) : demander à
l'assistant d'ouvrir une app qu'on a masquée du menu doit marcher.

⚠ CE QUI N'Y EST PAS : les outils SANS page (gestionnaire de fichiers, assistant), qui n'ont
rien à ouvrir, et la déconnexion, qui est un geste et pas une page.
"""
from __future__ import annotations

import logging
import unicodedata

logger = logging.getLogger(__name__)


def _fold(text: str) -> str:
    """Casse et accents repliés : « mediatheque » trouve « Médiathèque »."""
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def _reverse(key: str, url_name: str) -> str | None:
    """L'adresse d'une page déclarée, ou None — une route irrésolvable est omise et DITE dans le
    journal, comme au menu (leçon « WAMA Lab disparu », 2026-07-05)."""
    from django.urls import NoReverseMatch, reverse
    try:
        return reverse(url_name)
    except NoReverseMatch:
        logger.warning("[navigation] page '%s' (%s) omise — URL irrésolvable", key, url_name)
        return None


def account_pages_for(user, allowed_apps=None) -> list:
    """Les pages du COMPTE que `user` peut ouvrir, dans l'ordre du menu : `[{'key', 'label',
    'url', 'section', 'icon', 'tone', 'color', 'menu', 'description'}]`. `allowed_apps` : la
    lecture groupée `accessible_apps` déjà faite par l'appelant."""
    from wama.accounts.permissions import can_open_page
    from wama.common.app_registry import account_pages
    from wama.common.registries import REGISTRIES

    # Une page CATALOGUE se décrit par son registre (même route) : ce que l'assistant lit pour la
    # choisir n'est pas rédigé une seconde fois. Le premier déclaré l'emporte (Skills porte deux
    # registres, `skills` et `prompts`).
    registry_text = {}
    for registry in REGISTRIES.values():
        if registry.url_name and registry.description:
            registry_text.setdefault(registry.url_name, registry.description)

    pages = []
    for page in account_pages():
        if not page['description']:
            page['description'] = registry_text.get(page['url_name'], '')
        url = _reverse(page['key'], page['url_name']) if page['url_name'] else None
        if url is None:
            if not page['url_name']:
                logger.warning("[navigation] page '%s' omise — surface '%s' non déclarée",
                               page['key'], page['surface'])
            continue
        if not can_open_page(user, page['access'], url, allowed_apps):
            continue
        pages.append({k: page[k] for k in ('key', 'label', 'section', 'icon', 'tone', 'color',
                                            'menu', 'description')} | {'url': url})
    return pages


def account_menu(user, allowed_apps=None) -> list:
    """Le menu du COMPTE de `user` : `[{'key', 'label', 'pages': […]}]`, une entrée par section
    non vide, dans l'ordre déclaré (`app_registry.ACCOUNT_SECTIONS`)."""
    from wama.common.app_registry import ACCOUNT_SECTIONS

    sections = {key: {'key': key, 'label': spec['label'], 'pages': []}
                for key, spec in sorted(ACCOUNT_SECTIONS.items(), key=lambda kv: kv[1]['order'])}
    for page in account_pages_for(user, allowed_apps):
        if page['menu']:
            sections[page['section']]['pages'].append(page)
    return [s for s in sections.values() if s['pages']]


def navigable_pages(user) -> list:
    """Les pages que `user` a le DROIT d'ouvrir : `[{'key', 'label', 'url', 'world', 'section',
    'description', 'aliases'}]` — les apps et surfaces dans l'ordre du menu Applications, puis
    les pages du compte. Une page du compte qui renvoie à une surface déjà listée (Registres,
    Models) n'est pas répétée : son libellé de menu devient un ALIAS de la surface."""
    from wama.accounts.permissions import accessible_apps, all_gated_apps
    from wama.common.app_registry import ACCOUNT_SECTIONS, get_app_groups

    allowed = set(accessible_apps(user, all_gated_apps()))
    pages = []

    def _add(key, spec, gate):
        if gate not in allowed:
            return
        url = _reverse(key, spec.get('url_name') or '') if spec.get('url_name') else None
        if url is None:
            return
        pages.append({'key': key, 'label': spec.get('label') or key, 'url': url,
                      'world': spec.get('world') or '', 'section': 'Applications',
                      'description': spec.get('description') or '', 'aliases': []})

    for group in get_app_groups():
        for name, spec in group['apps']:
            _add(name, {**spec, 'world': group['world']}, name)
        for surface in group['links']:
            _add(surface['app'], surface, surface.get('gate') or surface['app'])

    by_url = {p['url']: p for p in pages}
    for page in account_pages_for(user, allowed):
        known = by_url.get(page['url'])
        if known is not None:
            known['aliases'].append(page['label'])
            continue
        entry = {'key': page['key'], 'label': page['label'], 'url': page['url'], 'world': '',
                 'section': ACCOUNT_SECTIONS[page['section']]['label'],
                 'description': page['description'], 'aliases': []}
        pages.append(entry)
        by_url[entry['url']] = entry
    return pages


def find_page(user, page: str):
    """La page que `page` désigne (clé, libellé ou alias, casse et accents ignorés) parmi celles
    que `user` peut ouvrir — `(page, pages)`, `page` valant None si rien ne correspond."""
    pages = navigable_pages(user)
    wanted = _fold(page)
    for entry in pages:
        names = [entry['key'], entry['label'], *entry.get('aliases', ())]
        if wanted in (_fold(n) for n in names):
            return entry, pages
    return None, pages


def absolute_url(path: str) -> str:
    """L'adresse COMPLÈTE d'une page, pour une surface hors navigateur (un canal) — '' si
    l'instance ne déclare pas son adresse publique. Lit `settings.WAMA_PUBLIC_URL` et rien
    d'autre, comme la passerelle (`gateway.services`)."""
    from django.conf import settings
    base = (getattr(settings, 'WAMA_PUBLIC_URL', '') or '').strip().rstrip('/')
    return f'{base}{path}' if base else ''
