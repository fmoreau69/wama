"""
WAMA Synthesizer — Voice References Utilities
==============================================
Gestion automatique des voix de référence :
  - Scan du dossier voice_references/ (découverte dynamique)
  - Résolution preset_id → chemin WAV absolu (legacy + nouveau format)

Structure de dossiers attendue :
  media/synthesizer/voice_references/
    default.wav                 ← fallback universel
    french/
      adult/
        male_adult_1_fr.wav     ← Homme adulte 1 (FR)
        male_adult_2_fr.wav
        female_adult_1_fr.wav
        female_adult_2_fr.wav
      elderly/
        male_elderly_fr.wav
        female_elderly_fr.wav
      child/
        male_child_fr.wav
        female_child_fr.wav
    english/
      adult/ ...
      elderly/ ...
      child/ ...

Convention de nommage des fichiers :
  {gender}_{age}[_{n}]_{lang_code}.wav
  gender : male | female
  age    : child | adult | elderly
  n      : numéro optionnel pour plusieurs voix du même profil (1, 2, ...)
  lang   : fr | en | es | de | it | ...

IDs de preset :
  - Nouveau format : chemin relatif sans extension, ex. 'french/adult/male_adult_1_fr'
  - Héritage       : 'default', 'male_1', 'male_2', 'female_1', 'female_2'
"""

import re
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dossier racine des voix de référence
# ---------------------------------------------------------------------------

def get_voice_refs_dir() -> Path:
    """Retourne le dossier racine des voix de référence."""
    from django.conf import settings
    return Path(settings.MEDIA_ROOT) / 'synthesizer' / 'voice_references'


# ---------------------------------------------------------------------------
# Tables de conversion
# ---------------------------------------------------------------------------

_LANG_DIR_TO_CODE: Dict[str, str] = {
    'french': 'fr', 'english': 'en', 'spanish': 'es',
    'german': 'de', 'italian': 'it', 'portuguese': 'pt',
    'japanese': 'ja', 'chinese': 'zh', 'korean': 'ko',
    'dutch': 'nl', 'polish': 'pl', 'russian': 'ru',
}

_LANG_CODE_TO_LABEL: Dict[str, str] = {
    'fr': 'Français', 'en': 'English', 'es': 'Español',
    'de': 'Deutsch', 'it': 'Italiano', 'pt': 'Português',
    'ja': '日本語', 'zh': '中文', 'ko': '한국어',
    'nl': 'Nederlands', 'pl': 'Polski', 'ru': 'Русский',
}

_AGE_TO_LABEL: Dict[str, str] = {
    'child': 'Enfant', 'adult': 'Adulte', 'elderly': 'Senior',
}

# Sort key for age (child < adult < elderly)
_AGE_ORDER: Dict[str, int] = {'child': 0, 'adult': 1, 'elderly': 2}

_GENDER_TO_LABEL: Dict[str, str] = {
    'male': 'Homme', 'female': 'Femme',
}

