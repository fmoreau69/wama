"""
Les PAGES qu'un utilisateur peut ouvrir — ce que l'assistant propose quand on lui demande
« emmène-moi sur… » (outil `open_page`, 2026-10-11), et le menu du compte (2026-10-14).

RIEN N'EST DÉCLARÉ ICI. Les pages viennent de quatre déclarations :
  • les apps du catalogue (`APP_CATALOG`, `url_name`) et les surfaces hors catalogue
    (`register_surface` : médiathèque, studio, Lab…), lues ensemble par `get_app_groups()` — ce
    qui fait déjà le menu « Applications » (`accounts/context_processors.py`). Le droit est la
    MÊME décision que celle du menu (`accessible_apps(user, all_gated_apps())`, clé `gate` pour
    une surface) ;
  • les pages du COMPTE (`register_account_page` : profil, journal, calendrier, catalogues…),
    qui font le menu du compte. Leur droit est celui de la requête RÉELLE
    (`permissions.can_open_page` : fermeture au visiteur, politique du chemin, décorateur de la
    vue) ;
  • les SCÈNES 3D (`register_scene`, 2026-10-30), avec la même décision (`scene_pages`).

⚠ CE QUI DIFFÈRE DU MENU APPLICATIONS, et pourquoi : il applique en plus la PRÉFÉRENCE
d'affichage (une app masquée par l'utilisateur, `subscriptions.masques`) et `nav_hide`. Ce sont
des choix d'AFFICHAGE, qui ne retirent aucun droit (`PROFILES_PERMISSIONS §8`) : demander à
l'assistant d'ouvrir une app qu'on a masquée du menu doit marcher.

⚠ CE QUI N'Y EST PAS : les outils SANS page (gestionnaire de fichiers, assistant), qui n'ont
rien à ouvrir, et la déconnexion, qui est un geste et pas une page.
"""
from __future__ import annotations

import logging

from wama.common.utils.text_fold import fold

logger = logging.getLogger(__name__)


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
    """Le menu du COMPTE de `user` : `[{'key', 'label', 'icon', 'submenu', 'pages': […]}]`, une
    entrée par section non vide, dans l'ordre déclaré (`app_registry.ACCOUNT_SECTIONS`) ; `submenu`
    dit si la section se replie en sous-menu."""
    from wama.common.app_registry import ACCOUNT_SECTIONS

    sections = {key: {'key': key, 'label': spec['label'], 'icon': spec.get('icon', ''),
                      'submenu': bool(spec.get('submenu')), 'pages': []}
                for key, spec in sorted(ACCOUNT_SECTIONS.items(), key=lambda kv: kv[1]['order'])}
    for page in account_pages_for(user, allowed_apps):
        if page['menu']:
            sections[page['section']]['pages'].append(page)
    return [s for s in sections.values() if s['pages']]


#: Le réglage qui retient, par compte et par app, le domaine de la dernière visite.
PAGE_DOMAIN_SETTING = 'domain'
#: Le paramètre d'adresse qui nomme le domaine d'une page : `/anonymizer/?domain=document`.
PAGE_DOMAIN_PARAM = 'domain'


def remember_page_domain(user, app: str, domain: str) -> bool:
    """Retient `domain` comme celui de `user` pour `app` — s'il est DÉCLARÉ par l'app. Rend False
    sinon (app sans ce domaine, visiteur sans compte) : rien n'est écrit."""
    from wama.common.utils import app_modes
    from wama.common.utils.user_settings import save_user_app_settings
    if not getattr(user, 'is_authenticated', False):
        return False
    if domain not in [d.get('id') for d in app_modes.get_domains(app)]:
        return False
    save_user_app_settings(user, app, {PAGE_DOMAIN_SETTING: domain})
    return True


def page_domain(request, app: str):
    """Le DOMAINE de la page d'app que sert `request` (`MODES_QUEUE_UX §2ter`, décision de Fabien
    du 2026-11-12 : le domaine se choisit AU-DESSUS de la page, le titre est le sélecteur).

    None pour une app d'un seul domaine : sa page n'a rien à choisir. Sinon
    `{'app', 'current', 'label', 'icon', 'description', 'domains': [{'id', 'label', 'icon',
    'description', 'url', 'current'}]}` — `description` : ce que le domaine fait, tel qu'il le déclare.
    Le domaine est celui que l'ADRESSE nomme (`?domain=…` — une adresse par domaine : favori,
    partage, bouton Retour), sinon celui que le compte a retenu, sinon le premier déclaré. Une
    adresse qui en nomme un le retient pour le compte ; un domaine inconnu est ignoré."""
    from wama.common.utils import app_modes
    from wama.common.utils.user_settings import get_user_app_setting

    domains = app_modes.get_domains(app) if app else []
    if len(domains) < 2:
        return None
    ids = [d.get('id') for d in domains]
    user = getattr(request, 'user', None)
    known = bool(getattr(user, 'is_authenticated', False))
    retained = get_user_app_setting(user, app, PAGE_DOMAIN_SETTING) if known else None
    asked = request.GET.get(PAGE_DOMAIN_PARAM)
    if asked in ids:
        current = asked
        if known and retained != asked:
            remember_page_domain(user, app, asked)
    else:
        current = retained if retained in ids else ids[0]
    chosen = next(d for d in domains if d.get('id') == current)
    return {'app': app, 'current': current, 'label': chosen.get('label') or current,
            'icon': chosen.get('icon') or '', 'description': chosen.get('description') or '',
            'domains': [{'id': d.get('id'), 'label': d.get('label') or d.get('id'),
                         'icon': d.get('icon') or '', 'current': d.get('id') == current,
                         'description': d.get('description') or '',
                         'url': f"{request.path}?{PAGE_DOMAIN_PARAM}={d.get('id')}"}
                        for d in domains]}


