"""Aperçu « pendant » BON MARCHÉ d'une génération par diffusion : les latents → une image.

Décision de Fabien (2026-10-06) : ne pas consommer de VRAM en plus sur des générations qui en
demandent déjà beaucoup. Donc AUCUN décodage VAE : les latents du pas courant sont projetés
LINÉAIREMENT vers RGB (une multiplication de matrice sur quelques milliers de pixels latents),
sur le CPU, au plus une fois par cadence de publication. L'image est floue et ses couleurs
approchées — assez pour voir la composition se former.

Trois pièces :
  - `vae_family(vae)` : la famille de latents, DÉDUITE de la configuration du VAE du pipeline
    (classe, canaux, facteurs d'échelle) par une table de règles — aucune déclaration par
    modèle à tenir ;
  - `latents_to_image(latents, …)` : latents à plat [C,H,W], vidéo [C,T,H,W] / [T,C,H,W], ou
    EMBALLÉS en jetons [L, C·p·p] (Flux, Qwen-Image, Flux2, LTX) → image BGR ;
  - `preview_from_pipe(pipe, latents, height, width)` : les deux à la suite, pour le rappel par
    pas d'un backend (`ImageGenerationBackend.preview_step`).

Coefficients : `latent_rgb_factors` (extraits de ComfyUI, GPL-3.0 — voir ce module). Une famille
sans coefficients (CogVideoX, un VAE inconnu) retombe sur une projection sur les trois axes
principaux du latent lui-même : la composition se voit, les couleurs sont fausses.
"""
from __future__ import annotations

import math
from typing import Optional

#: Déduire la famille d'un VAE : (classe du VAE, canaux latents, clé de config, valeur, famille).
#: La PREMIÈRE règle qui convient gagne ; `None` comme clé = aucune condition de plus.
#: Deux familles partagent une classe (`AutoencoderKL` : SD 1.5 / SDXL / SD3 / Flux) : c'est le
#: facteur d'échelle — ou de décalage — de leur config qui les distingue.
VAE_RULES = (
    ('AutoencoderKL', 4, 'scaling_factor', 0.13025, 'SDXL'),
    ('AutoencoderKL', 4, None, None, 'SD15'),
    ('AutoencoderKL', 16, 'shift_factor', 0.0609, 'SD3'),
    ('AutoencoderKL', 16, None, None, 'Flux'),
    ('AutoencoderKLFlux2', 32, None, None, 'Flux2'),
    ('AutoencoderKLWan', 16, None, None, 'Wan21'),
    ('AutoencoderKLWan', 48, None, None, 'Wan22'),
    ('AutoencoderKLQwenImage', 16, None, None, 'Wan21'),   # Qwen-Image 1.x = VAE de Wan 2.1
    ('AutoencoderKLQwenImage', 64, None, None, 'QwenImage21'),
    ('AutoencoderKLHunyuanImage', 64, None, None, 'HunyuanImage21'),
    ('AutoencoderKLHunyuanVideo', 16, None, None, 'HunyuanVideo'),
    ('AutoencoderKLHunyuanVideo15', 32, None, None, 'HunyuanVideo15'),
    ('AutoencoderKLLTXVideo', 128, None, None, 'LTXV'),
    ('AutoencoderKLMochi', 12, None, None, 'Mochi'),
)

#: Longueur du plus grand côté de l'image d'aperçu publiée.
PREVIEW_SIDE = 512


def _config_get(config, key, default=None):
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def vae_channels(vae) -> Optional[int]:
    config = getattr(vae, 'config', None)
    return _config_get(config, 'latent_channels') or _config_get(config, 'z_dim')


def vae_family(vae) -> Optional[str]:
    """La famille de latents d'un VAE (clé de `LATENT_RGB`), ou None si aucune règle ne convient."""
    if vae is None:
        return None
    name = type(vae).__name__
    config = getattr(vae, 'config', None)
    channels = vae_channels(vae)
    for cls, ch, key, value, family in VAE_RULES:
        if name != cls or channels != ch:
            continue
        if key is None:
            return family
        found = _config_get(config, key)
        if found is not None and math.isclose(float(found), value, rel_tol=1e-3):
            return family
    return None


def _spatial_ratio(pipe) -> int:
    return int(getattr(pipe, 'vae_scale_factor_spatial', 0)
               or getattr(pipe, 'vae_spatial_compression_ratio', 0)      # LTX
               or getattr(pipe, 'vae_scale_factor', 0) or 8)


