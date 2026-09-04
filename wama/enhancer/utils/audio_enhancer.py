"""
WAMA Enhancer — Audio Speech Enhancement Backend

Engines:
  - Resemble Enhance (MIT): dual-stage denoising + enhancement, 44.1kHz output
  - DeepFilterNet 3 (MIT): real-time noise suppression, 48kHz, ultra-fast

⚠️  HF_HUB_CACHE is set BEFORE resemble_enhance import to redirect model download
    to AI-models/models/speech/resemble-enhance/ (same rule as other HF models).
"""

import gc
import logging
import os
from pathlib import Path
from typing import Literal, Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# torchaudio 2.9+ compatibility patch (TorchCodec → soundfile shim)
# ---------------------------------------------------------------------------

def _patch_torchaudio_compat() -> None:
    """
    torchaudio 2.9 replaced load/save/info with TorchCodec (requires FFmpeg).
    deepfilternet also needs torchaudio.backend.common (removed in 2.0).

    BRIQUE COMMUNE depuis 2026-08-17 (`common/utils/torchaudio_compat.py`) — le corps
    inline historique en était la source ; le service TTS (Coqui) portait une 2e copie.
    Called once at module import so both ResembleEnhance and DeepFilterNet benefit.
    """
    from wama.common.utils.torchaudio_compat import patch_torchaudio_soundfile
    patch_torchaudio_soundfile(stub_backend_common=True, patch_info=True, patch_save=True)


# Apply at import time so both backends benefit
_patch_torchaudio_compat()


# ---------------------------------------------------------------------------
# Torch 2.x / deepspeed compatibility patch
# ---------------------------------------------------------------------------

def _patch_torch_elastic() -> None:
    """
    deepspeed is incompatible with torch 2.x and is only used by resemble_enhance
    for training configuration — never called during inference.

    Strategy: install a meta-path finder that intercepts ALL deepspeed.* imports
    and returns stub modules, so resemble_enhance loads without error.
    """
    import sys
    if any(f.__class__.__name__ == '_DeepSpeedMockFinder' for f in sys.meta_path):
        return  # already installed

    import types
    import importlib.abc
    import importlib.machinery
    from unittest.mock import MagicMock

    _shared_mm = MagicMock()

    class _DeepSpeedMockLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None  # default module object

        def exec_module(self, module):
            module.__path__    = []
            module.__version__ = '0.0.0-mock'
            # Any attribute access (class names, functions, …) returns MagicMock
            module.__getattr__ = lambda name: _shared_mm

    class _DeepSpeedMockFinder(importlib.abc.MetaPathFinder):
        _loader = _DeepSpeedMockLoader()

        def find_spec(self, fullname, path, target=None):
            if fullname == 'deepspeed' or fullname.startswith('deepspeed.'):
                return importlib.machinery.ModuleSpec(
                    fullname, self._loader, is_package=True
                )
            return None

    sys.meta_path.insert(0, _DeepSpeedMockFinder())
    logger.debug("[audio_enhancer] deepspeed mock finder installed (all deepspeed.* → stubs)")


# ---------------------------------------------------------------------------
# Model cache directories
# ---------------------------------------------------------------------------

def _get_resemble_cache() -> Path:
    try:
        from django.conf import settings
        d = Path(settings.MODEL_PATHS['speech']['resemble_enhance'])
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path.home() / ".cache" / "resemble-enhance"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _get_deepfilternet_cache() -> Path:
    try:
        from django.conf import settings
        d = Path(settings.MODEL_PATHS['speech']['deepfilternet'])
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path.home() / ".cache" / "DeepFilterNet"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------------------
# Resemble Enhance backend
# ---------------------------------------------------------------------------

