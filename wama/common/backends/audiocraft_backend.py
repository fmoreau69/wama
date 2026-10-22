"""
AudioCraft Backend — MusicGen + AudioGen

Handles music and SFX generation via Meta's AudioCraft library.

AGENTS.md rule: HF_HUB_CACHE is set BEFORE any audiocraft/transformers import.
"""

import gc
import io
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.music_generation_base import MusicGenerationBackend

logger = logging.getLogger(__name__)

#: Pas de calcul entre deux aperçus « pendant » : le modèle de langue d'AudioCraft en fait 50 par
#: seconde de son (`frame_rate`) — ~2 s d'audio produit. C'est le PREMIER aperçu, et la cadence
#: d'un rappel qui n'en déclare pas ; un récepteur à cadence (`PartialFrames.audio_sink`) est
#: interrogé (`due()`) AVANT le décodage, comme `ImageGenerationBackend.preview_step`.
PARTIAL_EVERY_STEPS = 100


def _follow_tokens(model, progress_callback, on_audio) -> None:
    """Suit la génération PAS À PAS (2026-10-20, Fabien : « dans Composer, la preview est censée
    se charger au fur et à mesure de l'avancement de la génération ») :
      • la progression réelle, de 40 à 80 %, par le rappel qu'AudioCraft offre
        (`set_custom_progress_callback`) — elle sautait de 40 à 80 d'un coup ;
      • l'audio déjà produit, rendu à `on_audio` quand son récepteur le demande (`due()`), sinon
        tous les `PARTIAL_EVERY_STEPS` pas.

    AudioCraft ne rend que des COMPTES à son rappel : les jetons sont relevés à leur sortie de
    l'échantillonneur (`_sample_next_token`, enveloppé sur CETTE instance — rien n'est patché dans
    la librairie), puis replacés dans l'ordre des pas de temps par le motif du modèle lui-même
    (`pattern.revert_pattern_sequence`, ce que fait `lm.generate` à la fin) et décodés par son
    codec (`compression_model.decode`, ce que fait `generate_audio`). Au-delà de `max_duration`,
    AudioCraft enchaîne des fenêtres qui reprennent un préfixe : progression seule.
    Ne lève jamais : un aperçu raté n'arrête pas la génération."""
    lm = model.lm
    steps = []
    stream = bool(on_audio) and model.duration <= model.max_duration
    due = getattr(on_audio, 'due', None)
    if stream:
        sample = lm._sample_next_token

        def _spy(*args, **kwargs):
            token = sample(*args, **kwargs)
            steps.append(token)
            return token
        lm._sample_next_token = _spy

    def _progress(generated, total):
        if progress_callback and total:
            progress_callback(40 + int(40 * min(generated, total) / total))
        if not stream or generated < PARTIAL_EVERY_STEPS:
            return
        if due() if due else generated % PARTIAL_EVERY_STEPS == 0:
            audio = _partial_audio(model, steps)
            if audio is not None:
                try:
                    on_audio(audio, model.sample_rate)
                except Exception:
                    logger.debug("[Composer] aperçu partiel non publié", exc_info=True)

    model.set_custom_progress_callback(_progress)


def _partial_audio(model, steps):
    """L'audio des pas de temps COMPLETS déjà échantillonnés (un pas porte chaque codebook avec
    son retard), en `(échantillons,)` ou `(échantillons, canaux)` ; None s'il n'y en a pas encore."""
    try:
        import torch
        lm = model.lm
        provider = lm.pattern_provider
        start = provider.get_pattern(1).get_first_step_with_timesteps(0)
        timesteps = start + len(steps) - len(provider.get_pattern(0).layout)
        if not steps or timesteps <= 0:
            return None
        first = steps[0]
        head = torch.full((first.shape[0], first.shape[1], start), lm.special_token_id,
                          dtype=first.dtype, device=first.device)
        sequence = torch.cat([head] + list(steps), dim=-1)
        codes, _, _ = provider.get_pattern(timesteps).revert_pattern_sequence(sequence, special_token=-1)
        codes = codes[..., :timesteps]
        if (codes < 0).any() or (codes >= lm.card).any():
            return None
        with torch.no_grad():
            wav = model.compression_model.decode(codes, None)
        audio = wav[0].float().cpu().numpy()
        return audio.T if audio.ndim == 2 else audio
    except Exception:
        logger.debug("[Composer] audio partiel indécodable", exc_info=True)
        return None


