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


def resolve_options(media_type: str, preset: str, base_options: dict | None = None) -> dict:
    """Return a new options dict = preset defaults overlaid by explicit base_options.

    Explicit options always win over preset defaults. Unknown preset/media_type
    yields base_options unchanged.
    """
    base_options = dict(base_options or {})
    preset = (preset or '').lower()
    defaults = _PRESETS.get(media_type, {}).get(preset, {})
    merged = dict(defaults)
    merged.update(base_options)  # explicit values override preset defaults
    return merged
