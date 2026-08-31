"""
Backend Kokoro ONNX — les MÊMES poids que Kokoro 82M, servis par onnxruntime
(doctrine inférence-first du 2026-08-31 : ONNX par défaut, tiré du dépôt d'export
OFFICIEL `onnx-community/Kokoro-82M-v1.0-ONNX` — jamais fabriqué localement, un
KPipeline ne s'exporte pas d'un bloc).

Premier adaptateur du motif « backend DÉCLARÉ » : le modèle n'est PAS codé ici —
ses composants viennent de `AIModel.composition` (projetée depuis le manifeste
`model`, elle-même MESURÉE sur disque), avec un repli Django-free sur les MÊMES
motifs (le service TTS n'initialise pas Django ; les défauts de l'adaptateur sont
la copie des motifs déclarés, la déclaration prime quand l'ORM est là).

Le fichier de voix est un artefact DÉRIVÉ : kokoro_onnx attend un .npz clé→style
(`np.load(voices_path)`), le dépôt publie 40 `voices/*.bin` de 510×256 float32
(un vecteur de style par longueur de phonèmes, rangée n-1 → forme (510, 1, 256)).
On assemble `voices-derived.npz` dans le dossier FAMILLE (pas dans le snapshot —
il reste un miroir fidèle du dépôt), idempotent — même motif que les alias
audio.cpp (`ensure_engine_default_aliases`).
"""
from __future__ import annotations

import glob
import logging
import os
from pathlib import Path

import numpy as np

from .base import TTSBackend, ai_models_dir, write_wav_int16

logger = logging.getLogger(__name__)

#: Identité du modèle au catalogue (clé du balayage générique des snapshots HF).
CATALOG_KEY = 'huggingface:onnx-community/Kokoro-82M-v1.0-ONNX'
FAMILY_DIR = 'Kokoro-82M-v1.0-ONNX'
SNAPSHOT_DIRNAME = 'models--onnx-community--Kokoro-82M-v1.0-ONNX'

#: Défauts de l'adaptateur = COPIE des motifs déclarés au manifeste (la déclaration
#: prime via _declared_patterns quand l'ORM est disponible).
DEFAULT_PATTERNS = {'acoustic_model': 'onnx/model.onnx', 'voices': 'voices/*.bin'}

#: Codes espeak-ng par langue WAMA — kokoro_onnx phonémise par espeak (branche unique,
#: pas de pipeline par langue comme KPipeline). ja/zh passent par espeak aussi : PRONONCÉS
#: mais de qualité moindre que la voie misaki du jumeau .pt — déclarés en repli, pas en
#: langues gérées, tant qu'un banc ne les a pas jugés.
ESPEAK_LANG = {
    'fr': 'fr-fr',
    'en': 'en-us',
    'es': 'es',
    'it': 'it',
    'pt': 'pt-br',
}
ESPEAK_FALLBACK = {'ja': 'ja', 'zh-cn': 'cmn'}


def _declared_patterns() -> dict:
    """Motifs de composants DÉCLARÉS (AIModel.composition, projetée du manifeste) —
    repli sur les défauts de l'adaptateur quand Django n'est pas là (service TTS)."""
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=CATALOG_KEY).first()
        comps = ((row.composition or {}).get('components') or []) if row else []
        motifs = {c['role']: c['pattern'] for c in comps
                  if isinstance(c, dict) and c.get('role') and c.get('pattern')}
        if motifs:
            return {**DEFAULT_PATTERNS, **motifs}
    except Exception:
        pass
    return dict(DEFAULT_PATTERNS)


