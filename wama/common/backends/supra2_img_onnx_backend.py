"""
Backend WAMA pour le modèle ONNX : Bartholomheow/Supra2-IMG-ONNX.

Le modèle est déjà présent localement ; les poids sont récupérés via
`component_paths('huggingface:Bartholomheow/Supra2-IMG-ONNX')` qui renvoie un
dictionnaire {rôle : Path}.  
Moteur : onnxruntime.  
Limites : résolution fixe 256×256, dtype du denoiser = fp32 (tel que
`pipeline_config.json` l’indique). Le backend signale un avertissement si
`width`/`height` diffèrent de 256.

Le code reproduit exactement l’algorithme de `example_inference.py` :
tokenisation → encodeur T5 → diffusion DiT (Euler) → décodage VAE.
"""

import json
import logging
import math
import os
from pathlib import Path
from typing import Callable, List, Optional

from .image_generation_base import (
    GenerationParams,
    GenerationResult,
    ImageGenerationBackend,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Inventaire des modèles supportés (module‑level, tel que requis)
# --------------------------------------------------------------------------- #
# Le nom de sa ligne de catalogue, et RIEN d'autre : nom, description et VRAM sont au
# REGISTRE (l'inventaire ne lit que la clé) — 2026-10-06, `backend_proposals`.
SUPPORTED_MODELS = {
    "Bartholomheow/Supra2-IMG-ONNX": {"model_key": "huggingface:Bartholomheow/Supra2-IMG-ONNX"},
}


class Supra2OnnxBackend(ImageGenerationBackend):
    """
    Backend d’inférence ONNX pour Supra2‑IMG.

    Implémente le contrat ``ImageGenerationBackend`` en s’appuyant sur
    onnxruntime et transformers (tokenizer). Aucun téléchargement n’est
    effectué ; les fichiers sont lus depuis le répertoire du snapshot.
    """

    # ------------------------------------------------------------------- #
    # Métadonnées requises par le contrat commun
    # ------------------------------------------------------------------- #
    ENGINE = "onnxruntime"
    REQUIRED_PACKAGES = ["onnxruntime", "transformers", "numpy", "Pillow"]
    name = "supra2_onnx"
    display_name = "Supra2‑IMG (ONNX)"
    recommended_vram_gb = 1.3

    def __init__(self):
        super().__init__()
        self._enc_session = None          # Text encoder (ONNX)
        self._dit_session = None          # Denoiser DiT (ONNX)
        self._vae_session = None          # VAE decoder (ONNX)
        self._tokenizer = None            # transformers.AutoTokenizer
        self._config = None               # pipeline_config.json
        self._device = "cpu"

    # ------------------------------------------------------------------- #
    # Vérification de disponibilité (paquets uniquement)
    # ------------------------------------------------------------------- #
    @classmethod
    def is_available(cls) -> bool:
        try:
            import onnxruntime  # noqa: F401
            import transformers  # noqa: F401
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning(f"Supra2‑OnnxBackend indisponible : {exc}")
            return False

    # ------------------------------------------------------------------- #
    # Chargement des sessions ONNX et du tokenizer
    # ------------------------------------------------------------------- #
    def load(self, model_name: str = None) -> bool:
        """
        Initialise les trois sessions ONNX et le tokenizer.

        Le paramètre ``model_name`` est ignoré : le backend ne supporte qu’un
        seul modèle (celui du catalogue).
        """
        from wama.common.utils.model_components import component_paths
        from wama.common.utils.onnx_utils import onnx_providers

        try:
            # ----------------------------------------------------------------
            # Récupération des chemins des composants ONNX
            # ----------------------------------------------------------------
            paths = component_paths("huggingface:Bartholomheow/Supra2-IMG-ONNX")
            # rôle → Path vers le fichier .onnx
            enc_path = paths["text_encoder"]
            dit_path = paths["denoiser"]
            vae_path = paths["vae_decoder"]

            # ----------------------------------------------------------------
            # Chargement du tokenizer (situé à la racine du snapshot)
            # ----------------------------------------------------------------
            root_dir = enc_path.parent.parent  # .../text_encoder/encoder_model.onnx → root
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(str(root_dir))

            # ----------------------------------------------------------------
            # Lecture du fichier de configuration du pipeline
            # ----------------------------------------------------------------
            cfg_path = root_dir / "pipeline_config.json"
            with open(cfg_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)

            # ----------------------------------------------------------------
            # Création des sessions ONNX avec les fournisseurs adéquats
            # ----------------------------------------------------------------
            import onnxruntime as ort

            providers = onnx_providers()
            self._enc_session = ort.InferenceSession(str(enc_path), providers=providers)
            self._dit_session = ort.InferenceSession(str(dit_path), providers=providers)
            self._vae_session = ort.InferenceSession(str(vae_path), providers=providers)

            # Détermination du device d’après les providers
            self._device = "cuda" if any("CUDA" in p for p in providers) else "cpu"

            self._loaded = True
            logger.info(
                f"Supra2‑OnnxBackend chargé (device={self._device}, providers={providers})"
            )
            return True
        except Exception as exc:  # pragma: no cover
            logger.error(f"Échec du chargement du backend Supra2‑Onnx : {exc}")
            self._loaded = False
            return False

    # ------------------------------------------------------------------- #
    # Déchargement des sessions
    # ------------------------------------------------------------------- #
    def unload(self) -> None:
        """Libère les sessions ONNX et le tokenizer."""
        self._enc_session = None
        self._dit_session = None
        self._vae_session = None
        self._tokenizer = None
        self._config = None
        self._device = None
        self._loaded = False
        import gc

        gc.collect()
        logger.info("Supra2‑OnnxBackend déchargé")

    # ------------------------------------------------------------------- #
    # Génération d’images
    # ------------------------------------------------------------------- #
    def generate(
        self,
        params: GenerationParams,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> GenerationResult:
        """
        Génère une ou plusieurs images à partir du prompt.

        L’algorithme reproduit exactement celui de ``example_inference.py``.
        """
        if not self._loaded:
            if not self.load():
                return GenerationResult(
                    success=False, images=[], error="Backend not loaded"
                )

        # --------------------------------------------------------------------
        # Vérifications de paramètres (résolution fixe 256×256)
        # --------------------------------------------------------------------
        target_sz = self._config.get("image_size", 256)
        if params.width != target_sz or params.height != target_sz:
            logger.warning(
                f"Supra2‑Onnx ne supporte que {target_sz}×{target_sz} ; "
                f"les dimensions demandées ({params.width}×{params.height}) seront ignorées."
            )
        width = height = target_sz

        # --------------------------------------------------------------------
        # Helpers de génération (mulberry32, gaussian, to_half)
        # --------------------------------------------------------------------
        def mulberry32(seed: int):
            a = seed & 0xFFFFFFFF

            def rand() -> float:
                nonlocal a
                a = (a + 0x6D2B79F5) & 0xFFFFFFFF
                t = (a ^ (a >> 15)) * (1 | a) & 0xFFFFFFFF
                t = (t + ((t ^ (t >> 7)) * (61 | t) & 0xFFFFFFFF)) & 0xFFFFFFFF
                return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

            return rand

        def gaussian(seed: int, n: int):
            rand = mulberry32(seed)
            out = np.empty(n, dtype=np.float32)
            for i in range(0, n, 2):
                r = math.sqrt(-2 * math.log(max(rand(), 1e-12)))
                a = 2 * math.pi * rand()
                out[i] = r * math.cos(a)
                if i + 1 < n:
                    out[i + 1] = r * math.sin(a)
            return out

        def to_half(arr: "np.ndarray"):
            return arr.astype(np.float16)

        # --------------------------------------------------------------------
        # Tokenisation (prompt + vide pour l’uncond)
        # --------------------------------------------------------------------
        import numpy as np

        def encode(text: str):
            toks = self._tokenizer(
                [text],
                padding="max_length",
                truncation=True,
                max_length=self._config["ctx_len"],
                return_tensors="np",
            )
            ids = toks["input_ids"].astype(np.int64)
            am = toks["attention_mask"].astype(np.int64)
            hidden = self._enc_session.run(
                None, {"input_ids": ids, "attention_mask": am}
            )[0]
            return hidden, (am > 0).astype(np.float32)

        ctx, mask = encode(params.prompt)
        uctx, umask = encode("")

        # --------------------------------------------------------------------
        # Pré‑calculs du bruit initial
        # --------------------------------------------------------------------
        latent_ch = self._config["latent_ch"]
        latent_sz = self._config["latent_size"]
        n = latent_ch * latent_sz * latent_sz

        # Seed dérivé du prompt + seed fourni (compatible avec l’exemple)
        base_seed = sum(ord(c) for c in params.prompt) + (params.seed or 0)
        z = (
            gaussian(base_seed, n)
            .reshape(1, latent_ch, latent_sz, latent_sz)
            .astype(np.float32)
        )

        # --------------------------------------------------------------------
        # Boucle de diffusion
        # --------------------------------------------------------------------
        steps = params.steps or self._config.get("default_steps", 50)
        cfg_scale = params.guidance_scale or self._config.get("default_cfg", 3.0)
        dt = 1.0 / steps
        dit_fp16 = self._config.get("dit_dtype", "fp32") != "fp32"
        ztype = np.float16 if dit_fp16 else np.float32

        for i in range(steps):
            t = np.array([i * dt], dtype=np.float32)

            outs = []
            for c, m in ((ctx, mask), (uctx, umask)):
                # Convertir le contexte au bon dtype si nécessaire
                cc = (
                    to_half(c)
                    if dit_fp16 and c.dtype != np.float16
                    else c.astype(ztype, copy=False)
                )
                v = self._dit_session.run(
                    None,
                    {
                        "z": z.astype(ztype, copy=False),
                        "t": t,
                        "ctx": cc,
                        "ctx_mask": m,
                    },
                )[0]
                outs.append(np.asarray(v, dtype=np.float32))

            vc, vu = outs
            z = z + dt * (vu + cfg_scale * (vc - vu))

        # --------------------------------------------------------------------
        # Décodage VAE
        # --------------------------------------------------------------------
        vae_scale = self._config["vae_scale"]
        img_tensor = self._vae_session.run(
            None, {"z": (z / vae_scale).astype(np.float32)}
        )[0]  # shape (1, 3, H, W)

        # Conversion en image PIL
        rgb = (
            np.clip((img_tensor + 1) / 2, 0, 1) * 255
        ).round().astype(np.uint8)[0].transpose(1, 2, 0)
        from PIL import Image

        images: List[Image.Image] = [Image.fromarray(rgb)]

        # --------------------------------------------------------------------
        # Gestion du nombre d’images demandé
        # --------------------------------------------------------------------
        # Le modèle ne supporte pas la génération batchée ; on répète le
        # processus avec un seed différent pour chaque image supplémentaire.
        for idx in range(1, params.num_images):
            if progress_callback:
                progress_callback(int(100 * idx / params.num_images))

            # Nouveau seed (décalé)
            seed = base_seed + idx
            z = (
                gaussian(seed, n)
                .reshape(1, latent_ch, latent_sz, latent_sz)
                .astype(np.float32)
            )
            for i in range(steps):
                t = np.array([i * dt], dtype=np.float32)
                outs = []
                for c, m in ((ctx, mask), (uctx, umask)):
                    cc = (
                        to_half(c)
                        if dit_fp16 and c.dtype != np.float16
                        else c.astype(ztype, copy=False)
                    )
                    v = self._dit_session.run(
                        None,
                        {
                            "z": z.astype(ztype, copy=False),
                            "t": t,
                            "ctx": cc,
                            "ctx_mask": m,
                        },
                    )[0]
                    outs.append(np.asarray(v, dtype=np.float32))
                vc, vu = outs
                z = z + dt * (vu + cfg_scale * (vc - vu))

            img_tensor = self._vae_session.run(
                None, {"z": (z / vae_scale).astype(np.float32)}
            )[0]
            rgb = (
                np.clip((img_tensor + 1) / 2, 0, 1) * 255
            ).round().astype(np.uint8)[0].transpose(1, 2, 0)
            images.append(Image.fromarray(rgb))

        if progress_callback:
            progress_callback(100)

        return GenerationResult(
            success=True,
            images=images,
            seed_used=base_seed,
        )