def _to_chw(t, channels: Optional[int], height=None, width=None, ratio: int = 8):
    """[C,H,W] de la DERNIÈRE image, quelle que soit la disposition des latents (un élément du
    lot, déjà sans dimension de lot). Rend None si la forme n'est pas reconnue.

      [C, H, W]        image à plat (SD, SDXL, HunyuanImage) ;
      [C·4, H, W]      canaux « patchifiés » 2×2 (Flux2 : 128 = 32 × 2 × 2) → dépliés ;
      [C, T, H, W]     vidéo (Wan, Mochi, LTX, Hunyuan) ; [T, C, H, W] (CogVideoX) ;
      [L, C·p·p]       jetons EMBALLÉS (Flux, Qwen-Image, Flux2, LTX) → grille reconstituée
                       d'après la taille demandée (`height`, `width`, facteur du VAE)."""
    if t.ndim == 4:
        if channels and t.shape[1] == channels and t.shape[0] != channels:
            return t[-1]
        return t[:, -1]
    if t.ndim == 3:
        if channels and t.shape[0] == channels * 4:
            c, h, w = channels, t.shape[1], t.shape[2]
            return t.reshape(c, 2, 2, h, w).permute(0, 3, 1, 4, 2).reshape(c, h * 2, w * 2)
        return t
    if t.ndim == 2 and channels and height and width:   # jetons EMBALLÉS [L, C·p·p]
        depth = t.shape[-1]
        if depth % channels:
            return None
        patch = int(round(math.sqrt(depth // channels)))
        if patch * patch * channels != depth:
            return None
        hp, wp = height // (ratio * patch), width // (ratio * patch)
        if hp * wp == 0 or t.shape[0] % (hp * wp):
            # La taille réelle n'est pas celle qu'on connaît (édition de Qwen-Image : le pipeline
            # la recalcule d'après l'image de référence) : grille retrouvée d'après le NOMBRE de
            # jetons et les PROPORTIONS données, si une seule image est en cours.
            hp, wp = _grid_from_tokens(t.shape[0], height / width)
            if not hp:
                return None
        last = t[-hp * wp:]                        # la dernière image d'une suite (LTX)
        grid = last.reshape(hp, wp, channels, patch, patch)
        return grid.permute(2, 0, 3, 1, 4).reshape(channels, hp * patch, wp * patch)
    return None


def _grid_from_tokens(count: int, aspect: float):
    """(lignes, colonnes) d'une grille de `count` jetons dont le rapport hauteur/largeur est le
    plus proche de `aspect` ; (0, 0) si aucune grille exacte n'est assez proche (±25 %)."""
    if count <= 0 or aspect <= 0:
        return 0, 0
    best = (0, 0)
    best_gap = None
    for rows in range(1, count + 1):
        if count % rows:
            continue
        cols = count // rows
        gap = abs(math.log((rows / cols) / aspect))
        if best_gap is None or gap < best_gap:
            best, best_gap = (rows, cols), gap
    return best if best_gap is not None and best_gap < math.log(1.25) else (0, 0)


def _project(chw, family: Optional[str]):
    """[3,H,W] dans [0,1] : coefficients de la famille, sinon trois axes principaux."""
    import torch
    from .latent_rgb_factors import LATENT_RGB
    entry = LATENT_RGB.get(family) if family else None
    if entry and entry['channels'] == chw.shape[0]:
        factors = torch.tensor(entry['factors'], dtype=chw.dtype)          # [C, 3]
        bias = torch.tensor(entry['bias'], dtype=chw.dtype)
        rgb = torch.einsum('chw,cr->rhw', chw, factors) + bias[:, None, None]
        return ((rgb + 1.0) / 2.0).clamp(0.0, 1.0)
    flat = chw.reshape(chw.shape[0], -1)
    flat = flat - flat.mean(dim=1, keepdim=True)
    _u, _s, v = torch.linalg.svd(flat.T, full_matrices=False)
    comps = (flat.T @ v[:3].T).T.reshape(-1, *chw.shape[1:])
    if comps.shape[0] < 3:
        comps = torch.cat([comps, comps[:1].expand(3 - comps.shape[0], *comps.shape[1:])])
    low = comps.reshape(3, -1).quantile(0.02, dim=1)[:, None, None]
    high = comps.reshape(3, -1).quantile(0.98, dim=1)[:, None, None]
    return ((comps - low) / (high - low).clamp_min(1e-6)).clamp(0.0, 1.0)


def latents_to_image(latents, family: Optional[str], *, channels: Optional[int] = None,
                     height: int = None, width: int = None, ratio: int = 8):
    """Image BGR (uint8, côté long ≤ `PREVIEW_SIDE`) des latents du pas courant, ou None.

    Seul le PREMIER élément du lot est lu, et seule sa dernière image pour une vidéo : la tranche
    est prise sur l'appareil des latents AVANT la copie vers le CPU (quelques Mo au plus)."""
    import cv2
    import numpy as np
    from .latent_rgb_factors import LATENT_RGB
    if latents is None or getattr(latents, 'ndim', 0) < 3:
        return None
    if channels is None and family in LATENT_RGB:
        channels = LATENT_RGB[family]['channels']
    first = latents[0].detach()
    if first.ndim == 4:                       # vidéo : la dernière image, prise AVANT la copie
        first = _to_chw(first, channels)
    chw = _to_chw(first.float().cpu(), channels, height, width, ratio)
    if chw is None or chw.ndim != 3:
        return None
    rgb = _project(chw, family)
    image = (rgb.permute(1, 2, 0).numpy() * 255.0).astype(np.uint8)[:, :, ::-1]
    h, w = image.shape[:2]
    scale = PREVIEW_SIDE / max(h, w)
    if scale > 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(image)


def preview_from_pipe(pipe, latents, *, height: int = None, width: int = None):
    """Le rappel par pas d'un backend diffusers : famille et canaux lus sur SON VAE."""
    vae = getattr(pipe, 'vae', None)
    family = vae_family(vae)
    return latents_to_image(latents, family, channels=vae_channels(vae),
                            height=height, width=width, ratio=_spatial_ratio(pipe))