def _snapshot_dir() -> Path | None:
    """Dernier snapshot HF du dépôt d'export (repli disque, Django-free)."""
    racine = ai_models_dir() / 'models' / 'speech' / FAMILY_DIR / SNAPSHOT_DIRNAME / 'snapshots'
    if not racine.is_dir():
        return None
    revs = sorted((d for d in racine.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime)
    return revs[-1] if revs else None


class KokoroOnnxBackend(TTSBackend):
    engine = "kokoro-onnx"
    description = ("Kokoro 82M (export ONNX officiel) — mêmes poids que Kokoro, servis par "
                   "onnxruntime ; phonémisation espeak-ng, 40 voix embarquées.")

    supports_cloning = False
    #: kokoro_onnx expose des timings, non câblés ici — on ne promet rien d'invérifié.
    supports_timestamps = False
    fallback_languages = sorted(ESPEAK_FALLBACK)

    #: Noms d'IMPORT (contrat commun) ; le nom pip diffère → PIP_PACKAGES.
    REQUIRED_PACKAGES = ['kokoro_onnx']
    PIP_PACKAGES = ['kokoro-onnx']

    recommended_vram_gb = 0.5

    def __init__(self):
        super().__init__()
        self._kokoro = None

    @property
    def is_loaded(self) -> bool:
        return self._kokoro is not None

    def load(self, model: str | None = None) -> bool:
        if self._kokoro is not None:
            return True
        snapshot = _snapshot_dir()
        if snapshot is None:
            raise RuntimeError(
                f"Kokoro-ONNX : snapshot absent ({FAMILY_DIR}) — installer "
                f"{CATALOG_KEY.split(':', 1)[1]} d'abord (prospection → installer).")
        motifs = _declared_patterns()
        model_path = snapshot / motifs['acoustic_model']
        if not model_path.is_file():
            raise RuntimeError(f"Kokoro-ONNX : composant acoustic_model absent ({model_path})")
        voices_npz = self._ensure_voices_npz(snapshot, motifs['voices'])

        from kokoro_onnx import Kokoro
        self._kokoro = Kokoro(str(model_path), str(voices_npz))
        self.loaded_model = "kokoro-onnx"
        self._current_model = "kokoro-onnx"
        logger.info("[Kokoro-ONNX] chargé : %s (%d voix)",
                    model_path.name, len(self._kokoro.get_voices()))
        return True

    def unload(self) -> None:
        if self._kokoro is None:
            return
        self._kokoro = None
        self.loaded_model = None
        self._current_model = None

    def _ensure_voices_npz(self, snapshot: Path, pattern: str) -> Path:
        """Assemble (une fois) le .npz clé→style attendu par kokoro_onnx depuis les
        `voices/*.bin` du dépôt (510×256 float32 → forme (510, 1, 256), la rangée n-1
        étant le vecteur de style pour n phonèmes). Dossier FAMILLE, jamais le snapshot."""
        cible = snapshot.parent.parent.parent / 'voices-derived.npz'
        bins = sorted(glob.glob(str(snapshot / pattern)))
        if cible.is_file() and cible.stat().st_mtime >= max(
                (os.path.getmtime(b) for b in bins), default=0):
            return cible
        if not bins:
            raise RuntimeError(f"Kokoro-ONNX : aucune voix ne répond au motif {pattern!r}")
        voix = {}
        for b in bins:
            brut = np.fromfile(b, dtype=np.float32)
            if brut.size % (510 * 256):
                logger.warning("[Kokoro-ONNX] voix ignorée (taille inattendue) : %s", b)
                continue
            voix[Path(b).stem] = brut.reshape(510, -1, 256)
        if not voix:
            raise RuntimeError("Kokoro-ONNX : aucune voix exploitable")
        # ⚠ np.savez AJOUTE '.npz' à tout nom qui ne se termine pas par '.npz' (vécu au
        # 1ᵉʳ smoke : un tmp '….npz.tmp' était écrit '….npz.tmp.npz' et os.replace échouait).
        tmp = cible.with_name('voices-derived.tmp.npz')
        np.savez(tmp, **voix)
        os.replace(tmp, cible)
        logger.info("[Kokoro-ONNX] voices-derived.npz assemblé (%d voix)", len(voix))
        return cible

    def process(self, text: str = "", language: str = "fr",
                voice_preset: str = "default", **_ignored) -> str:
        # Même brique de résolution langue→voix que le jumeau .pt (zéro duplication) :
        # les noms de voix du dépôt ONNX sont IDENTIQUES à ceux du dépôt .pt.
        from wama.common.tts.voices import voix_pour
        if self._kokoro is None:
            self.load()
        voice = voix_pour(language, voice_preset in ('male_1', 'male_2'))
        lang = ESPEAK_LANG.get(language) or ESPEAK_FALLBACK.get(language) or 'en-us'
        samples, sr = self._kokoro.create(text, voice=voice, speed=1.0, lang=lang)
        if samples is None or not len(samples):
            raise RuntimeError("Kokoro-ONNX : aucun audio généré")
        return write_wav_int16(np.asarray(samples, dtype=np.float32), sr)
