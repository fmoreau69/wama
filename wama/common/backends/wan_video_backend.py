"""
WAMA Imager - Wan Video Backend

Video generation using Wan 2.2 models via Hugging Face Diffusers.
Supports Text-to-Video and Image-to-Video generation.

Poids : `AI-models/models/diffusion/wan/` pour les Wan 2.2 officiels ; un modèle de la famille
qui a son propre dossier le déclare dans `MODEL_PROFILES` (`paths_key` de `settings.MODEL_PATHS`).

FastWan 2.2 TI2V 5B (2026-09-15) : son dépôt déclare `WanDMDPipeline` (paquet `fastvideo`, dont
l'installation est REFUSÉE par le verrou du venv), mais tous ses composants sont standard et
`WanPipeline` prend exactement les clés de son `model_index.json` (sonde à blanc du 2026-09-14,
`manage.py probe_fastwan`). Il est donc servi ici par `WanPipeline` + un scheduler DMD à 3 pas.
⚠ Le pas DMD est une HYPOTHÈSE tant que la première génération GPU ne l'a pas validé.
"""

import gc
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, List

from django.conf import settings

# 🔴 NE MUTE PLUS L'ENVIRONNEMENT (2026-09-03, `ROADMAP §5b`). Cette fonction posait
# `HF_HUB_CACHE` sur le dossier Wan, **au niveau module** : importer ce fichier suffisait à
# rediriger le cache HF de TOUT le processus, et le dernier module importé gagnait. C'est la
# « course » qui justifie le `--workers 1` du service TTS (`start_wama_prod.sh:271`), et c'est
# ce qui a fait échouer le test de socle dans la suite du 03/09 (`HF_HUB_CACHE` → `diffusion/wan`).
#
# Elle ne fait plus que RÉSOUDRE le dossier — le rangement du modèle principal est assuré par
# `cache_dir=`, passé aux 3 `from_pretrained` de ce fichier (VAE, T2V, I2V : vérifiés un par un).
# Le socle `HF_HOME`/`HF_HUB_CACHE` est posé UNE FOIS au démarrage (`settings.py:165-167`).
def _resoudre_dossier_wan():
    """Dossier des poids Wan. NE TOUCHE PAS à l'environnement — voir le bloc ci-dessus."""
    try:
        from django.conf import settings as _s
        wan_dir = _s.AI_MODELS_DIR / "models" / "diffusion" / "wan"
    except Exception:
        # Repli : `settings` indisponible (script hors Django).
        wan_dir = Path(settings.BASE_DIR) / "AI-models" / "models" / "diffusion" / "wan"
    wan_dir.mkdir(parents=True, exist_ok=True)
    return str(wan_dir)


_WAN_MODELS_DIR = _resoudre_dossier_wan()

from .image_generation_base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)

# Log the cache location at module load
logger.info(f"[Wan] Module loaded - HF cache directory: {_WAN_MODELS_DIR}")
logger.info(f"[Wan] Environment: HF_HUB_CACHE={os.environ.get('HF_HUB_CACHE', 'not set')}")


def get_wan_models_dir() -> str:
    """Get the directory for Wan video models.

    Returns the path as a string for compatibility with Hugging Face.
    Environment variables are set at module load time via _setup_hf_cache().
    """
    return _WAN_MODELS_DIR


@dataclass
class VideoGenerationParams:
    """Parameters for video generation."""
    prompt: str
    negative_prompt: Optional[str] = None
    model: str = "wan-ti2v-5b"
    width: int = 832
    height: int = 480
    num_frames: int = 81  # Should be 4k+1 (e.g., 81 = 4*20+1)
    fps: int = 16
    guidance_scale: float = 5.0
    num_inference_steps: int = 50
    seed: Optional[int] = None

    # Generation mode
    generation_mode: str = "txt2vid"  # txt2vid or img2vid
    reference_image: Optional[str] = None  # Path to reference image for img2vid


@dataclass
class VideoGenerationResult:
    """Result of video generation."""
    success: bool
    video_frames: List  # List of numpy arrays or PIL images
    video_path: Optional[str] = None  # Path to exported MP4
    seed_used: Optional[int] = None
    error: Optional[str] = None


#: Pas de débruitage DMD de FastWan 2.2 (README du dépôt : `--dmd-denoising-steps "1000,757,522"`).
FASTWAN_DMD_TIMESTEPS = (1000, 757, 522)


def dmd_step(velocity, sample, timestep, next_timestep, noise=None):
    """UN pas DMD sur une prédiction de flux.

    ⚠ HYPOTHÈSE À VALIDER AU GPU : sigma = t / 1000 (flow matching), prédiction v = bruit − x0,
    donc x0 = x_t − sigma·v ; au pas suivant x = (1 − sigma')·x0 + sigma'·bruit NEUF. Sans CFG
    (modèle distillé). Cohérence vérifiée sur CPU par `manage.py probe_fastwan` (2026-09-14).
    """
    sigma = float(timestep) / 1000.0
    x0 = sample - sigma * velocity.to(sample.dtype)
    if next_timestep is None:
        return x0
    next_sigma = float(next_timestep) / 1000.0
    return (1.0 - next_sigma) * x0 + next_sigma * noise