class ResembleEnhanceBackend(BaseModelBackend):
    """
    Resemble Enhance — dual-stage speech enhancement (MIT).

    Stage 1 — Denoiser:  CRUSE-based noise separation
    Stage 2 — Enhancer:  diffusion-based bandwidth extension (44.1 kHz output)

    VRAM: 4–6 GB  |  Speed: fast

    NB : backend SANS état persistant — les poids se chargent par appel dans re_denoise/re_enhance.
    `load()` ne fait que réchauffer (vérifier l'import) ; `unload()` est un no-op honnête.
    """

    REQUIRED_PACKAGES = ['resemble_enhance']
    recommended_vram_gb = 6.0
    description = "Resemble Enhance — débruitage + extension de bande (diffusion), MIT."

    def __init__(self):
        self._cache_dir = _get_resemble_cache()
        # ⚠ MUTATION RETIRÉE le 2026-09-04 (ROADMAP §5b) — elle ne routait RIEN : mesuré,
        # `resemble_enhance` télécharge son modèle par `git clone` DANS SON PROPRE PAQUET
        # (`site-packages/resemble_enhance/model_repo`, cf. `enhancer/download.py`), et ne
        # consulte jamais le cache HF. Son seul effet réel était donc de détourner les
        # téléchargements HF des AUTRES libs vers le dossier resemble, pour toute la durée du
        # processus. Un cas à part dans ce chantier : une mutation sans bénéfice, même
        # apparent — le `cache_dir` reste utile au voisin DeepFilterNet (l. ~317).
        self._warm = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            _patch_torch_elastic()
            import resemble_enhance  # noqa: F401
            return True
        except (ImportError, Exception):
            return False

    # ── Contrat BaseModelBackend ─────────────────────────────────────────────
    def load(self, model: Optional[str] = None) -> bool:
        """Réchauffe (vérifie l'import des fonctions). Le modèle réel se charge par appel."""
        self._load_resemble()
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        # Pas de modèle persistant à libérer (chargement par appel) ; on réinitialise l'état.
        self._warm = False
        gc.collect()

    def process(self, **kwargs):
        """Point d'entrée générique → délègue à enhance()."""
        return self.enhance(**kwargs)

    def _get_device(self) -> str:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_resemble(self):
        """Import resemble_enhance after applying the torch 2.x compatibility patch."""
        _patch_torch_elastic()
        from resemble_enhance.enhancer.inference import denoise as re_denoise, enhance as re_enhance
        return re_denoise, re_enhance

    def enhance(
        self,
        input_path: str,
        output_path: str,
        mode: Literal["both", "denoise", "enhance"] = "both",
        denoising_strength: float = 0.5,
        nfe: int = 64,
        progress_callback=None,
    ) -> str:
        """
        Enhance speech audio with Resemble Enhance.

        Args:
            input_path:         Path to input audio file
            output_path:        Path to output WAV file
            mode:               'both' (denoise+enhance), 'denoise', 'enhance'
            denoising_strength: tau parameter 0.0–1.0 (denoising amount)
            nfe:                Number of function evaluations (32=fast, 64=balanced, 128=best)
            progress_callback:  Optional 0–100 progress function

        Returns:
            output_path on success
        """
        import torchaudio  # already patched at module load; import for local reference

        device = self._get_device()
        logger.info(f"[ResembleEnhance] device={device}, mode={mode}, nfe={nfe}, tau={denoising_strength}")

        if progress_callback:
            progress_callback(10)

        # Load audio
        audio, sr = torchaudio.load(input_path)
        logger.info(f"[ResembleEnhance] Input: sr={sr}, shape={audio.shape}")

        # Mono
        if audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)

        # Squeeze to 1-D tensor (resemble_enhance expects shape [T])
        dwav = audio.squeeze(0)

        if progress_callback:
            progress_callback(20)

        # Import AFTER setting HF_HUB_CACHE and patching torch 2.x compat
        re_denoise, re_enhance = self._load_resemble()

        if mode == "denoise":
            logger.info("[ResembleEnhance] Denoising only…")
            out_wav, out_sr = re_denoise(dwav, sr, device)
        elif mode == "enhance":
            logger.info("[ResembleEnhance] Enhancing only (no denoising)…")
            out_wav, out_sr = re_enhance(dwav, sr, device, nfe=nfe, solver="midpoint", tau=0.0)
        else:  # both
            logger.info("[ResembleEnhance] Denoise + Enhance…")
            out_wav, out_sr = re_enhance(dwav, sr, device, nfe=nfe, solver="midpoint", tau=denoising_strength)

        if progress_callback:
            progress_callback(85)

        # Save output
        import soundfile as sf
        import numpy as np

        out_np = out_wav.cpu().numpy() if hasattr(out_wav, 'cpu') else np.array(out_wav)
        sf.write(output_path, out_np, int(out_sr))
        logger.info(f"[ResembleEnhance] Saved to {output_path} (sr={out_sr})")

        if progress_callback:
            progress_callback(100)

        return output_path