# Pattern: {gender}_{age}[_{variant}]_{lang}.wav
_FILE_PATTERN = re.compile(
    r'^(male|female)_(child|adult|elderly)(?:_(\d+))?_([a-z]{2,5})\.wav$',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Voix héritage (backward compat pour anciens enregistrements DB)
# ---------------------------------------------------------------------------

# Fichiers plats dans voice_references/ (ou default_voices/) pour les anciens IDs
_LEGACY_IDS = {'default', 'male_1', 'male_2', 'female_1', 'female_2'}


# ---------------------------------------------------------------------------
# Scan du dossier
# ---------------------------------------------------------------------------

def scan_voice_refs() -> List[Dict]:
    """
    Parcourt voice_references/ et retourne des groupes pour le dropdown.

    Retourne une liste de dicts :
      [
        {
          'group': 'Français — Adulte',
          'voices': [
            {'id': 'french/adult/male_adult_1_fr', 'label': 'Homme 1'},
            ...
          ]
        },
        ...
      ]

    Seuls les groupes non vides sont inclus.
    Les groupes sont triés : Français en premier, puis English, puis autres.
    """
    refs_dir = get_voice_refs_dir()
    if not refs_dir.exists():
        return []

    groups: Dict[str, Dict] = {}

    for lang_dir in sorted(refs_dir.iterdir()):
        if not lang_dir.is_dir():
            continue

        lang_key = lang_dir.name.lower()
        lang_code = _LANG_DIR_TO_CODE.get(lang_key, lang_key[:2])
        lang_label = _LANG_CODE_TO_LABEL.get(lang_code, lang_dir.name.capitalize())

        for age_dir in sorted(lang_dir.iterdir(), key=lambda d: _AGE_ORDER.get(d.name.lower(), 9)):
            if not age_dir.is_dir():
                continue

            age_key = age_dir.name.lower()
            age_label = _AGE_TO_LABEL.get(age_key, age_dir.name.capitalize())

            group_key = f"{lang_label} — {age_label}"
            voices = []

            for wav in sorted(age_dir.glob('*.wav')):
                m = _FILE_PATTERN.match(wav.name)
                if not m:
                    logger.debug(f"[voice_utils] Skipped (bad name): {wav.name}")
                    continue

                gender, _, variant, _ = m.groups()
                gender_label = _GENDER_TO_LABEL.get(gender.lower(), gender.capitalize())
                label = gender_label + (f" {variant}" if variant else "")
                rel = wav.relative_to(refs_dir)
                voice_id = str(rel).replace('\\', '/').removesuffix('.wav')
                voices.append({'id': voice_id, 'label': label})

            if voices:
                groups[group_key] = {
                    'group': group_key,
                    'voices': voices,
                    '_sort': (
                        0 if 'Français' in lang_label else 1 if 'English' in lang_label else 2,
                        _AGE_ORDER.get(age_key, 9),
                    ),
                }

    return [v for _, v in sorted(groups.items(), key=lambda x: x[1]['_sort'])]


# ---------------------------------------------------------------------------
# Résolution preset → chemin absolu
# ---------------------------------------------------------------------------

def resolve_voice_preset(preset_value: str) -> Optional[str]:
    """
    Résout un ID de preset en chemin absolu vers un fichier WAV.

    Gère :
    - Nouveau format  : 'french/adult/male_adult_1_fr'
    - Héritage plat   : 'default', 'male_1', 'female_2', etc.
    - Fallback final  : voice_references/default.wav ou default_voices/default.wav
    """
    if not preset_value or preset_value in ('custom', 'bark_v2_en_0'):
        return None
    if preset_value.startswith('bark_v2_') or preset_value.startswith('cv_'):
        return None

    refs_dir = get_voice_refs_dir()

    # Nouveau format : contient un '/'
    if '/' in preset_value:
        path = refs_dir / (preset_value + '.wav')
        if path.exists():
            return str(path)
        logger.warning(f"[voice_utils] Voice ref not found: {path}")
        return None

    # Héritage : fichiers plats dans voice_references/
    if preset_value in _LEGACY_IDS:
        path = refs_dir / (preset_value + '.wav')
        if path.exists():
            return str(path)

    # Fallback : ancien dossier default_voices/
    from django.conf import settings
    legacy_dir = Path(settings.MEDIA_ROOT) / 'synthesizer' / 'default_voices'
    path = legacy_dir / (preset_value + '.wav')
    if path.exists():
        return str(path)

    # Fallback final : default.wav
    for fallback in (refs_dir / 'default.wav', legacy_dir / 'default.wav'):
        if fallback.exists():
            return str(fallback)

    return None


# ---------------------------------------------------------------------------
# Catalogue de téléchargement automatique
# ---------------------------------------------------------------------------

_LJ_BASE   = "https://github.com/idiap/coqui-ai-TTS/raw/main/tests/data/ljspeech/wavs"
_XTTS_BASE = "https://huggingface.co/coqui/XTTS-v2/resolve/main/samples"

# Clé  = chemin relatif SANS .wav dans voice_references/
# Valeur = liste de (url, description) essayées dans l'ordre ; la première qui
#          réussit est conservée. LJSpeech sert de fallback fiable pour l'anglais.
#
# Note sur les genres :
#   - LJSpeech (LJ001-*.wav) = Linda Johnson, femme adulte anglophone (certifié)
#   - XTTS-v2 *_sample.wav   = voix de démonstration multilingues (adultes)
#     Le genre exact peut varier selon la langue ; remplacer par de vraies
#     voix étiqueté es si la précision est importante.
VOICE_DOWNLOAD_CATALOG: Dict[str, List[tuple]] = {
    # ── Fallback racine ───────────────────────────────────────────────────
    'default': [
        (f"{_LJ_BASE}/LJ001-0001.wav", "LJSpeech EN female (default)"),
    ],

    # ── Anglais — Adulte ──────────────────────────────────────────────────
    'english/adult/female_adult_1_en': [
        (f"{_LJ_BASE}/LJ001-0001.wav", "LJSpeech EN female clip 1"),
    ],
    'english/adult/female_adult_2_en': [
        (f"{_LJ_BASE}/LJ001-0010.wav", "LJSpeech EN female clip 2"),
    ],
    'english/adult/male_adult_1_en': [
        (f"{_XTTS_BASE}/en_sample.wav",      "XTTS-v2 EN reference sample"),
        (f"{_LJ_BASE}/LJ001-0015.wav",       "LJSpeech EN fallback"),
    ],
    'english/adult/male_adult_2_en': [
        (f"{_XTTS_BASE}/en_male_sample.wav", "XTTS-v2 EN male sample"),
        (f"{_LJ_BASE}/LJ001-0020.wav",       "LJSpeech EN fallback"),
    ],

    # ── Français — Adulte ─────────────────────────────────────────────────
    'french/adult/female_adult_1_fr': [
        (f"{_XTTS_BASE}/fr_sample.wav",        "XTTS-v2 FR reference sample"),
    ],
    'french/adult/female_adult_2_fr': [
        (f"{_XTTS_BASE}/fr_female_sample.wav", "XTTS-v2 FR female sample"),
        (f"{_XTTS_BASE}/fr_sample.wav",        "XTTS-v2 FR fallback"),
    ],
    'french/adult/male_adult_1_fr': [
        (f"{_XTTS_BASE}/fr_male_sample.wav",   "XTTS-v2 FR male sample"),
        (f"{_XTTS_BASE}/fr_sample.wav",        "XTTS-v2 FR fallback"),
    ],

    # ── Espagnol — Adulte ─────────────────────────────────────────────────
    'spanish/adult/female_adult_1_es': [
        (f"{_XTTS_BASE}/es_sample.wav", "XTTS-v2 ES reference sample"),
    ],

    # ── Allemand — Adulte ─────────────────────────────────────────────────
    'german/adult/female_adult_1_de': [
        (f"{_XTTS_BASE}/de_sample.wav", "XTTS-v2 DE reference sample"),
    ],

    # ── Italien — Adulte ──────────────────────────────────────────────────
    'italian/adult/female_adult_1_it': [
        (f"{_XTTS_BASE}/it_sample.wav", "XTTS-v2 IT reference sample"),
    ],

    # ── Portugais — Adulte ────────────────────────────────────────────────
    'portuguese/adult/female_adult_1_pt': [
        (f"{_XTTS_BASE}/pt_sample.wav", "XTTS-v2 PT reference sample"),
    ],
}


# ---------------------------------------------------------------------------
# Catalogue datasets HuggingFace (VoxPopuli)
# ---------------------------------------------------------------------------
# Priorité : VoxPopuli (Facebook, sans auth, locuteurs diversifiés) >
#            URLs directes du VOICE_DOWNLOAD_CATALOG.
#
# Note : Mozilla Common Voice a été retiré de HuggingFace en octobre 2025
# et migré vers datacollective.mozillafoundation.org — non intégré ici.

# Mapping : rel_path → vp_lang_code pour VoxPopuli (Facebook, sans auth)
# Common Voice a été retiré de HuggingFace en octobre 2025 (migré vers
# datacollective.mozillafoundation.org) — VoxPopuli est désormais la source
# principale pour les voix avec locuteurs diversifiés.
_VOICE_DATASETS_CATALOG: Dict[str, str] = {
    # ── Anglais ───────────────────────────────────────────────────────────
    'english/adult/female_adult_1_en': 'en',
    'english/adult/female_adult_2_en': 'en',
    'english/adult/male_adult_1_en':   'en',
    'english/adult/male_adult_2_en':   'en',
    'english/elderly/female_elderly_en': 'en',
    'english/elderly/male_elderly_en':   'en',
    'english/child/female_child_en':     'en',
    'english/child/male_child_en':       'en',

    # ── Français ─────────────────────────────────────────────────────────
    'french/adult/female_adult_1_fr': 'fr',
    'french/adult/female_adult_2_fr': 'fr',
    'french/adult/male_adult_1_fr':   'fr',
    'french/adult/male_adult_2_fr':   'fr',
    'french/elderly/female_elderly_fr': 'fr',
    'french/elderly/male_elderly_fr':   'fr',
    'french/child/female_child_fr':     'fr',
    'french/child/male_child_fr':       'fr',

    # ── Espagnol ──────────────────────────────────────────────────────────
    'spanish/adult/female_adult_1_es': 'es',
    'spanish/adult/male_adult_1_es':   'es',

    # ── Allemand ──────────────────────────────────────────────────────────
    'german/adult/female_adult_1_de': 'de',
    'german/adult/male_adult_1_de':   'de',

    # ── Italien ───────────────────────────────────────────────────────────
    'italian/adult/female_adult_1_it': 'it',
    'italian/adult/male_adult_1_it':   'it',
}

# Speakers déjà utilisés par session (évite de prendre le même locuteur
# pour deux slots différents du même catalogue).
_used_vp_speakers: Dict[str, set] = {}   # {lang: {speaker_id, ...}}

_VP_MIN_S, _VP_MAX_S = 5.0, 15.0    # durée acceptable pour la référence vocale
_VP_MAX_ITER = 10_000                # limite de sécurité pour l'itération streaming


def _save_audio_array(arr, sr: int, target: Path) -> bool:  # noqa: ANN001
    """Écrit un tableau numpy audio en WAV. Retourne True si succès."""
    try:
        import soundfile as sf
        sf.write(str(target), arr, sr)
    except ImportError:
        try:
            import numpy as np
            from scipy.io import wavfile
            arr_int16 = (arr * 32767).astype(np.int16)
            wavfile.write(str(target), sr, arr_int16)
        except Exception as exc:
            logger.warning(f"[voice_utils] Impossible d'écrire le WAV (soundfile/scipy requis) : {exc}")
            return False
    except Exception as exc:
        logger.warning(f"[voice_utils] Erreur écriture WAV : {exc}")
        return False

    ok = target.exists() and target.stat().st_size > 1024
    if not ok:
        target.unlink(missing_ok=True)
    return ok



def _try_voxpopuli(target: Path, vp_lang: str) -> bool:
    """
    Télécharge un clip depuis VoxPopuli (Facebook/Meta).
    Aucune authentification requise. Pas de métadonnées genre/âge.
    Utilisé en fallback quand Common Voice est inaccessible.

    Retourne True si un clip a été enregistré avec succès.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        return False

    # Langues supportées par VoxPopuli
    _VP_LANGS = {'en', 'fr', 'de', 'es', 'it', 'pt', 'pl', 'nl',
                 'fi', 'hu', 'ro', 'sk', 'sl', 'et', 'hr', 'lt', 'lv', 'cs', 'bg', 'da'}
    if vp_lang not in _VP_LANGS:
        return False

    # Patch de compatibilité transformers 4.57+ (PreTrainedTokenizerBase déplacé)
    try:
        import transformers as _tr
        if not hasattr(_tr, 'PreTrainedTokenizerBase'):
            _tr.PreTrainedTokenizerBase = _tr.tokenization_utils_base.PreTrainedTokenizerBase
    except Exception:
        pass

    used = _used_vp_speakers.setdefault(vp_lang, set())

    try:
        logger.info(f"[voice_utils] VoxPopuli streaming : lang={vp_lang} …")
        ds = load_dataset(
            "facebook/voxpopuli", vp_lang,
            split="train",
            streaming=True,
        )
    except Exception as exc:
        logger.warning(f"[voice_utils] Impossible d'ouvrir VoxPopuli ({vp_lang}) : {exc}")
        return False

    try:
        for i, item in enumerate(ds):
            if i >= _VP_MAX_ITER:
                break

            speaker = item.get('speaker_id', str(i))
            if speaker in used:
                continue

            arr      = item['audio']['array']
            sr       = item['audio']['sampling_rate']
            duration = len(arr) / sr
            if not (_VP_MIN_S <= duration <= _VP_MAX_S):
                continue

            if _save_audio_array(arr, sr, target):
                used.add(speaker)
                logger.info(f"[voice_utils] VoxPopuli OK : {target.name} "
                            f"({duration:.1f}s, locuteur {speaker})")
                return True

    except Exception as exc:
        logger.warning(f"[voice_utils] Erreur streaming VoxPopuli : {exc}")

    return False


def _try_url_download(target: Path, sources: List[tuple]) -> bool:
    """Télécharge depuis une liste d'URLs directes. Retourne True si succès."""
    import urllib.request

    for url, description in sources:
        try:
            logger.info(f"[voice_utils] URL fallback : {description} …")
            urllib.request.urlretrieve(url, str(target))
            if target.exists() and target.stat().st_size > 1024:
                logger.info(f"[voice_utils] URL OK : {target.name} "
                            f"({target.stat().st_size // 1024} Ko)")
                return True
            target.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(f"[voice_utils] Échec URL {url} : {exc}")
            target.unlink(missing_ok=True)

    return False


def needs_voice_download() -> bool:
    """Retourne True si au moins un fichier des catalogues est absent."""
    refs_dir = get_voice_refs_dir()
    all_keys = set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG)
    return any(not (refs_dir / (rel + '.wav')).exists() for rel in all_keys)