def make_dmd_scheduler(timesteps=FASTWAN_DMD_TIMESTEPS, generator=None):
    """Scheduler minimal pour la boucle de `WanPipeline`.

    Elle n'emploie du scheduler que `set_timesteps`, `timesteps`, `order`,
    `config.num_train_timesteps` et `step(..., return_dict=False)[0]` (lu dans diffusers 0.37).
    `generator` sert au re-bruitage entre deux pas ; il se REPOSE à chaque génération
    (`scheduler.generator = …`) pour que la graine de l'utilisateur gouverne tout le tirage.
    """
    import torch
    from diffusers import FlowMatchEulerDiscreteScheduler

    steps = tuple(int(t) for t in timesteps)

    class DMDScheduler(FlowMatchEulerDiscreteScheduler):
        order = 1

        def set_timesteps(self, num_inference_steps=None, device=None, **kwargs):
            self.timesteps = torch.tensor(steps, dtype=torch.float32, device=device)

        def step(self, model_output, timestep, sample, return_dict=True, **kwargs):
            t = float(timestep)
            i = min(range(len(steps)), key=lambda k: abs(steps[k] - t))
            next_t = steps[i + 1] if i + 1 < len(steps) else None
            noise = None
            if next_t is not None:
                noise = torch.randn(sample.shape, generator=self.generator,
                                    dtype=sample.dtype).to(sample.device)
            x = dmd_step(model_output, sample, t, next_t, noise)
            return (x,) if not return_dict else type('SchedulerOutput', (), {'prev_sample': x})()

    scheduler = DMDScheduler()
    scheduler.generator = generator
    return scheduler


