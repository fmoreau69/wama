"""Le MIROIR DE LUMINANCE — la règle qui tire le thème clair du thème sombre (chantier thèmes,
étape 4, 2026-10-18, `ROADMAP §28`).

    Y' = 0,0525 / (Y + 0,05) − 0,05

échange le noir et le blanc (Y luminance relative WCAG) en gardant la teinte et le chroma
(OKLCH). Pour deux couleurs miroirs, le rapport de contraste WCAG (Y1 + 0,05) / (Y2 + 0,05)
devient exactement son inverse : un texte lisible sur son fond en sombre l'est autant en clair, et
la hiérarchie des gris se conserve. C'est la seule bijection de [0, 1] qui le fasse.

Lu par `tests_theme` (chaque token clair est le miroir du sombre, sauf ceux que `themes.py`
déclare) et par qui ajoute un token : `mirror('#9aa3ab')` rend sa valeur claire."""
from __future__ import annotations

import math
import re

_HEX = re.compile(r'^#([0-9a-fA-F]{3,8})$')
_FUNC = re.compile(r'^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$')
_CHANNELS = re.compile(r'^(\d+),\s*(\d+),\s*(\d+)$')


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    c = max(0.0, min(1.0, c))
    return 255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)


def luminance(rgb) -> float:
    """Luminance relative WCAG d'un triplet 0-255."""
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    """Rapport de contraste WCAG de deux triplets 0-255 (1 à 21)."""
    ya, yb = luminance(a), luminance(b)
    return (max(ya, yb) + 0.05) / (min(ya, yb) + 0.05)


def mirrored_luminance(y: float) -> float:
    return 0.0525 / (y + 0.05) - 0.05


def _oklab(rgb):
    r, g, b = (_lin(x) for x in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def chroma(rgb) -> float:
    """La chroma OKLCH d'un triplet 0-255 : 0 pour un gris, ~0,3 pour un bleu saturé."""
    _L, a, b = _oklab(rgb)
    return math.hypot(a, b)


def _linear_from_oklch(L, C, h):
    a, b = C * math.cos(h), C * math.sin(h)
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def _rgb_from_oklch(L, C, h):
    """Le triplet 0-255 de (L, C, h), la chroma réduite au gamut sRGB si besoin."""
    def inside(c):
        return all(-1e-4 <= x <= 1 + 1e-4 for x in _linear_from_oklch(L, c, h))
    if not inside(C):
        lo, hi = 0.0, C
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if inside(mid) else (lo, mid)
        C = lo
    return tuple(round(_unlin(x)) for x in _linear_from_oklch(L, C, h))


def mirror_rgb(rgb):
    target = mirrored_luminance(luminance(rgb))
    if target >= 1 - 1e-9:   # le noir : le blanc exact (la recherche s'arrêterait à #fefefe)
        return (255, 255, 255)
    _L, a, b = _oklab(rgb)
    C, h = math.hypot(a, b), math.atan2(b, a)
    if C < 0.006:          # un gris reste un gris : la teinte d'une chroma nulle n'est que du bruit
        C = 0.0
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if luminance(_rgb_from_oklch(mid, C, h)) < target else (lo, mid)
    return _rgb_from_oklch((lo + hi) / 2, C, h)


def parse(value: str):
    """(forme, (r, g, b), alpha) d'une valeur de token — hexadécimale, `rgb()`/`rgba()` ou canaux
    « r, g, b » —, sinon (None, None, None)."""
    v = value.strip()
    m = _HEX.match(v)
    if m:
        digits = m.group(1)
        if len(digits) in (3, 4):
            digits = ''.join(c * 2 for c in digits)
        return 'hex', tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4)), (digits[6:8] or None)
    m = _FUNC.match(v)
    if m:
        return 'func', tuple(int(m.group(i)) for i in (1, 2, 3)), m.group(4)
    m = _CHANNELS.match(v)
    if m:
        return 'channels', tuple(int(m.group(i)) for i in (1, 2, 3)), None
    return None, None, None


def hex_of(rgb) -> str:
    """`#rrggbb` d'un triplet 0-255 (arrondi) — la seule écriture hexadécimale des thèmes (miroir,
    générateur, lecture de charte)."""
    return '#' + ''.join(f'{round(x):02x}' for x in rgb)


def rgb_of(value: str):
    """Le triplet 0-255 d'une couleur (`parse`), ou None."""
    return parse(value)[1]


def _format(kind, rgb, alpha):
    if kind == 'hex':
        return hex_of(rgb) + (alpha or '')
    if kind == 'func':
        return (f'rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})' if alpha
                else f'rgb({rgb[0]}, {rgb[1]}, {rgb[2]})')
    return f'{rgb[0]}, {rgb[1]}, {rgb[2]}'


def mirror(value: str) -> str:
    """La valeur claire d'une valeur sombre, dans la même forme (l'opacité est gardée)."""
    kind, rgb, alpha = parse(value)
    if kind is None:
        raise ValueError(f'pas une couleur : {value!r}')
    return _format(kind, mirror_rgb(rgb), alpha)