def navigable_pages(user) -> list:
    """Les pages que `user` a le DROIT d'ouvrir : `[{'key', 'label', 'url', 'world',
    'description', 'aliases'}]` — les apps et surfaces dans l'ordre du menu Applications, puis
    les pages du compte. Une page du compte qui renvoie à une surface déjà listée (Registres,
    Models) n'est pas répétée : son libellé de menu devient un ALIAS de la surface."""
    from wama.accounts.permissions import accessible_apps, all_gated_apps
    from wama.common.app_registry import get_app_groups

    allowed = set(accessible_apps(user, all_gated_apps()))
    pages = []

    def _add(key, spec, gate):
        if gate not in allowed:
            return
        url = _reverse(key, spec.get('url_name') or '') if spec.get('url_name') else None
        if url is None:
            return
        pages.append({'key': key, 'label': spec.get('label') or key, 'url': url,
                      'world': spec.get('world') or '',
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
                 'description': page['description'], 'aliases': []}
        pages.append(entry)
        by_url[entry['url']] = entry
    for entry in scene_pages(user, allowed):
        known = by_url.get(entry['url'])
        if known is not None:
            known['scene'] = True
            known['aliases'].append(entry['label'])
            continue
        pages.append(entry)
        by_url[entry['url']] = entry
    return pages


def scene_pages(user, allowed_apps=None) -> list:
    """Les SCÈNES 3D que `user` peut ouvrir (`common/scenes.py`, 2026-10-30 — demande de Fabien :
    « activer le mode main en 3D » depuis l'assistant, qui n'atteignait aucune scène). Chacune par
    sa déclaration — titre, description, garde — et le droit de la requête RÉELLE
    (`can_open_page` : le chemin `common/scenes` relève de la politique `registries`, puis la
    garde que la scène déclare). `scene: True` : c'est sur elles que les mains s'allument."""
    from django.urls import NoReverseMatch

    from wama.accounts.permissions import can_open_page
    from wama.common.scenes import SCENES, page_url

    pages = []
    for scene in SCENES.values():
        try:
            url = page_url(scene)
        except NoReverseMatch:
            logger.warning("[navigation] scène '%s' omise — URL irrésolvable", scene.key)
            continue
        access = 'admin' if scene.permission == 'admin' else 'account'
        if not can_open_page(user, access, url, allowed_apps):
            continue
        pages.append({'key': f'scene:{scene.key}', 'label': scene.page_title, 'url': url,
                      'world': '', 'description': scene.description, 'scene': True,
                      'aliases': [f'{scene.key} 3D', scene.kicker]})
    return pages


def find_page(user, page: str):
    """La page que `page` désigne (clé, libellé ou alias, casse et accents ignorés) parmi celles
    que `user` peut ouvrir — `(page, pages)`, `page` valant None si rien ne correspond."""
    pages = navigable_pages(user)
    wanted = _bare(fold(page))
    for entry in pages:
        names = [entry['key'], entry['label'], *entry.get('aliases', ())]
        if wanted in (_bare(fold(n)) for n in names):
            return entry, pages
    return None, pages


#: Les possessifs d'un libellé PERSONNEL du menu du compte (« Mon profil », « Mes partages ») :
#: une convention d'affichage — « profil » et « mon profil » désignent la même page (2026-11-12).
_POSSESSIVES = ('mon ', 'ma ', 'mes ')


def _bare(name: str) -> str:
    """`name` (déjà plié) sans son possessif de tête."""
    return next((name[len(p):] for p in _POSSESSIVES if name.startswith(p)), name)


def absolute_url(path: str) -> str:
    """L'adresse COMPLÈTE d'une page, pour une surface hors navigateur (un canal) — '' si
    l'instance ne déclare pas son adresse publique. Lit `settings.WAMA_PUBLIC_URL` et rien
    d'autre, comme la passerelle (`gateway.services`)."""
    from django.conf import settings
    base = (getattr(settings, 'WAMA_PUBLIC_URL', '') or '').strip().rstrip('/')
    return f'{base}{path}' if base else ''