class WanVideoBackend(ImageGenerationBackend):
    """
    Video generation backend using Wan 2.2 models.

    This backend supports:
    - Image-to-Video (img2vid) using Wan2.2-TI2V-5B
    - Text-to-Video (txt2vid) using Wan2.2-T2V-14B
    - Image-to-Video (img2vid) using Wan2.2-I2V-14B

    VRAM Requirements:
    - wan-ti2v-5b: ~24GB VRAM (supports both txt2vid and img2vid)
    - wan-t2v-14b: ~24GB VRAM (txt2vid only)
    - wan-i2v-14b: ~24GB VRAM (img2vid only)
    """

    # Dépendances DÉCLARATIVES (contrat commun : missing_packages/is_available dérivés).
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'diffusers'
    #: Classe de PARAMÈTRES déclarée par le backend (2026-09-07) — lue sur la classe RÉSOLUE.
    PARAMS = VideoGenerationParams
    # `DEPRECATED` RETIRÉ le 2026-09-15 : il disait « aucun modèle installé » — ce backend sert
    # désormais FastWan 2.2 (23 Go sur disque, déclaré par l'imager). Les trois Wan 2.2
    # officiels restent déclarés sans poids (partis du disque en 2026-01).
    REQUIRED_PACKAGES = ['torch', 'diffusers', 'numpy']
    name = "wan_video"
    display_name = "Wan Video (Hugging Face)"

    # Map model names to Hugging Face model IDs
    SUPPORTED_MODELS = {
        "wan-ti2v-5b": (
            "Wan 2.2 TI2V 5B (~8GB)",
            "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
        ),
        "wan-t2v-14b": (
            "Wan 2.2 T2V 14B (~24GB)",
            "Wan-AI/Wan2.2-T2V-A14B-Diffusers"
        ),
        "wan-i2v-14b": (
            "Wan 2.2 I2V 14B (~24GB)",
            "Wan-AI/Wan2.2-I2V-A14B-Diffusers"
        ),
        "fastwan-2.2-ti2v-5b": (
            "FastWan 2.2 TI2V 5B — DMD 3 pas (~23GB de poids)",
            "FastVideo/FastWan2.2-TI2V-5B-FullAttn-Diffusers"
        ),
    }

    #: Ce qui distingue un modèle de la famille au chargement et à la génération. Un modèle
    #: absent garde le comportement Wan 2.2 d'origine (dossier `diffusion/wan`, preset
    #: `wan-t2v`, pas et guidage de la génération).
    MODEL_PROFILES = {
        "fastwan-2.2-ti2v-5b": {
            # dossier des poids : clé de `settings.MODEL_PATHS['diffusion']`
            "paths_key": "fastwan",
            # preset de `MODEL_SIZE_PRESETS` qui choisit la stratégie mémoire
            "memory_preset": "fastwan",
            # distillé DMD : pas imposés, sans CFG (guidage 1,0 = CFG désactivé dans WanPipeline)
            "dmd_timesteps": FASTWAN_DMD_TIMESTEPS,
            "guidance_scale": 1.0,
            # image→vidéo par le MÊME dépôt (TI2V) : `expand_timesteps=True` au model_index,
            # donc conditionnement par la première image encodée au VAE — aucun encodeur
            # d'image requis (composant optionnel du pipeline). Mesuré le 2026-09-16.
            "img2vid": True,
        },
    }

    @classmethod
    def cache_dir_for(cls, model_name: str) -> str:
        """Dossier des poids de `model_name` : celui de son profil, sinon `diffusion/wan`."""
        key = (cls.MODEL_PROFILES.get(model_name) or {}).get("paths_key")
        if key:
            path = (getattr(settings, 'MODEL_PATHS', {}).get('diffusion') or {}).get(key)
            if path:
                return str(path)
        return get_wan_models_dir()

    # Resolution presets
    RESOLUTION_PRESETS = {
        "480p": (832, 480),
        "720p": (1280, 720),
    }

    # Default negative prompt for video generation
    DEFAULT_NEGATIVE_PROMPT = (
        "Bright tones, overexposed, static, blurred details, subtitles, "
        "style, works, paintings, images, static, overall gray, worst quality, "
        "low quality, JPEG compression residue, ugly, incomplete, extra fingers, "
        "poorly drawn hands, poorly drawn faces, deformed, disfigured, "
        "misshapen limbs, fused fingers, still picture, messy background, "
        "three legs, many people in the background, walking backwards"
    )

    def __init__(self):
        super().__init__()
        self._pipe_t2v = None
        self._pipe_i2v = None
        self._current_model = None
        self._torch = None
        self._vae = None
        # Poids PARTAGÉS entre texte→vidéo et image→vidéo (`from_pipe`, TI2V) : les crochets de
        # déchargement ne peuvent appartenir qu'à UN pipeline à la fois — `_hooks_owner` dit
        # lequel ; l'autre les repose avant de servir (`_rehook`).
        self._shared_components = False
        self._hooks_owner = None

    def _rehook(self, which: str, model_name: str) -> None:
        """Repose la stratégie mémoire sur le pipeline `which` ('t2v'|'i2v') s'il partage ses
        modules avec l'autre et que ce n'est pas lui qui porte les crochets. Sans cela, le
        pipeline qui a perdu ses crochets tournerait sur CPU (modules jamais remontés)."""
        if not self._shared_components or self._hooks_owner == which:
            self._hooks_owner = which
            return
        pipe = self._pipe_t2v if which == 't2v' else self._pipe_i2v
        if pipe is None:
            return
        profile = self.MODEL_PROFILES.get(model_name) or {}
        from wama.model_manager.services.memory_manager import MemoryManager
        MemoryManager.apply_strategy_for_model(
            pipeline=pipe, model_type=profile.get("memory_preset", "wan-t2v"),
            device=self._device, headroom_gb=4.0)
        self._hooks_owner = which
        logger.info(f"[Wan] Crochets de déchargement reposés sur le pipeline {which}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if Wan video generation is available."""
        try:
            import torch
            import diffusers
            logger.debug(f"[Wan] Checking availability - torch: {torch.__version__}, diffusers: {diffusers.__version__}")
            from diffusers import WanPipeline
            logger.info("[Wan] Backend available - WanPipeline found")
            return True
        except ImportError as e:
            logger.warning(f"[Wan] Backend not available: {e}")
            return False

    def _get_device(self) -> str:
        """Determine the best device to use."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            device_name = self._torch.cuda.get_device_name(0)
            logger.info(f"[Wan] CUDA device detected: {device_name}")
            return "cuda"
        elif hasattr(self._torch.backends, 'mps') and self._torch.backends.mps.is_available():
            logger.info("[Wan] MPS device detected (Apple Silicon)")
            return "mps"
        else:
            logger.warning("[Wan] No GPU detected, using CPU (very slow)")
            return "cpu"

    def _get_vram_gb(self) -> float:
        """Get available VRAM in GB."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            props = self._torch.cuda.get_device_properties(0)
            total_vram = props.total_memory / (1024 ** 3)
            free_vram = (props.total_memory - self._torch.cuda.memory_allocated(0)) / (1024 ** 3)
            logger.info(f"[Wan] VRAM: {total_vram:.1f}GB total, {free_vram:.1f}GB free")
            return total_vram
        return 0

    def load(self, model_name: str = None) -> bool:
        """
        Load a Wan video generation model.

        Args:
            model_name: Model name (e.g., "wan-t2v-1.3b", "wan-ti2v-5b").

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = "wan-t2v-1.3b"

        logger.info(f"[Wan] Requested model: {model_name}")

        # Map to HuggingFace model ID
        model_id = self.map_model_name(model_name)
        logger.info(f"[Wan] Mapped to HuggingFace ID: {model_id}")

        # Check if already loaded
        if self._loaded and self._current_model == model_id:
            logger.info(f"[Wan] Model {model_id} already loaded, skipping")
            return True

        try:
            import torch
            logger.info(f"[Wan] PyTorch version: {torch.__version__}")
            logger.info(f"[Wan] CUDA available: {torch.cuda.is_available()}")

            from diffusers import AutoencoderKLWan, WanPipeline
            logger.info("[Wan] Diffusers imports successful")

            self._torch = torch
            self._device = self._get_device()

            # Dossier des poids et réglages propres au modèle (FastWan : dossier, preset, DMD)
            profile = self.MODEL_PROFILES.get(model_name) or {}
            cache_dir = self.cache_dir_for(model_name)
            logger.info(f"[Wan] ========================================")
            logger.info(f"[Wan] Models cache directory: {cache_dir}")
            logger.info(f"[Wan] Directory exists: {os.path.exists(cache_dir)}")
            logger.info(f"[Wan] HF_HUB_CACHE env: {os.environ.get('HF_HUB_CACHE', 'not set')}")
            logger.info(f"[Wan] ========================================")
            logger.info(f"[Wan] Starting model load: {model_id} on {self._device}")

            # Unload previous model if any
            if self._pipe_t2v is not None:
                logger.info("[Wan] Unloading previous model...")
                self.unload()

            # Determine VAE dtype based on VRAM
            # float32 = better quality but 2x memory (needs 32GB+ for safety)
            # bfloat16 = good quality, half memory (recommended for 24GB GPUs)
            vram_gb = self._get_vram_gb()
            if vram_gb >= 32:
                vae_dtype = torch.float32
                logger.info("[Wan] Loading VAE in float32 (best quality, sufficient VRAM)")
            else:
                vae_dtype = torch.bfloat16
                logger.info(f"[Wan] Loading VAE in bfloat16 ({vram_gb:.0f}GB VRAM - saves memory)")

            logger.info("[Wan] Loading VAE (AutoencoderKLWan)...")
            self._vae = AutoencoderKLWan.from_pretrained(
                model_id,
                subfolder="vae",
                torch_dtype=vae_dtype,
                cache_dir=cache_dir
            )
            logger.info(f"[Wan] VAE loaded successfully (dtype={vae_dtype})")

            # Load T2V pipeline
            logger.info("[Wan] Loading T2V pipeline (WanPipeline)... This may take several minutes on first run.")
            # Modèle distillé DMD : son scheduler REMPLACE celui que déclare le dépôt (UniPC).
            pipe_kwargs = {}
            if profile.get("dmd_timesteps"):
                pipe_kwargs["scheduler"] = make_dmd_scheduler(profile["dmd_timesteps"])
                logger.info(f"[Wan] Scheduler DMD : pas {list(profile['dmd_timesteps'])}")
            self._pipe_t2v = WanPipeline.from_pretrained(
                model_id,
                vae=self._vae,
                torch_dtype=torch.bfloat16,
                cache_dir=cache_dir,
                **pipe_kwargs
            )
            logger.info("[Wan] T2V pipeline loaded")

            # Move to device or enable offloading based on VRAM
            # Video generation (especially VAE decode) needs significant memory
            logger.info(f"[Wan] Detected VRAM: {vram_gb:.1f}GB")

            # Clear CUDA cache before loading to maximize available memory
            if self._device == "cuda":
                torch.cuda.empty_cache()
                gc.collect()

            # Use centralized MemoryManager for optimal memory strategy
            try:
                from wama.model_manager.services.memory_manager import MemoryManager
                self._pipe_t2v = MemoryManager.apply_strategy_for_model(
                    pipeline=self._pipe_t2v,
                    # ⚠ le preset du MODÈLE : FastWan (~23 Go) sous `wan-t2v` (14) tenterait FULL_GPU
                    model_type=profile.get("memory_preset", "wan-t2v"),
                    device=self._device,
                    headroom_gb=4.0  # Video generation needs more headroom
                )
            except ImportError:
                # Fallback: use original VRAM-based logic
                logger.warning("[Wan] MemoryManager not available, using built-in VRAM logic")
                if self._device == "cuda" and vram_gb >= 48:
                    self._pipe_t2v = self._pipe_t2v.to(self._device)
                elif self._device == "cuda" and vram_gb >= 32:
                    self._pipe_t2v.enable_model_cpu_offload()
                elif self._device == "cuda":
                    self._pipe_t2v.enable_sequential_cpu_offload()
                else:
                    self._pipe_t2v = self._pipe_t2v.to(self._device)

            # Enable memory optimizations regardless of offload mode — sur le VAE LUI-MÊME.
            # ⚠ `pipe.enable_vae_tiling()` n'existe que sur les pipelines d'image
            # (`StableDiffusionMixin`) : `WanPipeline` ne l'a pas, l'appel levait, et l'échec
            # partait en DEBUG. Mesuré le 2026-09-23 (génération #48, FastWan, 121 images en
            # 832×480) : 3 pas de débruitage en 2,5 min, puis 69 min de décodage VAE non tuilé
            # qui débordait de la VRAM. D'où un avertissement si le tuilage échoue.
            try:
                self._pipe_t2v.vae.enable_slicing()
                self._pipe_t2v.vae.enable_tiling()
                logger.info("[Wan] VAE slicing + tiling enabled (reduces memory during decode)")
            except Exception as e:
                logger.warning(f"[Wan] VAE tiling not available — décodage non tuilé : {e}")

            # Enable attention slicing to reduce memory during inference
            try:
                self._pipe_t2v.enable_attention_slicing("auto")
                logger.info("[Wan] Attention slicing enabled (reduces peak memory)")
            except Exception as e:
                logger.debug(f"[Wan] Attention slicing not available: {e}")

            self._current_model = model_id
            self._loaded = True
            self._shared_components = False
            self._hooks_owner = 't2v'
            logger.info(f"[Wan] ✓ Model {model_id} loaded successfully on {self._device}")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[Wan] ✗ Failed to load model {model_id}: {e}")
            logger.error(f"[Wan] Traceback:\n{traceback.format_exc()}")
            self._loaded = False
            return False

    @classmethod
    def i2v_model_id(cls, model_name: str) -> str:
        """Dépôt qui sert l'image→vidéo de `model_name`.

        Un modèle TI2V fait les deux métiers avec SON dépôt (FastWan : `expand_timesteps`).
        Les Wan 2.2 officiels ont un dépôt I2V dédié — c'est lui que servait la constante en
        dur qui vivait ici, et elle envoyait TOUT modèle vers un A14B absent du disque.
        """
        if (cls.MODEL_PROFILES.get(model_name) or {}).get("img2vid"):
            profile_model = cls.SUPPORTED_MODELS.get(model_name)
            if profile_model:
                return profile_model[1]
        return "Wan-AI/Wan2.2-I2V-A14B-Diffusers"

    def _load_i2v_pipeline(self, model_name: str = None) -> bool:
        """Load Image-to-Video pipeline if needed."""
        if self._pipe_i2v is not None:
            logger.info("[Wan I2V] Pipeline already loaded, skipping")
            return True

        try:
            import torch
            from diffusers import WanImageToVideoPipeline

            profile = self.MODEL_PROFILES.get(model_name) or {}
            model_id = self.i2v_model_id(model_name)
            cache_dir = self.cache_dir_for(model_name)
            logger.info(f"[Wan I2V] ========================================")
            logger.info(f"[Wan I2V] Models cache directory: {cache_dir}")
            logger.info(f"[Wan I2V] Directory exists: {os.path.exists(cache_dir)}")
            logger.info(f"[Wan I2V] HF_HUB_CACHE env: {os.environ.get('HF_HUB_CACHE', 'not set')}")
            logger.info(f"[Wan I2V] ========================================")
            logger.info(f"[Wan I2V] Starting I2V pipeline load from {model_id}")
            logger.info("[Wan I2V] This is a 14B parameter model, requires ~24GB+ VRAM")
            logger.info("[Wan I2V] First download may take 20-30 minutes (~25GB)")

            # Load pipeline directly (simpler approach, handles all components)
            logger.info("[Wan I2V] Loading WanImageToVideoPipeline... This may take several minutes.")
            pipe_kwargs = {}
            if profile.get("dmd_timesteps"):
                pipe_kwargs["scheduler"] = make_dmd_scheduler(profile["dmd_timesteps"])
                logger.info(f"[Wan I2V] Scheduler DMD : pas {list(profile['dmd_timesteps'])}")
            if (self._pipe_t2v is not None and self._current_model == model_id):
                # TI2V : les DEUX métiers sont servis par le MÊME dépôt (FastWan). Charger un
                # second pipeline depuis le disque doublait les ~23 Go de poids en RAM — c'est
                # ce que faisait tout image→vidéo, et ce que la prolongation par segments
                # (2026-09-23) aurait fait à chaque vidéo longue. `from_pipe` PARTAGE les
                # modules ; les crochets de déchargement se reposent ci-dessous, et le pipeline
                # texte→vidéo les reposera à son tour avant de resservir (`_rehook`).
                # 🔴 `torch_dtype=None` OBLIGATOIRE : le défaut de `from_pipe` est `float32`, et il
                # CONVERTIT EN PLACE les modules partagés (`new_pipeline.to(dtype=…)`, diffusers
                # 0.37 `pipeline_utils.py:2118/2214`) — les 23 Go bf16 passaient à 46 Go fp32.
                # Vécu le 2026-09-23 à 22:40 : OOM du worker GPU (46,9 Go anon), 1ʳᵉ vidéo 15 s.
                self._pipe_i2v = WanImageToVideoPipeline.from_pipe(
                    self._pipe_t2v, torch_dtype=None, **pipe_kwargs)
                self._shared_components = True
                logger.info("[Wan I2V] Pipeline dérivé du texte→vidéo (poids partagés)")
            else:
                self._pipe_i2v = WanImageToVideoPipeline.from_pretrained(
                    model_id,
                    torch_dtype=torch.bfloat16,
                    cache_dir=cache_dir,
                    **pipe_kwargs
                )
            logger.info("[Wan I2V] Pipeline loaded")

            # Use centralized MemoryManager for optimal memory strategy
            try:
                from wama.model_manager.services.memory_manager import MemoryManager
                self._pipe_i2v = MemoryManager.apply_strategy_for_model(
                    pipeline=self._pipe_i2v,
                    # ⚠ le preset du MODÈLE (cf. `load`) : le 5B distillé n'a pas l'empreinte
                    # du A14B, et l'inverse ferait tenter un plein GPU de ~23 Go.
                    model_type=profile.get("memory_preset", "wan-i2v"),
                    device=self._device,
                    headroom_gb=4.0  # I2V needs extra headroom for image processing
                )
            except ImportError:
                # Fallback: use original VRAM-based logic
                vram_gb = self._get_vram_gb()
                logger.warning("[Wan I2V] MemoryManager not available, using built-in VRAM logic")
                if self._device == "cuda" and vram_gb >= 32:
                    self._pipe_i2v = self._pipe_i2v.to(self._device)
                elif self._device == "cuda" and vram_gb >= 20:
                    self._pipe_i2v.enable_model_cpu_offload()
                elif self._device == "cuda":
                    self._pipe_i2v.enable_sequential_cpu_offload()
                else:
                    self._pipe_i2v = self._pipe_i2v.to(self._device)

            # Enable VAE tiling for I2V — sur le VAE lui-même (cf. le chargement T2V ci-dessus).
            try:
                self._pipe_i2v.vae.enable_slicing()
                self._pipe_i2v.vae.enable_tiling()
                logger.info("[Wan I2V] VAE slicing + tiling enabled")
            except Exception as e:
                logger.warning(f"[Wan I2V] VAE tiling not available — décodage non tuilé : {e}")

            self._hooks_owner = 'i2v'
            logger.info("[Wan I2V] ✓ I2V pipeline loaded successfully")
            return True

        except Exception as e:
            import traceback
            logger.error(f"[Wan I2V] ✗ Failed to load I2V pipeline: {e}")
            logger.error(f"[Wan I2V] Traceback:\n{traceback.format_exc()}")
            self._pipe_i2v = None
            return False

    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> GenerationResult:
        """
        Generate images/videos based on parameters.

        This method routes to video generation for txt2vid/img2vid modes.

        Args:
            params: Generation parameters.
            progress_callback: Optional progress callback (0-100).

        Returns:
            GenerationResult (contains video frames for video modes).
        """
        # For video modes, route to video generation
        if params.generation_mode in ('txt2vid', 'img2vid'):
            video_params = VideoGenerationParams(
                prompt=params.prompt,
                negative_prompt=params.negative_prompt,
                model=params.model,
                width=params.width,
                height=params.height,
                guidance_scale=params.guidance_scale,
                seed=params.seed,
                generation_mode=params.generation_mode,
                reference_image=params.reference_image,
            )
            video_result = self.generate_video(video_params, progress_callback)

            # Convert to GenerationResult for compatibility
            return GenerationResult(
                success=video_result.success,
                images=[],  # Videos don't have images
                seed_used=video_result.seed_used,
                error=video_result.error
            )

        # Fallback: this backend doesn't support image generation
        return GenerationResult(
            success=False,
            images=[],
            error="WanVideoBackend only supports video generation (txt2vid, img2vid)"
        )

    def generate_video(
        self,
        params: VideoGenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> VideoGenerationResult:
        """
        Generate video based on parameters.

        Args:
            params: Video generation parameters.
            progress_callback: Optional progress callback (0-100).

        Returns:
            VideoGenerationResult with video frames.
        """
        # AVANT tout chargement : l'I2V de ce backend charge Wan 2.2 I2V A14B (absent du
        # disque, ~25 Go à télécharger) — un modèle dont le profil l'exclut s'arrête en le disant.
        profile = self.MODEL_PROFILES.get(params.model) or {}
        if (params.generation_mode == 'img2vid' and params.reference_image
                and profile.get("img2vid") is False):
            return VideoGenerationResult(
                success=False,
                video_frames=[],
                error=f"{params.model} : la génération image→vidéo n'est pas prise en charge "
                      f"(texte→vidéo uniquement)."
            )

        if not self._loaded:
            if not self.load(params.model):
                return VideoGenerationResult(
                    success=False,
                    video_frames=[],
                    error="Failed to load model"
                )

        # Route to appropriate generation method
        if params.generation_mode == 'img2vid' and params.reference_image:
            return self._generate_img2vid(params, progress_callback)
        else:
            return self._generate_txt2vid(params, progress_callback)

    def _generate_txt2vid(
        self,
        params: VideoGenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> VideoGenerationResult:
        """Generate video from text prompt."""
        try:
            import torch
            import time

            logger.info("[Wan T2V] Starting Text-to-Video generation")
            logger.info(f"[Wan T2V] Prompt: {params.prompt[:100]}{'...' if len(params.prompt) > 100 else ''}")
            logger.info(f"[Wan T2V] Resolution: {params.width}x{params.height}")
            logger.info(f"[Wan T2V] Frames: {params.num_frames}, Steps: {params.num_inference_steps}")
            logger.info(f"[Wan T2V] Guidance scale: {params.guidance_scale}")

            if self._pipe_t2v is None:
                logger.info("[Wan T2V] Pipeline not loaded, loading now...")
                if not self.load(params.model):
                    return VideoGenerationResult(
                        success=False,
                        video_frames=[],
                        error="T2V pipeline not loaded"
                    )
            self._rehook('t2v', params.model)

            # Setup generator for reproducibility
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[Wan T2V] Generated random seed: {seed_used}")
            else:
                logger.info(f"[Wan T2V] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Modèle distillé DMD : pas et guidage IMPOSÉS par la distillation — les réglages de
            # la génération (30 pas, guidage 5 par défaut) le feraient diverger. Le re-bruitage
            # entre deux pas suit la graine de l'utilisateur.
            profile = self.MODEL_PROFILES.get(params.model) or {}
            num_steps = params.num_inference_steps
            guidance_scale = params.guidance_scale
            if profile.get("dmd_timesteps"):
                num_steps = len(profile["dmd_timesteps"])
                guidance_scale = profile.get("guidance_scale", 1.0)
                self._pipe_t2v.scheduler.generator = generator
                logger.info(f"[Wan T2V] DMD : {num_steps} pas imposés, guidage {guidance_scale}")

            # Grille latente : le VAE réduit de `vae_scale_factor_spatial` et le transformer
            # découpe en patchs — 16 pour Wan 2.2 A14B, 32 pour le 5B (720 → 704).
            try:
                grid = int(self._pipe_t2v.vae_scale_factor_spatial
                           * self._pipe_t2v.transformer.config.patch_size[1])
            except Exception:
                grid = 16
            width = max(grid, params.width // grid * grid)
            height = max(grid, params.height // grid * grid)
            if (width, height) != (params.width, params.height):
                logger.info(f"[Wan T2V] Résolution alignée sur la grille {grid} : {width}x{height}")

            # Build prompts
            prompt = params.prompt
            negative_prompt = params.negative_prompt or self.DEFAULT_NEGATIVE_PROMPT
            logger.info(f"[Wan T2V] Negative prompt: {negative_prompt[:50]}...")

            start_time = time.time()
            last_log_time = start_time

            # Progress callback wrapper
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                nonlocal last_log_time
                current_time = time.time()
                progress = int((step_index / num_steps) * 100)
                if progress_callback:
                    progress_callback(progress)
                # Log every 10 steps or every 30 seconds
                if step_index % 10 == 0 or (current_time - last_log_time) > 30:
                    elapsed = current_time - start_time
                    logger.info(f"[Wan T2V] Step {step_index}/{num_steps} ({progress}%) - Elapsed: {elapsed:.1f}s")
                    last_log_time = current_time
                return callback_kwargs

            # Clear CUDA cache before generation to avoid fragmentation issues
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()
                free_mem = torch.cuda.memory_reserved(0) - torch.cuda.memory_allocated(0)
                logger.info(f"[Wan T2V] CUDA cache cleared. Free reserved: {free_mem / 1024**3:.1f}GB")

            # Generate video
            logger.info("[Wan T2V] Starting inference... This may take several minutes.")
            with torch.inference_mode():
                output = self._pipe_t2v(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    height=height,
                    width=width,
                    num_frames=params.num_frames,
                    num_inference_steps=num_steps,
                    guidance_scale=guidance_scale,
                    generator=generator,
                    callback_on_step_end=step_callback,
                )

            video_frames = output.frames[0]  # Get first (and only) video

            total_time = time.time() - start_time
            logger.info(f"[Wan T2V] ✓ Generation complete in {total_time:.1f}s ({len(video_frames)} frames)")

            if progress_callback:
                progress_callback(100)

            return VideoGenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            logger.error(f"[Wan T2V] ✗ Generation failed: {e}")
            logger.error(f"[Wan T2V] Traceback:\n{traceback.format_exc()}")
            return VideoGenerationResult(
                success=False,
                video_frames=[],
                error=str(e)
            )

    def _generate_img2vid(
        self,
        params: VideoGenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> VideoGenerationResult:
        """Generate video from reference image."""
        try:
            import torch
            import numpy as np
            import time
            from PIL import Image

            logger.info("[Wan I2V] Starting Image-to-Video generation")
            logger.info(f"[Wan I2V] Reference image: {params.reference_image}")
            logger.info(f"[Wan I2V] Prompt: {params.prompt[:100]}{'...' if len(params.prompt) > 100 else ''}")
            logger.info(f"[Wan I2V] Target resolution: {params.width}x{params.height}")
            logger.info(f"[Wan I2V] Frames: {params.num_frames}, Steps: {params.num_inference_steps}")

            # Load I2V pipeline if needed
            if self._pipe_i2v is None:
                logger.info("[Wan I2V] Pipeline not loaded, loading now...")
                if not self._load_i2v_pipeline(params.model):
                    return VideoGenerationResult(
                        success=False,
                        video_frames=[],
                        error="I2V pipeline not available. Make sure diffusers is up to date: pip install git+https://github.com/huggingface/diffusers"
                    )
            self._rehook('i2v', params.model)

            # Load and prepare reference image
            if not params.reference_image or not os.path.exists(params.reference_image):
                logger.error(f"[Wan I2V] Reference image not found: {params.reference_image}")
                return VideoGenerationResult(
                    success=False,
                    video_frames=[],
                    error=f"Reference image not found: {params.reference_image}"
                )

            logger.info("[Wan I2V] Loading reference image...")
            image = Image.open(params.reference_image).convert("RGB")
            original_size = image.size
            logger.info(f"[Wan I2V] Original image size: {original_size[0]}x{original_size[1]}")

            # Calculate dimensions using pipeline's VAE scale factor
            # max_area based on target resolution
            max_area = params.width * params.height
            aspect_ratio = image.height / image.width

            # Get mod_value from pipeline if available, otherwise use default
            try:
                mod_value = self._pipe_i2v.vae_scale_factor_spatial * self._pipe_i2v.transformer.config.patch_size[1]
                logger.info(f"[Wan I2V] Using pipeline mod_value: {mod_value}")
            except Exception:
                mod_value = 16  # Default VAE scale factor
                logger.info(f"[Wan I2V] Using default mod_value: {mod_value}")

            height = round(np.sqrt(max_area * aspect_ratio)) // mod_value * mod_value
            width = round(np.sqrt(max_area / aspect_ratio)) // mod_value * mod_value
            image = image.resize((width, height), Image.LANCZOS)
            logger.info(f"[Wan I2V] Image resized to {width}x{height} (mod {mod_value} aligned)")

            # Setup generator
            seed_used = params.seed
            if seed_used is None:
                seed_used = torch.randint(0, 2**32, (1,)).item()
                logger.info(f"[Wan I2V] Generated random seed: {seed_used}")
            else:
                logger.info(f"[Wan I2V] Using provided seed: {seed_used}")

            generator = torch.Generator(device="cpu").manual_seed(seed_used)

            # Build prompts (prompt is optional for I2V)
            prompt = params.prompt if params.prompt else ""
            negative_prompt = params.negative_prompt or self.DEFAULT_NEGATIVE_PROMPT
            logger.info(f"[Wan I2V] Prompt: {prompt[:50] if prompt else '(none)'}...")
            logger.info(f"[Wan I2V] Negative prompt: {negative_prompt[:50]}...")

            # Use recommended guidance scale for I2V (3.5 is recommended)
            guidance_scale = params.guidance_scale if params.guidance_scale else 3.5
            num_steps = params.num_inference_steps

            # Modèle distillé DMD : mêmes réglages imposés qu'en texte→vidéo (cf. `_generate_txt2vid`)
            profile = self.MODEL_PROFILES.get(params.model) or {}
            if profile.get("dmd_timesteps"):
                num_steps = len(profile["dmd_timesteps"])
                guidance_scale = profile.get("guidance_scale", 1.0)
                self._pipe_i2v.scheduler.generator = generator
                logger.info(f"[Wan I2V] DMD : {num_steps} pas imposés, guidage {guidance_scale}")
            logger.info(f"[Wan I2V] Guidance scale: {guidance_scale}")

            start_time = time.time()
            last_log_time = start_time

            # Progress callback wrapper
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                nonlocal last_log_time
                current_time = time.time()
                progress = int((step_index / num_steps) * 100)
                if progress_callback:
                    progress_callback(progress)
                # Log every 10 steps or every 30 seconds
                if step_index % 10 == 0 or (current_time - last_log_time) > 30:
                    elapsed = current_time - start_time
                    logger.info(f"[Wan I2V] Step {step_index}/{num_steps} ({progress}%) - Elapsed: {elapsed:.1f}s")
                    last_log_time = current_time
                return callback_kwargs

            # Generate video
            logger.info("[Wan I2V] Starting inference... This may take 10-30 minutes depending on your GPU.")
            with torch.inference_mode():
                output = self._pipe_i2v(
                    image=image,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    height=height,
                    width=width,
                    num_frames=params.num_frames,
                    num_inference_steps=num_steps,
                    guidance_scale=guidance_scale,
                    generator=generator,
                    callback_on_step_end=step_callback,
                )

            video_frames = output.frames[0]

            total_time = time.time() - start_time
            logger.info(f"[Wan I2V] ✓ Generation complete in {total_time:.1f}s ({len(video_frames)} frames)")

            if progress_callback:
                progress_callback(100)

            return VideoGenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed_used
            )

        except Exception as e:
            import traceback
            logger.error(f"[Wan I2V] ✗ Generation failed: {e}")
            logger.error(f"[Wan I2V] Traceback:\n{traceback.format_exc()}")
            return VideoGenerationResult(
                success=False,
                video_frames=[],
                error=str(e)
            )

    def export_video(
        self,
        frames,
        output_path: str,
        fps: int = 16
    ) -> bool:
        """
        Export video frames to MP4 file.

        Args:
            frames: List of video frames (numpy arrays or PIL images).
            output_path: Path to save the MP4 file.
            fps: Frames per second.

        Returns:
            True if export successful.
        """
        try:
            import time
            from diffusers.utils import export_to_video

            logger.info(f"[Wan Export] Starting video export...")
            logger.info(f"[Wan Export] Frames: {len(frames)}, FPS: {fps}")
            logger.info(f"[Wan Export] Output path: {output_path}")

            # Ensure output directory exists
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Wan Export] Output directory: {output_dir}")

            # Export to video
            start_time = time.time()
            export_to_video(frames, output_path, fps=fps)
            export_time = time.time() - start_time

            # Check file size
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
                logger.info(f"[Wan Export] ✓ Video exported in {export_time:.1f}s")
                logger.info(f"[Wan Export] File size: {file_size:.2f} MB")
            else:
                logger.warning(f"[Wan Export] Export completed but file not found at {output_path}")

            return True

        except Exception as e:
            import traceback
            logger.error(f"[Wan Export] ✗ Failed to export video: {e}")
            logger.error(f"[Wan Export] Traceback:\n{traceback.format_exc()}")
            return False

    def unload(self) -> None:
        """Unload all models from memory."""
        if self._pipe_t2v is not None:
            del self._pipe_t2v
            self._pipe_t2v = None

        if self._pipe_i2v is not None:
            del self._pipe_i2v
            self._pipe_i2v = None

        if self._vae is not None:
            del self._vae
            self._vae = None

        self._current_model = None
        self._loaded = False
        self._shared_components = False
        self._hooks_owner = None

        # Force garbage collection
        gc.collect()

        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        logger.info("Wan video models unloaded from memory")

    @classmethod
    def calculate_num_frames(cls, duration_seconds: float, fps: int = 16) -> int:
        """
        Calculate number of frames for Wan (must be 4k+1).

        Args:
            duration_seconds: Desired video duration in seconds.
            fps: Frames per second.

        Returns:
            Number of frames (always 4k+1).
        """
        raw_frames = int(duration_seconds * fps)
        # Round to nearest 4k+1
        k = round((raw_frames - 1) / 4)
        return 4 * k + 1

    @classmethod
    def get_resolution(cls, preset: str) -> tuple:
        """
        Get resolution from preset name.

        Args:
            preset: Resolution preset ("480p" or "720p").

        Returns:
            (width, height) tuple.
        """
        return cls.RESOLUTION_PRESETS.get(preset, (832, 480))
