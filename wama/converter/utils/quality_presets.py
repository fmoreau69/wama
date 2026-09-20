"""
WAMA Converter — Quality presets

Three presets per media type (web / balanced / max), inspired by FileConverter.
`resolve_options(media_type, preset, base_options)` merges the preset defaults
UNDER any explicitly-set base options (explicit values always win).
"""

import re

# Preset → per-media defaults. Keys match the option keys read by the backends.
_PRESETS = {
    'image': {
        'web':      {'quality': 80},
        'balanced': {'quality': 90},
        'max':      {'quality': 98, 'optimize': True},
    },
    'video': {
        # video_quality = CRF (lower = better) ; preset = x264 speed/efficiency
        'web':      {'video_quality': 23, 'preset': 'medium'},
        'balanced': {'video_quality': 20, 'preset': 'slow'},
        'max':      {'video_quality': 16, 'preset': 'slow'},
    },
    'audio': {
        'web':      {'audio_bitrate': '160k'},
        'balanced': {'audio_bitrate': '224k'},
        'max':      {'audio_bitrate': '320k'},
    },
    # documents have no quality knob
    'document': {
        'web': {}, 'balanced': {}, 'max': {},
    },
}

DEFAULT_PRESET = 'balanced'
PRESET_CHOICES = ('web', 'balanced', 'max')
#: Libellés = le trio CANONIQUE du curseur commun (Rapide / Équilibré / Qualité — arbitrage
#: Fabien 02/09), la nuance locale en sous-libellé. Les CLÉS `web/balanced/max` restent : ce sont
#: des données (filemanager, tool_api, `quality_preset` en base — frontière des DONNÉES).
PRESET_LABELS = {
    'web':      'Rapide (web)',
    'balanced': 'Équilibré',
    'max':      'Qualité',
}

# ── Le CURSEUR commun décliné en réglages d'encodage (chantier C, 2026-09-20) ────────────
# ROUTE §F4b ③ : le converter n'a pas de modèle à tirer ; sa déclinaison du curseur 0-100 est
# « valeur → réglages d'encodage par format ». Les trois presets sont des POSITIONS sur l'échelle
# commune (`QUALITY_PRESETS` du sélecteur : Rapide 15 / Équilibré 50 / Qualité 85) ; entre deux
# positions, les valeurs numériques s'INTERPOLENT (« chaque cran déplace réellement », Fabien
# 02/09) ; une valeur non numérique (preset x264, `optimize`) prend celle de la position la plus
# proche. Aux positions exactes, on retrouve la table ci-dessus à l'unité.
_CANON_TO_PRESET = {'fast': 'web', 'balanced': 'balanced', 'quality': 'max'}


def preset_positions() -> dict:
    """{clé de preset: position 0-100} — lues chez le sélecteur commun, jamais recopiées."""
    from wama.model_manager.services.model_selector import QUALITY_PRESETS
    return {_CANON_TO_PRESET[key]: pos for key, _label, pos in QUALITY_PRESETS
            if key in _CANON_TO_PRESET}


def intent_for_preset(preset: str):
    """Position du curseur qui correspond à un preset, None si la clé est inconnue."""
    return preset_positions().get((preset or '').strip().lower())


def preset_for_intent(intent) -> str:
    """Le preset le plus PROCHE d'une valeur de curseur — la TRACE (`quality_preset`) d'un geste
    au curseur, pour les lecteurs qui ne connaissent que les trois clés."""
    from wama.common.utils.auto_model import read_quality_intent
    v = read_quality_intent(intent)
    positions = preset_positions()
    return min(positions, key=lambda k: (abs(positions[k] - v), -positions[k]))


def _blend(a, b, t: float):
    """Valeur entre `a` (t=0) et `b` (t=1) : nombres interpolés, `'160k'` par son nombre,
    le reste (chaîne x264, booléen) = la position la plus proche."""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a if t < 0.5 else b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        val = a + (b - a) * t
        return int(round(val)) if isinstance(a, int) and isinstance(b, int) else val
    if isinstance(a, str) and isinstance(b, str):
        ma, mb = re.match(r'^(\d+)(\D*)$', a), re.match(r'^(\d+)(\D*)$', b)
        if ma and mb and ma.group(2) == mb.group(2):
            return f"{int(round(int(ma.group(1)) + (int(mb.group(1)) - int(ma.group(1))) * t))}{ma.group(2)}"
    return a if t < 0.5 else b


def values_for_intent(media_type: str, intent) -> dict:
    """Réglages d'encodage pour une valeur de curseur 0-100 — `{}` pour une nature sans bouton
    de qualité (documents). Aux positions des presets, exactement `preset_values`."""
    from wama.common.utils.auto_model import read_quality_intent
    v = read_quality_intent(intent)
    table = _PRESETS.get(media_type, {})
    if not table or not any(table.values()):
        return {}
    positions = preset_positions()
    order = sorted(positions, key=positions.get)
    below = [k for k in order if positions[k] <= v]
    above = [k for k in order if positions[k] >= v]
    lo = below[-1] if below else order[0]
    hi = above[0] if above else order[-1]
    span = positions[hi] - positions[lo]
    t = 0.0 if span == 0 else min(1.0, max(0.0, (v - positions[lo]) / span))
    if not below:
        t = 0.0                       # sous la 1re position : la plus légère
    if not above:
        t = 1.0                       # au-delà de la dernière : la plus riche
    out = {}
    for key in sorted(set(table.get(lo, {})) | set(table.get(hi, {}))):
        out[key] = _blend(table.get(lo, {}).get(key), table.get(hi, {}).get(key), t)
    return out


def preset_values(media_type: str, preset: str) -> dict:
    """Valeurs du préréglage choisi, ou {} — l'app est la SEULE à connaître sa table.

    C'est tout ce que le converter doit fournir à la cascade commune
    (`param_schema.effective_settings` : défauts du schéma ← preset ← réglages posés).
    Auparavant, `resolve_options` faisait lui-même la fusion — mais sans les défauts du
    schéma, qui vivaient une 3ᵉ fois en dur dans les backends (ROADMAP §23.2bis).
    """
    return dict(_PRESETS.get(media_type, {}).get((preset or '').lower(), {}))


def resolve_options(media_type: str, preset: str, base_options: dict | None = None) -> dict:
    """~~Fusion preset ← options~~ — CONSERVÉE pour `inline_convert` et `tool_api`, qui
    convertissent SANS élément de file (donc sans schéma d'item à cascader).

    ⚠ Ne pas l'utiliser pour un job de la file : la cascade complète est
    `param_schema.effective_settings` (elle ajoute les défauts du schéma SOUS le preset).
    """
    base_options = dict(base_options or {})
    merged = preset_values(media_type, preset)
    merged.update(base_options)  # explicit values override preset defaults
    return merged