# ---------------------------------------------------------------------------
# DeepFilterNet 3 backend
# ---------------------------------------------------------------------------

class DeepFilterNetBackend(BaseModelBackend):
    """
    DeepFilterNet 3 — real-time speech noise suppression (MIT).

    Ultra-fast, <1 GB VRAM, supports up to 48 kHz, streaming-capable.
    Garde le modèle en mémoire (keep_loaded) ; singleton via get_deepfilternet_backend().
    """

    REQUIRED_PACKAGES = ['df']
    recommended_vram_gb = 1.0
    description = "DeepFilterNet 3 — débruitage temps réel (discriminatif), MIT."

    def __init__(self):
        self._model = None
        self._df_state = None
        self._cache_dir = _get_deepfilternet_cache()

    @classmethod
    def is_available(cls) -> bool:
        # Override try-import : 'df' peut être présent (find_spec) mais échouer sur sa lib native.
        try:
            import df  # noqa: F401
            return True
        except Exception as e:
            logger.warning("[DeepFilterNet] import df failed: %s", e)
            return False

    # ── Contrat BaseModelBackend ─────────────────────────────────────────────
    def load(self, model: Optional[str] = None) -> bool:
        """Charge le modèle (idempotent) et retourne l'état de chargement."""
        self._ensure_loaded()
        return self.is_loaded

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def process(self, **kwargs):
        """Point d'entrée générique → délègue à enhance()."""
        return self.enhance(**kwargs)

    def _ensure_loaded(self):
        if self._model is None:
            logger.info("[DeepFilterNet] Loading model…")
            # Model lives at: <cache_dir>/DeepFilterNet3/config.ini
            # Pass the model directory directly; deepfilternet skips download
            # when the path is not one of the PRETRAINED_MODELS names.
            import df.enhance as _df_enhance
            model_dir = self._cache_dir / "DeepFilterNet3"
            if not (model_dir / "config.ini").exists():
                # First run: redirect get_cache_dir so maybe_download_model()
                # saves to our AI-models directory.
                _orig = _df_enhance.get_cache_dir
                _df_enhance.get_cache_dir = lambda: str(self._cache_dir)
                try:
                    from df import init_df
                    self._model, self._df_state, _ = init_df("DeepFilterNet3")
                finally:
                    _df_enhance.get_cache_dir = _orig
            else:
                from df import init_df
                self._model, self._df_state, _ = init_df(str(model_dir))
            logger.info("[DeepFilterNet] Model loaded ✓")

    # ── Garde-fou mémoire (2026-07-25) ───────────────────────────────────────
    # `load_audio()` charge le fichier ENTIER à 48 kHz, tous canaux, et `df_enhance()`
    # traite tout le signal en UN appel (STFT/ERB sur la totalité). Sur un 2 h 21 stéréo :
    # 3,3 Go rien que pour l'entrée, ~13,7 Go de RSS au pic → **OOM killer**, worker `gpu`
    # (pool solo) tué net, sans traceback, file `gpu` sans consommateur. Constaté le
    # 2026-07-25 sur la transcription #176 (dmesg : anon-rss 14385544 kB, VM WSL2 = 15 Go).
    # Au-delà du seuil on bascule en fenêtrage disque→disque : RAM bornée à une fenêtre,
    # quelle que soit la durée. DFN est un modèle TEMPS RÉEL (trames de 20 ms) : le
    # découpage lui est fidèle — contrairement à la diarisation, dont le clustering de
    # locuteurs est global (fenêtrage annulé au commit 6cc37ec, ne pas confondre).
    LONG_AUDIO_THRESHOLD_S = 600.0   # 10 min → fenêtrage
    WINDOW_S = 120.0                 # durée traitée par passe
    WINDOW_OVERLAP_S = 0.5           # recouvrement fondu (pas de clic aux jointures)

    def enhance(
        self,
        input_path: str,
        output_path: str,
        progress_callback=None,
        mono: bool = False,
    ) -> str:
        """
        Enhance speech audio with DeepFilterNet 3.

        Args:
            input_path:        Path to input audio file
            output_path:       Path to output WAV file
            progress_callback: Optional 0–100 progress function
            mono:              True → downmix mono AVANT débruitage (moitié moins de RAM,
                               et sans aucune perte pour un appelant qui finit en mono —
                               ex. le prétraitement ASR du transcriber, qui reconvertit
                               en 16 kHz mono juste après).

        Returns:
            output_path on success

        Note: au-delà de LONG_AUDIO_THRESHOLD_S, le traitement passe en fenêtré et la
        sortie est MONO (contrainte de `decode_window`) — seule façon de borner la RAM.
        """
        self._ensure_loaded()

        if progress_callback:
            progress_callback(20)

        from wama.common.utils.audio_decode import probe_duration_seconds
        duration = probe_duration_seconds(input_path) or 0.0
        if duration > self.LONG_AUDIO_THRESHOLD_S:
            if not mono:
                logger.warning(f"[DeepFilterNet] Fichier long ({duration / 60:.0f} min) → "
                               "débruitage fenêtré, sortie MONO (garde-fou mémoire)")
            return self._enhance_windowed(input_path, output_path, duration, progress_callback)

        from df.enhance import enhance as df_enhance, load_audio, save_audio

        # Load at model sample rate
        audio, _ = load_audio(input_path, sr=self._df_state.sr())
        if mono and audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)
        logger.info(f"[DeepFilterNet] Input: sr={self._df_state.sr()}, shape={audio.shape}")

        if progress_callback:
            progress_callback(40)

        enhanced = df_enhance(self._model, self._df_state, audio, pad=True)

        if progress_callback:
            progress_callback(85)

        save_audio(output_path, enhanced, self._df_state.sr())
        logger.info(f"[DeepFilterNet] Saved to {output_path}")

        if progress_callback:
            progress_callback(100)

        return output_path

    def _enhance_windowed(self, input_path: str, output_path: str, duration: float,
                          progress_callback=None) -> str:
        """
        Débruitage d'un long média par fenêtres, disque → disque (RAM constante).

        Décodage fenêtré par la brique COMMUNE `audio_decode.decode_window` (ffmpeg, seek
        avant `-i`) — pas de décodeur maison, et pas de torchcodec (cassé, cf.
        `memory/reference_torchcodec_broken.md`). Écriture incrémentale via soundfile :
        le signal débruité complet n'est jamais tenu en mémoire non plus.

        Les fenêtres se recouvrent de WINDOW_OVERLAP_S, recollées en fondu enchaîné
        linéaire : pas de discontinuité audible aux jointures.
        """
        import numpy as np
        import soundfile as sf
        import torch
        from df.enhance import enhance as df_enhance
        from wama.common.utils.audio_decode import decode_window

        sr = self._df_state.sr()
        overlap_n = int(self.WINDOW_OVERLAP_S * sr)
        fade_in = np.linspace(0.0, 1.0, overlap_n, dtype=np.float32) if overlap_n else None
        n_windows = max(1, int(np.ceil(duration / self.WINDOW_S)))
        logger.info(f"[DeepFilterNet] Fenêtrage : {duration:.0f} s → {n_windows} fenêtre(s) "
                    f"de {self.WINDOW_S:.0f} s (sr={sr}, mono) — RAM bornée")

        prev_tail = None   # queue de la fenêtre précédente, en attente de fondu
        start = 0.0
        with sf.SoundFile(output_path, 'w', samplerate=sr, channels=1, subtype='PCM_16') as out:
            while start < duration:
                chunk, _ = decode_window(input_path, target_sr=sr, start_s=start,
                                         duration_s=self.WINDOW_S + self.WINDOW_OVERLAP_S,
                                         mono=True)
                if chunk.size == 0:
                    break

                # .copy() : decode_window renvoie une vue np.frombuffer NON inscriptible
                # (torch.from_numpy prévient alors d'un comportement indéfini si la lib
                # écrivait dedans). Copie d'une fenêtre = ~23 Mo, négligeable.
                enhanced = df_enhance(self._model, self._df_state,
                                      torch.from_numpy(chunk.copy()).unsqueeze(0), pad=True)
                y = enhanced.squeeze(0).detach().cpu().numpy().astype(np.float32)

                # Fondu enchaîné avec la queue réservée par la fenêtre précédente.
                if prev_tail is not None and y.size:
                    n = min(prev_tail.size, y.size)
                    out.write(y[:n] * fade_in[:n] + prev_tail[:n] * (1.0 - fade_in[:n]))
                    y = y[n:]

                # Réserve la zone de recouvrement pour le fondu de la fenêtre suivante.
                has_next = (start + self.WINDOW_S) < duration
                if has_next and overlap_n and y.size > overlap_n:
                    prev_tail = y[-overlap_n:].copy()
                    y = y[:-overlap_n]
                else:
                    prev_tail = None

                out.write(y)
                start += self.WINDOW_S

                if progress_callback:
                    progress_callback(40 + int(45 * min(1.0, start / max(duration, 1e-6))))

        logger.info(f"[DeepFilterNet] Saved to {output_path} (fenêtré)")
        if progress_callback:
            progress_callback(100)
        return output_path

    def unload(self):
        self._model = None
        self._df_state = None
        gc.collect()


