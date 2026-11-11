"""
Backend ACE-Step 1.5 — génération musicale text-to-music via le moteur vendorisé ace_step_1_5.

Poids : installés par la route WAMA sous le dossier du modèle, lus via
`component_paths(model_key, with_backbone=True)`. Le moteur est un clone vendorisé
(settings.BACKEND_VENDOR_DIR/ace_step_1_5/), importé par `import_vendored`.

Variantes (SUPPORTED_MODELS) :
- turbo (ACE-Step/Ace-Step1.5) : 8 pas, shift=3.0, guidance_scale=1.0
- SFT (ACE-Step/acestep-v15-sft) : 50 pas, shift=1.0, guidance_scale=7.0
- SFT XL (ACE-Step/acestep-v15-xl-sft) : 50 pas, shift=1.0, guidance_scale=7.0

Architecture : DiT + LM 5 Hz (Qwen3-1.7B, planificateur CoT) + VAE (AutoencoderOobleck)
+ encodeur texte (Qwen3-Embedding-0.6B). Les variantes SFT ne publient que leur DiT
et leur silence_latent ; VAE, encodeur et LM proviennent de la dorsale (backbone).

Limites :
- Durée 10 s à 600 s (bornée, annoncée dans le log).
- Pas de partition (score_path refusée via refuse_score).
- Mélodie de référence supportée (→ reference_audio).
- Turbo : guidance_scale imposé à 1.0 par le pipeline, shift=3.0.
- Pas d'aperçu partiel (on_audio non supporté par ce moteur).
- Écriture WAV via le module stdlib `wave` (pas de torchaudio/torchcodec).
"""

import gc
import logging
import wave
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.base import LoadPrecision
from wama.common.backends.music_generation_base import (
    MusicGenerationBackend, split_caption_lyrics)
from wama.common.utils.model_components import component_paths

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = {
    'ACE-Step/Ace-Step1.5': {
        'model_key': 'huggingface:ACE-Step/Ace-Step1.5',
        'inference_steps': 8,
        'shift': 3.0,
        'guidance_scale': 1.0,
    },
    'ACE-Step/acestep-v15-sft': {
        'model_key': 'huggingface:ACE-Step/acestep-v15-sft',
        'inference_steps': 50,
        'shift': 1.0,
        'guidance_scale': 7.0,
    },
    'ACE-Step/acestep-v15-xl-sft': {
        'model_key': 'huggingface:ACE-Step/acestep-v15-xl-sft',
        'inference_steps': 50,
        'shift': 1.0,
        'guidance_scale': 7.0,
    },
}


def _make_progress_adapter(progress_callback: Optional[Callable[[int], None]]):
    """
    Adapte le rappel de progression du MOTEUR au contrat WAMA.

    Le moteur appelle avec :
      - progress(0.1, 'Phase 1: Generating CoT metadata...')   → (float, str)
      - progress(0.51, desc='Preparing inputs...')              → (float, desc=str)

    Le contrat WAMA attend : progress_callback(pct: int)  où pct ∈ [0, 100].
    """
    if progress_callback is None:
        return None

    def _adapter(*args, **kwargs):
        pct = 0
        if args and isinstance(args[0], (int, float)):
            pct = int(args[0] * 100)
        pct = max(0, min(100, pct))
        try:
            progress_callback(pct)
        except Exception:
            logger.debug("[ACE-Step] rappel de progression ignoré", exc_info=True)

    return _adapter


def _save_wav(tensor, sample_rate: int, out_path: Path) -> None:
    """
    Écrit un tenseur audio [channels, samples] (float32, CPU) en WAV 16-bit
    via le module stdlib `wave` — sans torchaudio ni torchcodec.
    """
    import numpy as np

    audio_np = tensor.detach().cpu().numpy()  # [channels, samples]
    # Conversion float32 → int16
    audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)

    if audio_int16.ndim == 1:
        audio_int16 = audio_int16.reshape(1, -1)

    n_channels = audio_int16.shape[0]
    # Le module wave attend les échantillons en [samples, channels] pour multi-canaux
    if n_channels > 1:
        audio_int16 = audio_int16.T  # → [samples, channels]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), 'wb') as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())


