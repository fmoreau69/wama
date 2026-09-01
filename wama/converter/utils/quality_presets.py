"""
WAMA Converter — Quality presets

Three presets per media type (web / balanced / max), inspired by FileConverter.
`resolve_options(media_type, preset, base_options)` merges the preset defaults
UNDER any explicitly-set base options (explicit values always win).
"""

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
PRESET_LABELS = {
    'web':      'Web (léger)',
    'balanced': 'Équilibré',
    'max':      'Maximum',
}


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
