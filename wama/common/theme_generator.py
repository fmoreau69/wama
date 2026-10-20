"""Le GÉNÉRATEUR de thème — un thème personnel tiré de quelques couleurs-graines (chantier thèmes,
étape 7, 2026-10-20, `ROADMAP §28`).

Fabien, 2026-10-19 : « Je me demande aussi pour permettre aux gens de personnaliser leur thème :
fournir une charte complète ? Cliquer sur des thèmes de couleurs ? Importer une image… » — toutes
ces voies rendent la MÊME chose : une base (le clair ou le sombre) et une couleur d'accent. Ce
module en dérive le bloc d'identité, les mêmes ~20 propriétés que le bloc d'un thème de charte
(UGE, La Suite) ; les 421 autres viennent de la base, dont le thème personnel est dans la liste de
sélecteurs (`wama-theme.css`). Personne n'édite un token à la main.

Chaque couleur lue comme TEXTE est assombrie (base claire) ou éclaircie (base sombre) jusqu'à
4,5:1 sur chaque fond de sa base et sur sa page ; la primaire de Bootstrap, fond d'un bouton
plein, jusqu'à 4,5:1 sous son texte blanc — les règles de `tests_theme.DerivedThemeTest`, qui
valent ici pour TOUTE graine (`tests_theme.GeneratedThemeTest` en balaie des centaines). Les
valeurs des fonds sont lues dans `wama-theme.css`, jamais recopiées ici."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from wama.common.theme_mirror import contrast_ratio as ratio
from wama.common.theme_mirror import parse

THEME_CSS = Path(__file__).resolve().parent / 'static' / 'common' / 'css' / 'wama-theme.css'

#: Le contraste exigé d'un texte (WCAG AA, texte courant).
TEXT_RATIO = 4.5
#: La part de la graine dans la teinte de la page.
PAGE_TINT = {'light': 0.05, 'dark': 0.06}

_HEX6 = re.compile(r'^#[0-9a-fA-F]{6}$')
#: Un nom de police tel qu'une charte l'écrit (« TT Norms Pro ») : rien qui puisse fermer la
#: déclaration CSS où il entre.
_FONT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 .\-]{0,62}$')
_WHITE, _BLACK = (255, 255, 255), (0, 0, 0)


def valid_seed(value) -> bool:
    """Une graine est une couleur `#rrggbb` (ce que rend un `<input type="color">`)."""
    return isinstance(value, str) and bool(_HEX6.match(value))


def valid_font(value) -> bool:
    """Un nom de police (lettres, chiffres, espaces, point, tiret) ; '' = aucune."""
    return value == '' or (isinstance(value, str) and bool(_FONT.match(value)))


@lru_cache(maxsize=None)
def _base_blocks(css_text: str) -> dict:
    css = re.sub(r'/\*.*?\*/', '', css_text, flags=re.S)
    blocks = {}
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        tokens = dict(re.findall(r'(--[a-z0-9-]+)\s*:\s*([^;]+);', body))
        for selector in selectors.split(','):
            m = re.fullmatch(r'\s*(?::root)?\[data-wama-theme="([a-z0-9_-]+)"\]\s*', selector)
            if m:
                blocks.setdefault(m.group(1), {}).update({k: v.strip() for k, v in tokens.items()})
    return blocks


def base_values(base: str) -> dict:
    """Les tokens du thème `base` tels que `wama-theme.css` les déclare."""
    return _base_blocks(THEME_CSS.read_text(encoding='utf-8'))[base]


def _rgb(value: str):
    return parse(value)[1]


def _hex(rgb) -> str:
    return '#' + ''.join(f'{round(x):02x}' for x in rgb)


def _mix(a, b, part_b: float):
    return tuple(x + (y - x) * part_b for x, y in zip(a, b))


def _toward(colour, target, grounds, need=TEXT_RATIO):
    """`colour`, mêlée à `target` (noir ou blanc) juste assez pour passer `need` sur chaque fond."""
    for step in range(0, 101):
        c = tuple(round(x) for x in _mix(colour, target, step / 100))
        if all(ratio(c, g) >= need for g in grounds):
            return c
    return target


def grounds(base: str, page) -> tuple:
    """Les fonds sur lesquels un texte de ce thème se lit : ceux de la base, et sa page."""
    v = base_values(base)
    if base == 'light':
        return (_WHITE, _rgb(v['--wama-surface-raised']), page)
    return (_rgb(v['--wama-surface']), _rgb(v['--wama-surface-raised']), page)


def generate(base: str, accent: str, font: str = '') -> dict:
    """Le bloc d'identité d'un thème de base `base` ('light' / 'dark') et d'accent `accent`
    (`#rrggbb`) : {propriété CSS: valeur}. `font` : la police d'une charte, NOMMÉE en tête de la
    pile — un poste qui l'a l'affiche, WAMA ne la sert pas (`themes.LICENSED_FONTS`)."""
    if base not in ('light', 'dark') or not valid_seed(accent) or not valid_font(font):
        raise ValueError(f'graine invalide : {base!r}, {accent!r}, {font!r}')
    v = base_values(base)
    seed = _rgb(accent)
    page_start = _mix(_rgb(v['--wama-page-bg-start']), seed, PAGE_TINT[base])
    page_end = _mix(_rgb(v['--wama-page-bg-end']), seed, PAGE_TINT[base])
    page = tuple(round(x) for x in page_start)
    on_fill = _rgb(v['--wama-text-on-accent'])
    read_on = grounds(base, page) + (tuple(round(x) for x in page_end),)
    # La primaire, fond d'un bouton plein sous un texte blanc — et en clair, lue aussi comme texte.
    primary = _toward(seed, _BLACK, (on_fill,) + (read_on if base == 'light' else ()))
    if base == 'light':
        text = primary
        link_soft = _toward(_mix(primary, _BLACK, 0.35), _BLACK, read_on)
        soft = tuple(round(x) for x in _mix(seed, _WHITE, 0.45))
        emphasis = _toward(_mix(primary, _BLACK, 0.6), _BLACK, read_on)
        soft_text = emphasis
        bg_subtle, border_subtle = _mix(primary, _WHITE, 0.8), _mix(primary, _WHITE, 0.6)
        accent_fill, batch = primary, soft
    else:
        text = _toward(seed, _WHITE, read_on)
        link_soft = _toward(_mix(seed, _WHITE, 0.7), _WHITE, read_on)
        soft = _toward(_mix(seed, _WHITE, 0.35), _WHITE, read_on)
        emphasis = _toward(_mix(primary, _WHITE, 0.4), _WHITE, read_on)
        soft_text = soft
        bg_subtle, border_subtle = _mix(primary, _BLACK, 0.8), _mix(primary, _BLACK, 0.6)
        accent_fill, batch = text, _mix(primary, text, 0.5)
    link = _toward(_mix(text, _WHITE if base == 'dark' else _BLACK, 0.1), _WHITE if base == 'dark' else _BLACK,
                   read_on)

    def channels(rgb):
        return ', '.join(str(round(x)) for x in rgb)
    named = {'--bs-body-font-family': f'"{font}", var(--bs-font-sans-serif)'} if font else {}
    return {
        '--wama-page-bg-start': _hex(page_start), '--wama-page-bg-end': _hex(page_end),
        '--wama-accent': _hex(accent_fill), '--wama-accent-rgb': channels(accent_fill),
        '--wama-accent-text': _hex(text),
        '--wama-link': _hex(link), '--wama-link-rgb': channels(link), '--wama-link-soft': _hex(link_soft),
        '--wama-indigo': _hex(text), '--wama-indigo-rgb': channels(text),
        '--wama-scrollbar-thumb': f'rgba({channels(accent_fill)}, .5)',
        '--wama-scrollbar-thumb-hover': f'rgba({channels(accent_fill)}, .8)',
        '--wama-accent-soft': _hex(soft), '--wama-accent-soft-text': _hex(soft_text),
        '--wama-accent-batch': _hex(batch),
        '--bs-primary': _hex(primary), '--bs-primary-rgb': channels(primary),
        '--bs-primary-text-emphasis': _hex(emphasis),
        '--bs-primary-bg-subtle': _hex(bg_subtle), '--bs-primary-border-subtle': _hex(border_subtle),
        **named,
    }


def css_block(key: str, base: str, accent: str, font: str = '') -> str:
    """La règle CSS du thème `key` : ce que `base.html` pose dans `#wama-theme-generated`."""
    body = ''.join(f'  {name}: {value};\n' for name, value in generate(base, accent, font).items())
    return f'[data-wama-theme="{key}"] {{\n{body}}}\n'