# ---------------------------------------------------------------------------
# Singleton DeepFilterNet (keep_loaded) — partagé enhancer + transcriber
# ---------------------------------------------------------------------------
# DeepFilterNet est minuscule (<1 Go VRAM) : on garde l'instance chargée et on
# la réutilise entre tâches (et entre apps). Évite de recharger le modèle à
# chaque fichier d'un batch. Cohabite sans problème avec l'ASR (Whisper) en VRAM.

_DFN_SINGLETON = None


def get_deepfilternet_backend():
    """Retourne l'instance DeepFilterNet partagée (chargée à la 1ʳᵉ demande)."""
    global _DFN_SINGLETON
    if _DFN_SINGLETON is None:
        _DFN_SINGLETON = DeepFilterNetBackend()
    return _DFN_SINGLETON


# ---------------------------------------------------------------------------
# Routing helper
# ---------------------------------------------------------------------------

def run_audio_enhancement(
    input_path: str,
    output_path: str,
    engine: str = "resemble",
    mode: str = "both",
    denoising_strength: float = 0.5,
    quality: int = 64,
    progress_callback=None,
) -> str:
    """
    Route to the correct audio enhancement engine.

    Args:
        input_path:         Input audio file path
        output_path:        Output audio file path (WAV)
        engine:             'resemble' | 'deepfilternet'
        mode:               'both' | 'denoise' | 'enhance'  (Resemble only)
        denoising_strength: 0.0–1.0  (Resemble only)
        quality:            NFE 32/64/128  (Resemble only)
        progress_callback:  Optional 0–100 progress function

    Returns:
        output_path on success
    """
    if engine == "deepfilternet":
        if not DeepFilterNetBackend.is_available():
            raise RuntimeError(
                "DeepFilterNet non installé. Exécutez : pip install deepfilternet"
            )
        backend = get_deepfilternet_backend()  # singleton keep_loaded
        return backend.enhance(input_path, output_path, progress_callback=progress_callback)

    else:  # resemble (default)
        if not ResembleEnhanceBackend.is_available():
            raise RuntimeError(
                "Resemble Enhance non installé. Exécutez : pip install resemble-enhance"
            )
        backend = ResembleEnhanceBackend()
        return backend.enhance(
            input_path, output_path,
            mode=mode,
            denoising_strength=denoising_strength,
            nfe=quality,
            progress_callback=progress_callback,
        )