class AudioCraftBackend(MusicGenerationBackend):
    """
    Unified backend for MusicGen (music) and AudioGen (SFX).

    Each call to generate() sets HF_HUB_CACHE, loads the model, runs
    inference, unloads the model, and returns the output path.
    Models are NOT cached in memory between calls — the 4090 has 24GB
    but other apps share it; we load/unload like every other WAMA backend.

    SANS état persistant (chargement par appel) → load() réchauffe, unload() no-op.
    """

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'audiocraft'
    REQUIRED_PACKAGES = ['audiocraft']
    recommended_vram_gb = 8.0
    description = "AudioCraft — MusicGen (musique) + AudioGen (bruitages)."
    #: Il TIRE ses jetons audio : 1,0, le défaut de `set_generation_params` d'AudioCraft (MusicGen
    #: comme AudioGen). Réglable depuis la card (2026-10-21).
    default_temperature = 1.0
    #: La graine se pose sur torch avant le tirage (2026-10-22). Pas de top_p : AudioCraft tire
    #: par `top_k=250` et `top_p=0` (« 0 = top_k ») — régler l'un changerait de stratégie.
    reads_seed = True
    default_top_p = None
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            import audiocraft  # noqa: F401
            return True
        except Exception:
            return False

    def load(self, model: Optional[str] = None) -> bool:
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    def generate(
        self,
        model_id: str,
        prompt: str,
        duration: float,
        output_path: str,
        melody_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        on_audio: Optional[Callable] = None,
        score_path: Optional[str] = None,
        sampling: Optional[dict] = None,
    ) -> str:
        """
        Generate audio and save to output_path.

        Args:
            model_id: One of 'musicgen-small', 'musicgen-medium', 'musicgen-melody',
                      'audiogen-medium'
            prompt: Text description of the sound/music to generate
            duration: Duration in seconds (max 30)
            output_path: Absolute path where the .wav will be saved
            melody_path: Optional path to a melody reference audio (musicgen-melody only)
            progress_callback: Optional callable(percent: int)

        Returns:
            output_path (same as input, for convenience)
        """
        self.refuse_score(score_path, 'AudioCraft')
        # Passe-plat COMMUN : le backend lit la déclaration sans importer l'app.
        # Le jour où il rejoint le substrat, cette ligne ne change pas — c'est
        # tout l'objet de l'étape 2.
        from wama.common.utils.model_declarations import declaration

        config = declaration('composer', model_id)
        if config is None:
            raise ValueError(f"Modèle inconnu : {model_id}")

        cache_dir = str(config['cache_dir'])
        audiocraft_name = config['audiocraft_name']
        sample_rate = config['sample_rate']
        model_type = config['type']

        # ── AGENTS.md: env vars BEFORE any audiocraft import ──────────────
        # ROADMAP §5b (2026-09-04) — audiocraft n'accepte pas `cache_dir=` sur
        # `MusicGen.get_pretrained`, MAIS il expose SA PROPRE variable : `loaders.py:36`
        # (`get_audiocraft_cache_dir`) la lit, et `_get_state_dict` la passe à
        # `hf_hub_download(cache_dir=…)`. On route donc audiocraft par SA variable au lieu
        # des variables HF GLOBALES.
        # ⚠ La différence n'est pas cosmétique : `HF_HUB_CACHE` est lue par TOUT consommateur
        # du hub dans le processus — elle emportait les sous-dépendances (t5-base, t5-large :
        # les résidus encore visibles dans `music/musicgen` et `music/audiogen`). Celle-ci
        # n'oriente qu'audiocraft.
        os.environ['AUDIOCRAFT_CACHE_DIR'] = cache_dir

        # ── torch 2.9.x / xformers 0.0.35 compat ─────────────────────────
        # GroupName was removed from torch.distributed.distributed_c10d in
        # torch 2.9.x.  xformers uses it as a type annotation only (no runtime
        # logic), so injecting str as a stand-in is safe.  Must happen before
        # any xformers import (triggered by audiocraft.modules.transformer).
        import torch.distributed.distributed_c10d as _c10d
        if not hasattr(_c10d, 'GroupName'):
            _c10d.GroupName = str  # type: ignore[attr-defined]
        # ──────────────────────────────────────────────────────────────────

        logger.info(f"[Composer] Loading {model_id} (cache: {cache_dir})")

        if progress_callback:
            progress_callback(5)

        # La card, sinon la sienne (`sampling_temperature`, le contrat commun) ; sa graine posée.
        options = {'options': sampling or {}}
        temperature = self.sampling_temperature(options)
        self.sampling_seed(options)
        try:
            if model_type == 'music':
                wav = self._generate_music(
                    audiocraft_name, prompt, duration, melody_path,
                    progress_callback, on_audio, temperature=temperature,
                )
            else:
                wav = self._generate_sfx(
                    audiocraft_name, prompt, duration, progress_callback, on_audio,
                    temperature=temperature,
                )

            if progress_callback:
                progress_callback(85)

            # Save to WAV — use soundfile directly to avoid torchcodec/FFmpeg
            # dependency (torchaudio >= 2.5 routes .save() through torchcodec
            # which requires system FFmpeg shared libraries).
            import soundfile as sf
            import numpy as np
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            audio_np = wav.cpu().numpy()
            if audio_np.ndim == 2:
                audio_np = audio_np.T  # (channels, samples) → (samples, channels)
            sf.write(output_path, audio_np, sample_rate, subtype='PCM_16')
            logger.info(f"[Composer] Saved to {output_path}")

            # L'audio FINAL aussi, au même rappel que les partiels (`_follow_tokens`) — la cadence
            # est celle de l'appelant. N'interrompt JAMAIS la génération (try/except).
            if on_audio:
                try:
                    on_audio(audio_np, sample_rate)
                except Exception:
                    pass

            if progress_callback:
                progress_callback(100)

            return output_path

        finally:
            # Free GPU memory
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_music(
        self,
        audiocraft_name: str,
        prompt: str,
        duration: float,
        melody_path: Optional[str],
        progress_callback: Optional[Callable],
        on_audio: Optional[Callable] = None,
        temperature: float = 1.0,
    ):
        """Load MusicGen, generate, unload."""
        from audiocraft.models import MusicGen

        if progress_callback:
            progress_callback(15)

        model = MusicGen.get_pretrained(audiocraft_name)
        model.set_generation_params(duration=duration, temperature=temperature)

        if progress_callback:
            progress_callback(40)
        _follow_tokens(model, progress_callback, on_audio)

        if melody_path and audiocraft_name == 'melody':
            import torch
            import torchaudio
            melody, sr = torchaudio.load(melody_path)
            # MusicGen expects (batch, channels, time) or None
            melody = melody.unsqueeze(0)  # (1, C, T)
            # Prompt vide → description None : conditionnement par la SEULE mélodie
            # (audiocraft accepte des entrées None dans descriptions).
            wav = model.generate_with_chroma([prompt or None], melody, sr, progress=True)
        elif prompt:
            wav = model.generate([prompt], progress=True)
        else:
            # Prompt VIDE = génération ALÉATOIRE (inconditionnelle) — annoncé dans l'UI
            # (placeholder de la card d'entrée). Cf. INPUT_MODEL_MATCHING.md.
            wav = model.generate_unconditional(1, progress=True)

        if progress_callback:
            progress_callback(80)

        # wav shape: (batch, channels, samples) — take first sample
        result = wav[0]  # (channels, samples)

        # Unload model from GPU
        del model
        return result

    def _generate_sfx(
        self,
        audiocraft_name: str,
        prompt: str,
        duration: float,
        progress_callback: Optional[Callable],
        on_audio: Optional[Callable] = None,
        temperature: float = 1.0,
    ):
        """Load AudioGen, generate, unload."""
        from audiocraft.models import AudioGen

        if progress_callback:
            progress_callback(15)

        model = AudioGen.get_pretrained(audiocraft_name)
        model.set_generation_params(duration=duration, temperature=temperature)

        if progress_callback:
            progress_callback(40)
        _follow_tokens(model, progress_callback, on_audio)

        wav = model.generate([prompt], progress=True)

        if progress_callback:
            progress_callback(80)

        result = wav[0]  # (channels, samples)
        del model
        return result
