"""
WAMA Common TTS Constants
=========================
Source unique des constantes TTS partagées entre :
  - wama.avatarizer  (AvatarJob)
  - wama.synthesizer (VoiceSynthesis)
  - tts_service.py   (service FastAPI)

Pour ajouter un modèle, une langue ou un preset, modifiez uniquement ce fichier.
"""

# ---------------------------------------------------------------------------
# Modèles TTS
# ---------------------------------------------------------------------------

TTS_MODEL_CHOICES = [
    ('xtts_v2',       'XTTS v2 (Multilingue, Clonage vocal)'),
    ('bark',          'Bark (Naturel, Expressif, Effets sonores)'),
    ('vits',          'VITS (Rapide, Bonne qualité)'),
    ('tacotron2',     'Tacotron2 (Classique, Stable)'),
    ('speedy_speech', 'SpeedySpeech (Très rapide)'),
    ('higgs_audio',   'Higgs Audio v2 (Multilocuteur, Clonage vocal, 24 Go VRAM)'),
]

# ---------------------------------------------------------------------------
# Langues
# ---------------------------------------------------------------------------

LANGUAGE_CHOICES = [
    ('fr',    'Français'),
    ('en',    'English'),
    ('es',    'Español'),
    ('de',    'Deutsch'),
    ('it',    'Italiano'),
    ('pt',    'Português'),
    ('pl',    'Polski'),
    ('tr',    'Türkçe'),
    ('ru',    'Русский'),
    ('nl',    'Nederlands'),
    ('cs',    'Čeština'),
    ('ar',    'العربية'),
    ('zh-cn', '中文'),
    ('ja',    '日本語'),
    ('ko',    '한국어'),
]

# ---------------------------------------------------------------------------
# Presets de voix
# ---------------------------------------------------------------------------

VOICE_PRESET_CHOICES = [
    ('default',        'Voix par défaut'),
    ('male_1',         'Voix masculine 1'),
    ('male_2',         'Voix masculine 2'),
    ('female_1',       'Voix féminine 1'),
    ('female_2',       'Voix féminine 2'),
    ('custom',         'Voix personnalisée (clonage)'),
    # Bark — presets par langue
    ('bark_v2_en_0',   'Bark EN Speaker 0'),
    ('bark_v2_en_1',   'Bark EN Speaker 1'),
    ('bark_v2_en_2',   'Bark EN Speaker 2'),
    ('bark_v2_en_3',   'Bark EN Speaker 3'),
    ('bark_v2_en_4',   'Bark EN Speaker 4'),
    ('bark_v2_en_5',   'Bark EN Speaker 5'),
    ('bark_v2_fr_0',   'Bark FR Speaker 0'),
    ('bark_v2_fr_1',   'Bark FR Speaker 1'),
    ('bark_v2_es_0',   'Bark ES Speaker 0'),
    ('bark_v2_de_0',   'Bark DE Speaker 0'),
]

# ---------------------------------------------------------------------------
# Coqui TTS — mapping modèle → chemin HuggingFace (utilisé par tts_service.py)
# ---------------------------------------------------------------------------

COQUI_MODEL_MAPPING = {
    "xtts_v2":       "tts_models/multilingual/multi-dataset/xtts_v2",
    "vits":          "tts_models/en/vctk/vits",
    "tacotron2":     "tts_models/en/ljspeech/tacotron2-DDC",
    "speedy_speech": "tts_models/en/ljspeech/speedy-speech",
}

# ---------------------------------------------------------------------------
# Bark — speaker par défaut par langue (utilisé par tts_service.py)
# ---------------------------------------------------------------------------

BARK_LANG_DEFAULTS = {
    "en":    "v2/en_speaker_0",
    "fr":    "v2/fr_speaker_0",
    "es":    "v2/es_speaker_0",
    "de":    "v2/de_speaker_0",
    "it":    "v2/it_speaker_0",
    "pt":    "v2/pt_speaker_0",
    "pl":    "v2/pl_speaker_0",
    "tr":    "v2/tr_speaker_0",
    "ru":    "v2/ru_speaker_0",
    "nl":    "v2/nl_speaker_0",
    "cs":    "v2/cs_speaker_0",
    "zh-cn": "v2/zh_speaker_0",
    "ja":    "v2/ja_speaker_0",
    "ko":    "v2/ko_speaker_0",
}

# ---------------------------------------------------------------------------
# Higgs Audio v2 — noms de langues en anglais (utilisés dans le system prompt)
# ---------------------------------------------------------------------------

HIGGS_LANGUAGE_NAMES = {
    "fr": "French",    "en": "English",    "de": "German",   "es": "Spanish",
    "it": "Italian",   "pt": "Portuguese", "nl": "Dutch",    "pl": "Polish",
    "ru": "Russian",   "zh": "Chinese",    "ja": "Japanese", "ko": "Korean",
    "ar": "Arabic",    "tr": "Turkish",    "sv": "Swedish",  "da": "Danish",
    "fi": "Finnish",   "nb": "Norwegian",  "cs": "Czech",    "hu": "Hungarian",
}

# ---------------------------------------------------------------------------
# XTTS v2 / Coqui — mapping preset → (nom fichier local, URL téléchargement)
# ---------------------------------------------------------------------------

_LJ_BASE = "https://github.com/idiap/coqui-ai-TTS/raw/main/tests/data/ljspeech/wavs"

PRESET_DOWNLOAD_MAPPING = {
    "default":  ("default.wav",  f"{_LJ_BASE}/LJ001-0001.wav"),
    "male_1":   ("male_1.wav",   f"{_LJ_BASE}/LJ001-0015.wav"),
    "male_2":   ("male_2.wav",   f"{_LJ_BASE}/LJ001-0020.wav"),
    "female_1": ("female_1.wav", f"{_LJ_BASE}/LJ001-0010.wav"),
    "female_2": ("female_2.wav", f"{_LJ_BASE}/LJ001-0025.wav"),
}
