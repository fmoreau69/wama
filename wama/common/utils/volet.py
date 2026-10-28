"""
Déclaration du VOLET DROIT par la page — `WAMA_VOLETS.md §8 n°2`.

LE PROBLÈME. `base.html` rend les trois sections (Médias, Paramètres, Actions) pour TOUTE page
qui l'étend. Mesuré le 2026-08-22 : sur 35 pages, **17 n'en déclarent aucune** et héritent donc
de **51 cadres vides** — « Médias / Sélectionnez un fichier pour l'aperçu » sur la page de
connexion, « Actions » sans une seule action sur la matrice d'accès. Le volet y est un décor.

LE PRINCIPE. Une page DÉCLARE son volet ; sans déclaration, elle garde les trois sections.
Le défaut est donc l'état d'AVANT : les 10 apps n'ont rien à écrire et ne changent pas d'un
pixel (c'est la contrainte n°1 du chantier). Seules les pages transversales déclarent, et ce
qu'elles déclarent est un RETRAIT.
⚠ Depuis le 2026-10-20 (Fabien : « on met les champs en fonction du contenu de la page, pas de
champ par défaut ») une page du COMPTE (`app_registry.register_account_page`) n'a PLUS de
défaut : sans déclaration, AUCUNE section (`context_processors.volet_defaut`). Mesuré le jour
même : quatre pages du compte (Partages, Notifications, Formats médias, Apps) héritaient encore
des trois cadres vides ; Apps en remplit deux, elle les déclare.

POURQUOI UN DICT COMPLET, ET PAS `{% if volet.medias %}` SUR UN DICT PARTIEL. Une variable
absente vaut « faux » dans un `{% if %}` Django : un dict partiel masquerait donc les sections
non citées, exactement l'inverse du défaut voulu. Deux issues : un filtre maison
(`volet|section:'medias'`) ou un dict TOUJOURS complet. On prend le second — `_filter_bar.html`
a tranché la même question dans le même sens (« en ajouter un pour ça seul serait un mécanisme
de plus à connaître »). Le context processor `volet_defaut` garantit le dict complet ; une vue
qui déclare le remplace en entier, et `volet()` le construit pour elle.

USAGE (dans la vue) ::

    from wama.common.utils.volet import volet, VOLET_AUCUN

    context['volet'] = VOLET_AUCUN                       # page sans volet du tout
    context['volet'] = volet(medias=False)               # garde Paramètres + Actions
    context['volet'] = volet(tete=True, medias=False,    # accueil : avatar seul en tête
                             parametres=False, actions=False)

⚠ `tete` n'est PAS une section : c'est le bloc libre `right_panel_top`, sans cadre ni titre.
Il faut le déclarer parce qu'un gabarit ne peut pas dire s'il est vide, et qu'un volet réduit à
ce seul bloc doit rester rendu (cas de `home.html` et de son avatar).

LES SECTIONS EN BRIQUES (2026-10-28, `WAMA_VOLETS §3-ter` étape ②) : chaque section du volet est
un panneau de la disposition commune (`WamaBrickLayout`, monté par `wama-panel-layout.js`) — on
la réordonne, on la retaille, on l'empile, on l'épingle à un bord de la zone centrale, et la
disposition se garde PAR COMPTE et par page (`layout_of`, route `common:panel_layout`). Le rendu
par défaut ne change pas : tant que le compte n'a rien disposé, le volet reste celui d'avant, et
la grille ne se monte qu'au geste « Modifier la disposition ». Une page dont le volet a sa
propre disposition (une surface) ou qui la fera brique par brique (le cam_analyzer, étape ③ :
« il déclare, il n'hérite pas ») le dit : `arrangeable=False`.

LE CENTRE AUSSI (2026-10-28, étape ④) : la card d'entrée, la progression globale, la barre de la
file et la file d'une page d'app sont des briques de la MÊME disposition — la grille du centre,
à côté de la colonne du volet, comme sur une surface. Les pièces communes qui les rendent les
marquent (`data-wama-brick`) ; une app à plusieurs domaines (onglets) en a un jeu par domaine
(`centre_slots`). Une seule disposition par page et par compte, donc une seule route.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Clés = ce que `base.html` sait rendre. `actif` est DÉRIVÉE, jamais écrite à la main.
SECTIONS = ('tete', 'medias', 'parametres', 'actions')


def volet(*, tete: bool = False, medias: bool = True,
          parametres: bool = True, actions: bool = True, arrangeable: bool = True) -> dict:
    """Déclaration de volet, toujours COMPLÈTE (cf. le pourquoi dans l'en-tête du module)."""
    d = {'tete': bool(tete), 'medias': bool(medias),
         'parametres': bool(parametres), 'actions': bool(actions)}
    # `actif` : le volet a-t-il quoi que ce soit à montrer ? Sinon `base.html` ne rend PAS
    # l'`<aside>` — et le corps récupère la largeur que le CSS lui réservait (classe
    # `wama-sans-volet`). Sans ce dernier point, retirer les cadres laisserait une bande
    # vide de 360 px : on aurait déplacé le décor au lieu de l'enlever.
    d['actif'] = any(d[k] for k in SECTIONS)
    d['arrangeable'] = bool(arrangeable)
    return d


@dataclass(frozen=True)
class PanelSlot:
    """Une section du volet comme emplacement de la disposition commune : la COLONNE du volet
    (`zone='panel'`, une colonne), son ordre (`y`) et sa hauteur PAR DÉFAUT (`h`, en rangées de la
    grille, 46 px) — le contenu défile dans la brique, l'utilisateur la retaille. `element` :
    l'identifiant que `base.html` donne à la section, jamais renommé (l'inspecteur le lit)."""
    id: str
    element: str
    y: int
    h: int
    x: int = 0
    w: int = 1
    zone: str = 'panel'
    #: Une brique du CENTRE se trouve par sa marque (`data-wama-brick="<kind>"`) et son domaine,
    #: pas par un identifiant : les pièces communes la rendent une fois par domaine.
    kind: str = ''
    domain: str = ''
    title: str = ''
    #: À la hauteur de son contenu (`wama-brick-layout.js`, `sized`) : on la déplace et on règle sa
    #: largeur, sa hauteur suit ce qu'elle montre.
    fit: bool = False

    def to_dict(self) -> dict:
        return {'id': self.id, 'element': self.element, 'x': self.x, 'y': self.y, 'w': self.w,
                'h': self.h, 'zone': self.zone, 'kind': self.kind, 'domain': self.domain,
                'title': self.title, 'fit': self.fit}


def _stacked(*sections) -> tuple:
    """Les emplacements dans l'ordre donné, chacun sous le précédent."""
    out, y = [], 0
    for slot_id, element, h in sections:
        out.append(PanelSlot(slot_id, element, y, h))
        y += h
    return tuple(out)


#: Les sections du volet, dans l'ordre de `base.html`. Une section absente de la page (non
#: déclarée, ou l'assistant désactivé) n'a pas de panneau.
PANEL_SLOTS = _stacked(
    ('assistant', 'assistant-avatar-section', 9),
    ('top', 'right-panel-top', 4),
    ('preview', 'media-section', 7),
    ('info', 'info-section', 6),
    ('settings', 'settings-section', 10),
    ('actions', 'actions-section', 4),
)


#: Les briques du CENTRE d'une page d'app (étape ④), par leur clé au registre des briques
#: (`surfaces.BRICKS`, qui porte leur nom et le gabarit qui les monte), dans l'ordre où les pages
#: les rendent le plus souvent — le module les empile dans l'ordre de LA page. Les trois premières
#: sont à la hauteur de leur contenu (`fit`) ; la file a une hauteur qu'on règle (elle s'allonge
#: sans fin). La pièce commune qui monte chacune pose la marque `data-wama-brick="<clé>"`.
CENTRE_BRICKS = (
    ('entry_card', 3, True),
    ('global_progress', 1, True),
    ('toolbar', 1, True),
    ('queue', 12, False),
)


def centre_slots(page: str) -> tuple:
    """Les briques du centre de la page `page` : un jeu par domaine quand l'app en a plusieurs
    (onglets de l'imager, de l'enhancer — `<kind>-<domaine>`), sinon un seul. Toute la largeur de
    la grille, l'une sous l'autre."""
    from wama.common.surfaces import BRICKS, GRID_COLUMNS
    from wama.common.utils.app_modes import get_domains, has_domain_tabs
    domains = get_domains(page) if page and has_domain_tabs(page) else [{}]
    out, y = [], 0
    for domain in domains:
        key = domain.get('id', '')
        label = domain.get('label') or key
        for kind, h, fit in CENTRE_BRICKS:
            title = BRICKS[kind].name
            out.append(PanelSlot(f'{kind}-{key}' if key else kind, '', y, h, x=0, w=GRID_COLUMNS,
                                 zone='grid', kind=kind, domain=key, fit=fit,
                                 title=f'{title} — {label}' if key else title))
            y += h
    return tuple(out)


@dataclass(frozen=True)
class _PanelDeclaration:
    """Ce que `surfaces.clean_layout` lit d'une page de briques : ses emplacements."""
    slots: tuple


def declaration(page: str) -> _PanelDeclaration:
    """Les emplacements de la page `page` : les sections du volet, puis les briques du centre."""
    return _PanelDeclaration(PANEL_SLOTS + centre_slots(page))

#: Le nom du réglage utilisateur (`UserAppSetting`, sous la clé de la page) qui garde la disposition.
LAYOUT_SETTING = 'panel_layout'
#: Une clé de page : un espace de noms d'URL ou un nom de vue.
PAGE_KEY = re.compile(r'^[A-Za-z_][\w-]{0,63}$')


def page_key(request) -> str:
    """La page dont on garde la disposition du volet : l'espace de noms de sa route — le plus
    proche : l'app (`cam_analyzer` sous `wama_lab`), ou `common` pour le journal et le calendrier —,
    à défaut le nom de sa vue ; '' si rien ne la nomme."""
    match = getattr(request, 'resolver_match', None)
    if match is None:
        return ''
    key = match.namespaces[-1] if match.namespaces else (match.url_name or '')
    return key if PAGE_KEY.match(key) else ''


def layout_of(user, key: str) -> dict:
    """La disposition du volet que `user` a gardée pour la page `key` (`clean_layout`), `stored` à
    vrai ; à défaut, aucune — FIGÉE : le volet d'avant, tant que rien n'a été disposé."""
    from wama.common.surfaces import clean_layout
    from wama.common.utils.user_settings import get_user_app_setting
    stored = get_user_app_setting(user, key, LAYOUT_SETTING) if key else None
    if isinstance(stored, dict):
        try:
            return dict(clean_layout(declaration(key), stored), stored=True)
        except ValueError:
            pass
    return {'slots': None, 'frozen': True, 'docked': {}, 'stacks': {}, 'stored': False}


def is_arranged(layout: dict) -> bool:
    """Le compte a-t-il disposé ce volet ? Sinon il reste celui d'avant, sans grille."""
    return not (layout.get('frozen') and not layout.get('slots')
                and not layout.get('stacks') and not layout.get('docked'))


def layout_config(request) -> dict | None:
    """Ce que `wama-panel-layout.js` lit (`base.html`) ; None sans compte ou sans page nommée."""
    from django.urls import reverse

    from wama.common.surfaces import DOCK_EDGES, GRID_COLUMNS, MAX_LAYOUT_ROWS
    user = getattr(request, 'user', None)
    key = page_key(request)
    if user is None or not user.is_authenticated or not key:
        return None
    layout = layout_of(user, key)
    return {'page': key, 'url': reverse('common:panel_layout', args=[key]),
            'key': f'wama.panel.{key}', 'layout': layout, 'arranged': is_arranged(layout),
            'slots': [s.to_dict() for s in declaration(key).slots], 'columns': GRID_COLUMNS,
            'max_rows': MAX_LAYOUT_ROWS, 'dock_edges': list(DOCK_EDGES)}


#: Défaut HISTORIQUE — les trois sections, aucun bloc de tête. C'est ce que rend une page qui
#: ne déclare rien, donc l'état d'avant le 2026-08-22 pour les 35 pages.
VOLET_DEFAUT = volet()

#: Aucun volet : ni sections, ni bloc de tête. Pour les pages où il n'a jamais rien porté.
VOLET_AUCUN = volet(medias=False, parametres=False, actions=False)