class AceStepBackend(MusicGenerationBackend):
    """
    Génération musicale ACE-Step 1.5 (turbo) — moteur vendorisé ace_step_1_5.

    Charge le DiT, la VAE, l'encodeur texte et le LM 5 Hz depuis les poids installés,
    puis délègue la génération à `generate_music` du moteur.
    """

    ENGINE = 'ace_step_1_5'
    VENDORED = True
    REQUIRED_PACKAGES = ['torch', 'transformers', 'diffusers', 'numpy']
    recommended_vram_gb = 12.1
    description = "ACE-Step 1.5 — text-to-music (DiT + LM 5 Hz + VAE) ; turbo < 10 s sur GPU, SFT ~50 pas."
    #: Le LM tire ses jetons : température 0.85 (défaut du moteur).
    default_temperature = 0.85
    #: La graine se pose sur GenerationParams.seed.
    reads_seed = True
    #: top_p transmis au LM (défaut 0.9).
    default_top_p = 0.9

    @classmethod
    def load_precisions(cls, model_id: str) -> tuple:
        # Le moteur charge le DiT en BF16 sur CUDA (init_service_loader.py:179,
        # `dtype=self.dtype`), alors que la XL-SFT publie ses poids en F32.
        # On déclare cette précision pour que le gouverneur calcule la VRAM
        # réelle (~14 Go) au lieu de la taille des fichiers (~18,6 Go).
        if model_id not in SUPPORTED_MODELS:
            return ()
        return (LoadPrecision('BF16', quantized=('diffusion_transformer',)),)

    def __init__(self):
        self._dit_handler = None
        self._llm_handler = None
        self._loaded = False
        self._loaded_model = None
        self._device = 'cpu'

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Vérifie que les paquets lourds s'importent (pas de chargement de modèle)."""
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            import diffusers  # noqa: F401
            import numpy  # noqa: F401
            return True
        except ImportError:
            return False

    def load(self, model: Optional[str] = None) -> bool:
        """Charge DiT + VAE + encodeur texte + LM 5 Hz depuis les poids installés.

        `model` : clé de `SUPPORTED_MODELS` (défaut : la turbo). Si une autre
        variante est déjà chargée, elle est déchargée avant le rechargement.
        """
        if model is not None and model not in SUPPORTED_MODELS:
            raise ValueError(
                f"[ACE-Step] modèle inconnu : {model!r} — variantes disponibles : "
                f"{', '.join(SUPPORTED_MODELS)}")

        model = model or 'ACE-Step/Ace-Step1.5'

        # Si une autre variante est chargée, décharger d'abord.
        if self._loaded and self._loaded_model != model:
            self.unload()

        if self._loaded:
            return True

        import torch

        model_key = SUPPORTED_MODELS[model]['model_key']
        paths = component_paths(model_key, with_backbone=True)
        root = paths['vae'].parent.parent

        # Périphérique
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._device = device

        # Dtype selon le matériel
        gpu_config = self.import_vendored('acestep.gpu_config')
        if device == 'cuda' and gpu_config.is_rocm_available():
            dtype = torch.float32  # sûr par défaut sur ROCm
        elif device == 'cuda':
            dtype = torch.bfloat16 if gpu_config.cuda_supports_bfloat16() else torch.float16
        else:
            dtype = torch.float32

        # ── DiT + VAE + encodeur texte (AceStepHandler) ──────────────────────
        handler_mod = self.import_vendored('acestep.handler')
        dit_handler = handler_mod.AceStepHandler()

        # Configuration runtime (pas de compile, pas de quantization)
        normalized_compile, normalized_quant, mlx_compile = (
            dit_handler._configure_initialize_runtime(
                device=device, compile_model=False, quantization=None))

        dit_handler.device = device
        dit_handler.dtype = dtype
        dit_handler.compiled = normalized_compile
        dit_handler.quantization = normalized_quant
        dit_handler.offload_to_cpu = False
        dit_handler.offload_dit_to_cpu = False

        # DiT : le dossier contient model.safetensors + silence_latent.pt + config.json
        dit_dir = str(paths['diffusion_transformer'].parent)
        dit_handler._load_main_model_from_checkpoint(
            model_checkpoint_path=dit_dir,
            device=device,
            use_flash_attention=False,
            compile_model=False,
            quantization=None,
        )

        # VAE : le dossier racine (dorsale) contient vae/
        dit_handler._load_vae_model(
            checkpoint_dir=str(root),
            device=device,
            compile_model=False,
        )

        # Encodeur texte : le dossier racine (dorsale) contient Qwen3-Embedding-0.6B/
        dit_handler._load_text_encoder_and_tokenizer(
            checkpoint_dir=str(root),
            device=device,
        )

        # MLX backends (inactifs sur CUDA / CPU standard)
        dit_handler._initialize_mlx_backends(
            device=device,
            use_mlx_dit=False,
            mlx_compile_requested=False,
        )

        self._dit_handler = dit_handler

        # ── LM 5 Hz (LLMHandler) ─────────────────────────────────────────────
        llm_mod = self.import_vendored('acestep.llm_inference')
        llm_handler = llm_mod.LLMHandler()
        llm_handler.initialize(
            checkpoint_dir=str(root),
            lm_model_path=paths['language_model'].parent.name,
            backend='transformers',
            device=device,
        )
        self._llm_handler = llm_handler

        self._loaded = True
        self._loaded_model = model
        logger.info("[ACE-Step] Modèle %s chargé sur %s (dtype=%s)", model, device, dtype)
        return True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        """Décharge le modèle et restaure la fraction VRAM plafonnée par le moteur."""
        if not self._loaded:
            return
        self._dit_handler = None
        self._llm_handler = None
        self._loaded = False
        self._loaded_model = None
        gc.collect()
        # Le moteur plafonne la VRAM du processus — la rendre.
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(1.0)
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[ACE-Step] Modèle déchargé.")

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------

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
        """Génère un morceau et l'écrit dans `output_path` (WAV 16-bit)."""
        self.load(model_id)

        # Partition : non supportée par ce moteur → refus explicite.
        self.refuse_score(score_path, self.ENGINE)

        # Aperçu partiel : non supporté par ACE-Step (génération en bloc).
        if on_audio:
            logger.info("[ACE-Step] on_audio ignoré — ce moteur ne produit pas d'aperçu partiel.")

        # Découpe prompt → (caption, lyrics)
        caption, lyrics = split_caption_lyrics(prompt)

        # Durée : bornée 10–600 s
        if duration < 10:
            logger.warning("[ACE-Step] durée %.1f s < 10 s — bornée à 10 s", duration)
            duration = 10.0
        elif duration > 600:
            logger.warning("[ACE-Step] durée %.1f s > 600 s — bornée à 600 s", duration)
            duration = 600.0

        # Paramètres de tirage — aides communes de la classe de base
        options = {'options': sampling or {}}
        temperature = self.sampling_temperature(options)
        seed = self.sampling_seed(options)
        if seed is None:
            seed = -1  # le moteur attend -1 pour « graine aléatoire »
        top_p = self.sampling_top_p(options)

        # Mélodie de référence → reference_audio (supportée par ACE-Step)
        reference_audio = melody_path

        # ── Construction des paramètres du moteur ────────────────────────────
        inference_mod = self.import_vendored('acestep.inference')
        GenerationParams = inference_mod.GenerationParams
        GenerationConfig = inference_mod.GenerationConfig
        generate_music = inference_mod.generate_music

        # Réglages de la variante réellement chargée
        variant = SUPPORTED_MODELS[self._loaded_model]

        params = GenerationParams(
            task_type="text2music",
            caption=caption,
            lyrics=lyrics,
            instrumental=(lyrics == '[instrumental]'),
            duration=duration,
            reference_audio=reference_audio,
            inference_steps=variant['inference_steps'],
            seed=seed,
            shift=variant['shift'],
            guidance_scale=variant['guidance_scale'],
            lm_temperature=temperature,
            lm_top_p=top_p,
            thinking=True,
            use_cot_metas=True,
            use_cot_caption=False,
            use_cot_lyrics=False,
            use_cot_language=True,
            use_constrained_decoding=True,
        )

        config = GenerationConfig(
            batch_size=1,
            audio_format="wav",
        )

        # ── Génération ───────────────────────────────────────────────────────
        if progress_callback:
            progress_callback(5)

        # Adapter le rappel du moteur (float 0-1, texte optionnel) au contrat WAMA (int 0-100)
        engine_progress = _make_progress_adapter(progress_callback)

        result = generate_music(
            self._dit_handler,
            self._llm_handler,
            params,
            config,
            save_dir=None,
            progress=engine_progress,
        )

        if not result.success:
            raise RuntimeError(f"ACE-Step : échec de la génération — {result.error}")

        # ── Écriture de l'audio (WAV 16-bit, stdlib `wave`) ─────────────────
        audio_entry = result.audios[0]
        tensor = audio_entry['tensor']  # [channels, samples], CPU, float32
        sample_rate = audio_entry.get('sample_rate', 48000)

        out_path = Path(output_path)
        _save_wav(tensor, sample_rate, out_path)

        if progress_callback:
            progress_callback(100)

        logger.info("[ACE-Step] Audio écrit dans %s (%d Hz, %d échantillons)",
                    output_path, sample_rate, tensor.shape[-1])
        return str(output_path)
