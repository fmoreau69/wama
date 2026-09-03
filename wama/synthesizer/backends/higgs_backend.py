"""
Backend Higgs Audio v2 (Boson AI, 3B) — multi-locuteurs + clonage de voix.

Porte les compat-patches transformers 4.57+ requis par `boson_multimodal`
(complément runtime des patches de fichiers de `patches/apply_patches.py` #1)
et le VERROU de génération : l'engine mute `current_past_key_values_bucket` sur
l'instance partagée — deux générations simultanées corrompent le KV cache
(« target cache size 1024 is smaller than source cache size 4096 »).
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading

import numpy as np

from wama.common.tts.constants import LANGUAGE_NAMES_EN

from .base import CATALOG_KEYS, TTSBackend, project_root, speech_dir, write_wav_int16

logger = logging.getLogger(__name__)

MODEL_PATH = "bosonai/higgs-audio-v2-generation-3B-base"
TOKENIZER_PATH = "bosonai/higgs-audio-v2-tokenizer"

#: Higgs v2 est entraîné sur des références de 3-8 s : au-delà, le contexte KV
#: gonfle et la qualité de génération se dégrade — on tronque à 6 s.
MAX_REF_DURATION_S = 6.0


class HiggsAudioBackend(TTSBackend):
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'higgs'
    engine = "higgs"
    description = "Higgs Audio v2 — multi-locuteurs, clonage, conditionnement de scène."

    supports_cloning = True    # clonage multi-locuteurs (aligné sur le catalogue)

    REQUIRED_PACKAGES = ['boson_multimodal', 'transformers', 'librosa', 'soundfile', 'scipy']
    # boson_multimodal s'installe depuis le dépôt Boson AI (pas de wheel PyPI fiable).
    PIP_PACKAGES = []

    recommended_vram_gb = 16.0

    #: Une seule génération à la fois sur l'instance partagée (voir docstring module).
    _generation_lock = threading.Lock()

    def __init__(self):
        super().__init__()
        self._engine = None

    @property
    def is_loaded(self) -> bool:
        return self._engine is not None

    def load(self, model: str | None = None) -> bool:
        if self._engine is not None:
            return True

        # ── CRITIQUE : cache HF isolé AVANT tout import HF (règle CLAUDE.md) ──
        cache_dir = speech_dir('higgs')
        os.environ['HF_HUB_CACHE'] = str(cache_dir)
        os.environ['HUGGINGFACE_HUB_CACHE'] = str(cache_dir)

        self._patch_transformers()

        from boson_multimodal.serve.serve_engine import HiggsAudioServeEngine

        logger.info(f"[Higgs] chargement de l'engine : {MODEL_PATH}")
        self._engine = HiggsAudioServeEngine(
            model_name_or_path=MODEL_PATH,
            audio_tokenizer_name_or_path=TOKENIZER_PATH,
            device="cuda",
        )
        self.loaded_model = "higgs-audio"
        self._current_model = CATALOG_KEYS['higgs-audio']

        # Debug : désactiver entièrement les CUDA graphs (start_wama_prod.sh l'exporte).
        if os.environ.get("HIGGS_DISABLE_CUDA_GRAPHS"):
            self._engine.model.decode_graph_runners.clear()
            logger.warning("[Higgs debug] CUDA graphs DISABLED via HIGGS_DISABLE_CUDA_GRAPHS")
        return True

    def unload(self) -> None:
        if self._engine is None:
            return
        logger.info("[Higgs] déchargement de l'engine")
        del self._engine
        self._engine = None
        self.loaded_model = None
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # ------------------------------------------------------------------

    def process(self, text: str = "", language: str = "fr",
                speaker_wav: str | None = None, multi_speaker: bool = False,
                scene_description: str = "", **_ignored) -> str:
        """Génère un WAV 48 kHz. `speaker_wav` est déjà résolu par l'appelant (preset→fichier)."""
        from boson_multimodal.data_types import AudioContent, ChatMLSample, Message, TextContent

        content_parts = []
        _tmp_ref_path = None  # fichier tronqué à nettoyer

        lang_name = LANGUAGE_NAMES_EN.get(language, language.capitalize())
        system_message = Message(
            role="system",
            content=TextContent(text=f"Generate high-quality {lang_name} speech audio of the provided text.")
        )

        ref_wav = speaker_wav
        if ref_wav and os.path.exists(ref_wav):
            logger.info(f"[Higgs] Voice reference: {ref_wav}")
        else:
            if ref_wav:
                logger.warning(f"[Higgs] Voice reference introuvable ({ref_wav!r}) — voix par défaut")
            ref_wav = None

        if ref_wav:
            ref_wav, _tmp_ref_path = self._trim_reference(ref_wav)
            # Chemin passé tel quel — serve_engine charge via librosa.load(audio_url)
            content_parts.append(AudioContent(audio_url=ref_wav))

        final_text = text
        if multi_speaker and scene_description:
            final_text = f"<|scene_desc_start|>{scene_description.strip()}<|scene_desc_end|>{text}"
        content_parts.append(TextContent(text=final_text))

        chat_ml = ChatMLSample(messages=[
            system_message,
            Message(role="user", content=content_parts)
        ])

        # Budget de tokens : ~300 tokens audio/s, parole ~2,5 mots/s, marge 1,5× + 1500
        # d'overhead. L'ancien max(8192, …) générait 8192 tokens pour 23 mots → timeout.
        _words = len(text.split())
        _estimated_audio_tokens = int(_words / 2.5 * 300)
        max_tokens = min(max(int(_estimated_audio_tokens * 1.5) + 1500, 2000), 75000)
        logger.info(f"[Higgs] max_tokens={max_tokens} for {_words} words (~{_estimated_audio_tokens} audio tokens)")

        with self._generation_lock:
            self._log_kv_caches("BEFORE")
            logger.info(f"[Higgs diag] max_tokens={max_tokens}, text_chars={len(text)}")
            output = self._engine.generate(
                chat_ml_sample=chat_ml,
                max_new_tokens=max_tokens,
                temperature=0.7,   # défaut serve_engine ; 0.3 provoquait des EOS précoces
                top_p=0.95,
                force_audio_gen=True,
            )

        if output.audio is None or len(output.audio) == 0:
            raise ValueError("Higgs Audio returned empty audio")

        actual_sr = int(output.sampling_rate) if getattr(output, 'sampling_rate', None) else 24000
        logger.info(f"[Higgs] {len(output.audio)} samples @ {actual_sr} Hz = {len(output.audio)/actual_sr:.1f}s")
        if output.usage:
            logger.info(f"[Higgs diag] Usage: {output.usage}")
        self._log_kv_caches("AFTER")
        self._log_audio_tokens(output)

        combined = np.asarray(output.audio, dtype=np.float32)
        max_val = np.max(np.abs(combined))
        if max_val > 0:
            combined = combined / max_val

        # Rééchantillonnage 48 kHz (sortie native Higgs = 24 kHz)
        target_sr = 48000
        if actual_sr != target_sr:
            from scipy.signal import resample as scipy_resample
            num_samples = int(len(combined) * target_sr / actual_sr)
            combined = scipy_resample(combined, num_samples).astype(np.float32)
            logger.info(f"[Higgs] resampled {actual_sr}Hz → {target_sr}Hz ({len(combined)} samples)")
            actual_sr = target_sr

        wav_path = write_wav_int16(combined, actual_sr, normalize=False)

        if _tmp_ref_path:
            try:
                os.remove(_tmp_ref_path)
            except OSError:
                pass
        return wav_path

    # ------------------------------------------------------------------

    @staticmethod
    def _trim_reference(ref_wav: str):
        """Tronque la référence à `MAX_REF_DURATION_S`. Rend (chemin, tmp_à_nettoyer|None)."""
        try:
            import librosa
            import soundfile as _sf
            _raw, _sr = librosa.load(ref_wav, sr=None)
            _dur = len(_raw) / _sr
            logger.info(f"[Higgs] Voice reference: {_dur:.1f}s @ {_sr}Hz")
            max_samples = int(MAX_REF_DURATION_S * _sr)
            if len(_raw) > max_samples:
                _raw = _raw[:max_samples]
                _tmp_ref = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                                       dir=str(project_root() / "logs"))
                _sf.write(_tmp_ref.name, _raw, _sr)
                _tmp_ref.close()
                logger.info(f"[Higgs] Voice reference trimmed to {MAX_REF_DURATION_S}s → {_tmp_ref.name}")
                return _tmp_ref.name, _tmp_ref.name
        except Exception as _e:
            logger.warning(f"[Higgs] Could not trim reference audio: {_e} — using original")
        return ref_wav, None

    def _log_kv_caches(self, moment: str) -> None:
        try:
            for bucket_len, kv_cache in self._engine.kv_caches.items():
                logger.info(f"[Higgs diag] KV cache[{bucket_len}] seq_length {moment} = "
                            f"{kv_cache.get_seq_length()}")
        except Exception as _e:
            logger.debug(f"[Higgs diag] Could not read cache lengths: {_e}")

    @staticmethod
    def _log_audio_tokens(output) -> None:
        try:
            _tok = output.generated_audio_tokens  # (num_codebooks, num_steps)
            if _tok is not None and hasattr(_tok, 'shape'):
                _n_steps = _tok.shape[1] if len(_tok.shape) > 1 else len(_tok)
                _unique = len(set(_tok.flatten().tolist())) if hasattr(_tok, 'flatten') else '?'
                _min_t = int(_tok.min()) if hasattr(_tok, 'min') else '?'
                _max_t = int(_tok.max()) if hasattr(_tok, 'max') else '?'
                logger.info(f"[Higgs diag] Audio tokens: {_n_steps} steps, "
                            f"range [{_min_t},{_max_t}], {_unique} unique values")
        except Exception as _de:
            logger.debug(f"[Higgs diag] Could not inspect audio tokens: {_de}")

    @staticmethod
    def _patch_transformers() -> None:
        """Compat boson_multimodal ↔ transformers 4.57+ (lazy : ~60-90 s d'import évités
        au démarrage du service si Higgs n'est jamais demandé)."""
        try:
            from transformers.models.llama import modeling_llama as _llama_module
            if not hasattr(_llama_module, "LLAMA_ATTENTION_CLASSES"):
                _llama_module.LLAMA_ATTENTION_CLASSES = {
                    "eager": _llama_module.LlamaAttention,
                    "sdpa": _llama_module.LlamaAttention,
                    "flash_attention_2": _llama_module.LlamaAttention,
                }
                logger.info("[Higgs] Patched LLAMA_ATTENTION_CLASSES for boson_multimodal")
        except Exception as e:
            logger.warning(f"[Higgs] Could not patch LLAMA_ATTENTION_CLASSES: {e}")

        try:
            from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS
            _patched_keys = []
            for _key in (None, "eager"):
                if _key not in ALL_ATTENTION_FUNCTIONS:
                    ALL_ATTENTION_FUNCTIONS[_key] = ALL_ATTENTION_FUNCTIONS["sdpa"]
                    _patched_keys.append(repr(_key))
            if _patched_keys:
                logger.info(f"[Higgs] Patched ALL_ATTENTION_FUNCTIONS: added {', '.join(_patched_keys)} → sdpa")
        except Exception as e:
            logger.warning(f"[Higgs] Could not patch ALL_ATTENTION_FUNCTIONS: {e}")

        try:
            from transformers import GenerationConfig as _GC
            if not hasattr(_GC, "generation_kwargs"):
                _orig_gc_init = _GC.__init__

                def _patched_gc_init(self, *args, **kwargs):
                    _orig_gc_init(self, *args, **kwargs)
                    if not isinstance(getattr(self, "generation_kwargs", None), dict):
                        self.generation_kwargs = {}

                _GC.__init__ = _patched_gc_init
                _GC.generation_kwargs = {}
                logger.info("[Higgs] Patched GenerationConfig.generation_kwargs for boson_multimodal")
        except Exception as e:
            logger.warning(f"[Higgs] Could not patch GenerationConfig.generation_kwargs: {e}")