def download_missing_voice_refs(force: bool = False) -> Dict[str, str]:
    """
    Télécharge les fichiers de voix de référence manquants.

    Stratégie pour chaque fichier (dans l'ordre) :
      1. VoxPopuli (Facebook, sans auth) — locuteurs diversifiés, pip install datasets soundfile
      2. URLs directes (XTTS-v2 HuggingFace, LJSpeech GitHub) — fallback fiable

    Args:
        force: re-télécharge même si le fichier existe déjà.

    Returns:
        dict {rel_path: 'downloaded'|'skipped'|'failed'}
    """
    refs_dir = get_voice_refs_dir()
    results: Dict[str, str] = {}

    # Union des deux catalogues ; _VOICE_DATASETS_CATALOG est prioritaire
    all_keys = set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG)

    for rel_path in sorted(all_keys):
        target = refs_dir / (rel_path + '.wav')

        if target.exists() and not force:
            results[rel_path] = 'skipped'
            continue

        target.parent.mkdir(parents=True, exist_ok=True)

        downloaded = False

        # ── 1. VoxPopuli ──────────────────────────────────────────────────
        if not downloaded and rel_path in _VOICE_DATASETS_CATALOG:
            vp_lang = _VOICE_DATASETS_CATALOG[rel_path]
            if vp_lang:
                downloaded = _try_voxpopuli(target, vp_lang)

        # ── 2. URLs directes ──────────────────────────────────────────────
        if not downloaded and rel_path in VOICE_DOWNLOAD_CATALOG:
            downloaded = _try_url_download(target, VOICE_DOWNLOAD_CATALOG[rel_path])

        results[rel_path] = 'downloaded' if downloaded else 'failed'
        if not downloaded:
            logger.error(f"[voice_utils] Toutes les sources ont échoué : {rel_path}")

    n_ok   = sum(1 for s in results.values() if s == 'downloaded')
    n_skip = sum(1 for s in results.values() if s == 'skipped')
    n_fail = sum(1 for s in results.values() if s == 'failed')
    logger.info(f"[voice_utils] Terminé : {n_ok} téléchargées, "
                f"{n_skip} déjà présentes, {n_fail} échec(s)")
    return results


def get_voice_label(preset_value: str) -> str:
    """
    Retourne un libellé lisible pour un ID de preset.
    Utilisé par get_voice_preset_display() dans les modèles.
    """
    if not preset_value:
        return ''

    # Nouveau format : 'french/adult/male_adult_1_fr'
    if '/' in preset_value:
        parts = preset_value.split('/')
        if len(parts) >= 3:
            lang_key, age_key, fname = parts[0], parts[1], parts[-1]
            lang_code = _LANG_DIR_TO_CODE.get(lang_key, lang_key[:2])
            lang_label = _LANG_CODE_TO_LABEL.get(lang_code, lang_key.capitalize())
            age_label = _AGE_TO_LABEL.get(age_key, age_key.capitalize())

            m = _FILE_PATTERN.match(fname + '.wav')
            if m:
                gender, _, variant, _ = m.groups()
                gender_label = _GENDER_TO_LABEL.get(gender.lower(), gender.capitalize())
                voice_label = gender_label + (f" {variant}" if variant else "")
                return f"{lang_label} — {age_label} — {voice_label}"
        return preset_value.replace('/', ' › ')

    return preset_value
