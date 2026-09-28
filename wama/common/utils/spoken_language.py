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
