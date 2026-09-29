"""
Langue PARLÉE d'un audio — pour un moteur qui l'EXIGE avant de transcrire.

POURQUOI (2026-09-28). Le transcriber ne connaît jamais la langue d'un élément avant de le
transcrire : aucun réglage ne la demande, le worker ne la transmet pas, et les moteurs qu'il avait
jusque-là la détectaient seuls (Whisper, Qwen3-ASR, Parakeet). Canary 1B v2, lui, EXIGE sa langue
source — et c'est aussi un traducteur : lui donner la mauvaise ne produit pas d'erreur, il TRADUIT.
Mesuré au premier passage : un extrait français, faute de langue, a reçu la langue du site
(`LANGUAGE_CODE = 'en-us'`) et est ressorti EN ANGLAIS. *Un repli qui devine une langue est une
réponse fausse.*

COMMENT. faster-whisper — le moteur par défaut du transcriber, déjà installé — détecte la langue sur
les 30 premières secondes ; son modèle `tiny` (75 Mo) est déjà rangé dans le dossier de famille de
Whisper. Sur CPU : aucun détenteur de VRAM de plus, rien que le gouverneur devrait arbitrer.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
#: Fenêtre d'écoute : celle de Whisper, suffisante pour une langue.
WINDOW_SECONDS = 30

_detector = None


def _model():
    global _detector
    if _detector is None:
        from django.conf import settings
        from faster_whisper import WhisperModel
        root = str(settings.MODEL_PATHS['speech']['whisper'])
        _detector = WhisperModel('tiny', device='cpu', compute_type='int8', download_root=root)
    return _detector


def detect_spoken_language(audio_16k, supported: Optional[Iterable[str]] = None) -> Tuple[str, float]:
    """(code ISO 639-1, probabilité) de la langue parlée dans `audio_16k` (mono float32, 16 kHz).

    `supported` : les langues du moteur appelant. La langue retenue est la PLUS PROBABLE, pas la
    plus probable parmi celles-là — si elle n'en fait pas partie, `ValueError` le dit : proposer
    au moteur la « moins mauvaise » de ses langues lui ferait traduire au lieu de transcrire.
    """
    language, probability, _ = _model().detect_language(audio=audio_16k[:SAMPLE_RATE * WINDOW_SECONDS])
    logger.info('[spoken_language] %s (p=%.2f)', language, probability)
    if supported is not None and language not in set(supported):
        raise ValueError(f"langue parlée détectée « {language} » (p={probability:.2f}), "
                         "que ce moteur ne transcrit pas")
    return language, float(probability)


# ── Plusieurs langues dans un même audio (2026-09-29) ──────────────────────────────────────
# Question de Fabien : « si les locuteurs changent de langue au cours d'un enregistrement, les
# modèles gèrent-ils l'appariement de la langue au texte ? » — Whisper la décidait UNE fois (30
# premières secondes) pour tout le fichier ; la card n'en gardait qu'UNE, celle du 1er morceau.

#: Probabilité à partir de laquelle une fenêtre compte comme « entendue dans cette langue ».
#: En dessous, la fenêtre est muette ou ambiguë (bruit, rires, parole superposée) : elle ne vote pas.
CONFIDENT_PROBABILITY = 0.7
PROBE_WINDOWS = 8


def probe_languages(path, duration_s: float, windows: int = PROBE_WINDOWS) -> list:
    """[(langue, probabilité)] de fenêtres de 30 s RÉPARTIES sur tout l'audio (pas seulement le
    début : une réunion peut s'ouvrir sur une autre langue que celle qu'elle parle). Modèle `tiny`
    sur CPU — aucune VRAM, quelques secondes."""
    from wama.common.utils.audio_decode import decode_window
    duration_s = float(duration_s or 0)
    count = max(1, min(windows, int(duration_s // WINDOW_SECONDS) or 1))
    heard = []
    for i in range(count):
        start = max(0.0, (i + 0.5) * duration_s / count - WINDOW_SECONDS / 2) if duration_s else 0.0
        audio, _ = decode_window(path, target_sr=SAMPLE_RATE, start_s=start,
                                 duration_s=WINDOW_SECONDS)
        if audio is None or not len(audio):
            continue
        language, probability, _ = _model().detect_language(audio=audio)
        heard.append((language, float(probability)))
    logger.info('[spoken_language] sonde : %s', heard)
    return heard


def languages_heard(probe: list, min_probability: float = CONFIDENT_PROBABILITY) -> list:
    """Les langues que la sonde a entendues avec assurance, la plus fréquente d'abord."""
    from collections import Counter
    votes = Counter(lang for lang, p in probe if p >= min_probability)
    return [lang for lang, _ in votes.most_common()]


def language_shares(segments) -> dict:
    """{langue: secondes de parole} — segments objets (`TranscriptionSegment`) ou dicts."""
    shares = {}
    for s in segments or []:
        get = s.get if isinstance(s, dict) else (lambda k, s=s: getattr(s, k, None))
        lang = get('language')
        start, end = get('start_time'), get('end_time')
        if lang and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            shares[lang] = shares.get(lang, 0.0) + max(0.0, end - start)
    return shares


def dominant_language(segments, fallback: str = '') -> str:
    """La langue la plus PARLÉE (en durée) — celle d'une card qui en porte plusieurs."""
    shares = language_shares(segments)
    return max(shares, key=shares.get) if shares else fallback
