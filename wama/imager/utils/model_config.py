"""
Imager Model Configuration

Centralized configuration for all models used by the Imager application.
Uses the centralized AI-models directory structure from settings.py.

# ════════════════════════════════════════════════════════════════════════
# ⚠️  RÈGLE OBLIGATOIRE — AJOUT D'UN NOUVEAU MODÈLE
# ════════════════════════════════════════════════════════════════════════
#
# Avant d'ajouter un modèle qui télécharge via HuggingFace Hub :
#
#  1. Ajouter une entrée dans settings.MODEL_PATHS['diffusion'] (ou 'speech'
#     etc.) avec le chemin dédié au modèle.
#
#  2. Ajouter la constante *_DIR ici en la lisant depuis MODEL_PATHS
#     (avec fallback explicite), par exemple :
#         MONMODELE_DIR = MODEL_PATHS.get('diffusion', {}).get('mon_modele',
#             settings.AI_MODELS_DIR / "models" / "diffusion" / "mon-modele")
#
#  3. Dans le backend (backends/*.py), AVANT tout import de transformers /
#     diffusers / huggingface_hub, ajouter :
#         os.environ['HF_HUB_CACHE'] = str(MON_MODELE_DIR)
#         os.environ['HUGGINGFACE_HUB_CACHE'] = str(MON_MODELE_DIR)
#     ET passer cache_dir=str(MON_MODELE_DIR) à from_pretrained().
#
#  4. Ajouter l'entrée dans IMAGER_MODELS (ou le groupe approprié) avec
#     au minimum : model_id, hf_id, type, mode, vram_gb, description.
#
#  5. Mettre à jour _discover_imager_models() dans model_registry.py.
#
#  Ne jamais laisser un modèle se télécharger dans AI-models/cache/huggingface/
#  via la mise en cache globale par défaut — chaque modèle a son propre répertoire.
# ════════════════════════════════════════════════════════════════════════
"""

import os
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# =============================================================================
# MODEL PATHS CONFIGURATION
# =============================================================================

# Get centralized paths from settings
MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

# Diffusion models directories
HUNYUAN_DIR = MODEL_PATHS.get('diffusion', {}).get('hunyuan',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "hunyuan")

STABLE_DIFFUSION_DIR = MODEL_PATHS.get('diffusion', {}).get('stable_diffusion',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "stable-diffusion")

COGVIDEOX_DIR = MODEL_PATHS.get('diffusion', {}).get('cogvideox',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "cogvideox")

LTX_DIR = MODEL_PATHS.get('diffusion', {}).get('ltx',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "ltx")

MOCHI_DIR = MODEL_PATHS.get('diffusion', {}).get('mochi',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "mochi")

FLUX_DIR = MODEL_PATHS.get('diffusion', {}).get('flux',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "flux")

LOGO_DIR = MODEL_PATHS.get('diffusion', {}).get('logo',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "logo")

QWEN_IMAGE_DIR = MODEL_PATHS.get('diffusion', {}).get('qwen_image',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "qwen-image")

FLUX2_KLEIN_DIR = MODEL_PATHS.get('diffusion', {}).get('flux2_klein',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "flux2-klein")

# Ensure directories exist
for dir_path in [HUNYUAN_DIR, STABLE_DIFFUSION_DIR, COGVIDEOX_DIR, LTX_DIR,
                 MOCHI_DIR, FLUX_DIR, LOGO_DIR, QWEN_IMAGE_DIR, FLUX2_KLEIN_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

# ─── Hunyuan Image (Tencent) ──────────────────────────────────────────────────
HUNYUAN_MODELS = {
    'hunyuan-image-2.1': {
        'model_id': 'hunyuan-image-2.1',
        'hf_id': 'hunyuanvideo-community/HunyuanImage-2.1-Diffusers',
        'type': 'image',
        'mode': 't2i',
        'vram_gb': 16,
        'description': 'HunyuanImage 2.1 — qualité max, text rendering, 1K-4K',
        'description_long': "HunyuanImage 2.1 (Tencent) : génération d'images haut de gamme, "
                            "excellent rendu du texte dans l'image et résolutions 1K à 4K. "
                            "Le choix qualité maximale quand le temps de génération importe peu.",
    },
}

# ─── CogVideoX (Tsinghua THUDM) ───────────────────────────────────────────────
COGVIDEOX_MODELS = {
    # 'cogvideox-5b' (Text-to-Video) RETIRÉ du parc local le 2026-07-28 : redondant avec
    # LTX-Video-13B-distilled (plus récent, 14 GB VRAM contre 21, déjà sur disque), pour
    # 20,05 GiB. Poids sauvegardés sur le NAS (DEEP_LEARNING/MODELS/diffusion/cogvideox/),
    # vérifiés octet par octet avant suppression — restaurables par recopie.
    # ⚠ La variante I2V ci-dessous est un dépôt HF DISTINCT et reste en service.
    'cogvideox-5b-i2v': {
        'model_id': 'cogvideox-5b-i2v',
        'hf_id': 'THUDM/CogVideoX-5b-I2V',
        'type': 'video',
        'mode': 'i2v',
        'vram_gb': 21,
        'disk_gb': 12,
        'fps': 24,
        'resolution': '720x480',
        'description': 'CogVideoX 5B — Image-to-Video, 24 fps',
        'description_long': "CogVideoX 5B I2V (Zhipu/THUDM) : anime une image de référence en "
                            "clip vidéo 24 images/s, guidé par le prompt. Idéal pour donner vie "
                            "à une illustration ou une photo.",
    },
}

# ─── LTX-Video (Lightricks) ───────────────────────────────────────────────────
# Seul repo diffusers disponible pour la 0.9.8 : Lightricks/LTX-Video-0.9.8-13B-distilled
# (pas de repo 0.9.8-dev — utiliser 0.9.7-dev ou attendre la sortie officielle)
LTX_MODELS = {
    # ── 13B Distilled — rapide, haute qualité ────────────────────────────────
    'ltx-video-13b-0.9.8-distilled': {
        'model_id': 'ltx-video-13b-0.9.8-distilled',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-13B-distilled',
        'type': 'video',
        'mode': 't2v+i2v',
        'vram_gb': 14,
        'disk_gb': 18,
        'fps': 24,
        'resolution': '1216x704',
        'description': 'LTX-Video 13B Distilled — rapide, T2V + I2V',
        'description_long': "LTX-Video 13B Distilled (Lightricks) : génération vidéo rapide, en "
                            "texte-vers-vidéo comme en image-vers-vidéo. La distillation réduit "
                            "fortement le nombre d'étapes — bon choix par défaut pour itérer vite.",
    },
    # ── 13B Distilled FP8 — meilleur ratio qualité/VRAM sur RTX 4090 ─────────
    'ltx-video-13b-0.9.8-distilled-fp8': {
        'model_id': 'ltx-video-13b-0.9.8-distilled-fp8',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-13B-distilled',
        'type': 'video',
        'mode': 't2v+i2v',
        'vram_gb': 8,
        'disk_gb': 18,
        'fps': 24,
        'resolution': '1216x704',
        'quantization': 'fp8',
        'description': 'LTX-Video 13B Distilled FP8 — léger, T2V + I2V',
        'description_long': "LTX-Video 13B Distilled en quantification FP8 : mêmes usages que la "
                            "version distillée (T2V + I2V) avec une empreinte mémoire réduite, au "
                            "prix d'une légère perte de qualité. Pour GPU plus modestes.",
    },
}

# ─── Mochi (Genmo) ────────────────────────────────────────────────────────────
MOCHI_MODELS = {
    'mochi-1-preview': {
        'model_id': 'mochi-1-preview',
        'hf_id': 'genmo/mochi-1-preview',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 22,
        'disk_gb': 18,
        'fps': 30,
        'resolution': '848x480',
        'description': 'Mochi-1 Preview — haute qualité, 30 fps',
        'description_long': "Mochi-1 Preview (Genmo) : génération vidéo haute fidélité à 30 "
                            "images/s, mouvements naturels et bonne adhérence au prompt. Le plus "
                            "gourmand des modèles vidéo — à réserver aux rendus soignés.",
    },
}

# ─── Stable Diffusion (image generation) ─────────────────────────────────────
STABLE_DIFFUSION_MODELS = {
    'stable-diffusion-v1-5': {
        'model_id': 'stable-diffusion-v1-5',
        'hf_id': 'stable-diffusion-v1-5/stable-diffusion-v1-5',
        'type': 'image',
        'pipeline': 'sd',
        # t2i + image de référence OPTIONNELLE (StableDiffusionImg2ImgPipeline,
        # diffusers_backend._generate_img2img) — nourrit l'appariement entrée↔modèle.
        'mode': 't2i+i2i',
        'vram_gb': 4,
        'description': 'Stable Diffusion 1.5 — classique (compatibilité LoRA)',
        'description_long': "Stable Diffusion 1.5 (Runway/CompVis) : le classique historique de la "
                            "génération d'images, porté par le plus vaste écosystème de LoRA et de "
                            "fine-tunes. Qualité datée en natif, mais base de compatibilité inégalée.",
    },
    'stable-diffusion-xl': {
        'model_id': 'stable-diffusion-xl',
        'hf_id': 'stabilityai/stable-diffusion-xl-base-1.0',
        'type': 'image',
        'pipeline': 'sdxl',
        # t2i + image de référence OPTIONNELLE (StableDiffusionXLImg2ImgPipeline).
        'mode': 't2i+i2i',
        'vram_gb': 10,
        'description': 'Stable Diffusion XL — haute résolution (compatibilité LoRA)',
        'description_long': "Stable Diffusion XL (Stability AI) : génération native en 1024 px, "
                            "compositions et anatomies bien plus fiables que SD 1.5, large choix "
                            "de LoRA. La valeur sûre polyvalente de la famille Stable Diffusion.",
    },
    # 'dreamlike-art-2' (1,99 GiB) et 'deliberate-v6' (1,99 GiB) RETIRÉS du parc local le
    # 2026-07-28 : deux fine-tunes SD 1.5 de 2022-2023 sur le même créneau que SD 1.5 lui-même,
    # que les modèles 1024 px du parc (SDXL, FLUX.1-dev, Qwen) couvrent largement.
    # Poids sauvegardés sur le NAS et vérifiés octet par octet avant suppression.
    # RETIRÉS (2026-07-28) : 'stable-diffusion-2-1', 'dreamshaper-8', 'anything-v5'.
    # Les trois étaient offerts au dropdown (téléchargement à la demande) mais n'ont JAMAIS été
    # téléchargés, et appartiennent tous à l'ère SD 1.5/2.x — exactement l'étage que la
    # modernisation du parc remplace. SD 1.5 et SDXL restent, eux, pour l'écosystème LoRA.
    # Restaurables par git si un besoin de style précis réapparaît.
}

# ─── Qwen Image 2 (Alibaba) ───────────────────────────────────────────────────
# Apache 2.0 — #1 open source (AI Arena), text rendering, 2K natif, character consistency
# HF IDs : Qwen/Qwen-Image-2512 (20B, gen), Qwen/Qwen-Image-Edit-2511 (editing)
# Backend : qwen_image_backend.py (diffusers-compatible)
QWEN_IMAGE_MODELS = {
    'qwen-image-2': {
        'model_id': 'qwen-image-2',
        'hf_id': 'Qwen/Qwen-Image-2512',
        'type': 'image',
        'mode': 't2i',
        'pipeline': 'qwen_image',
        # 38 Go MESURÉS le 29/07/2026 (annoncé 16 jusque-là). Un MMDiT de 20B en bf16 pèse
        # ~40 Go de poids : 16 était structurellement impossible. Conséquence de l'écart : le
        # backend tentait FULL_GPU sur une carte de 24 Go → débordement en RAM hôte sous WSL2.
        # ⛔ Ne tient PAS sur une RTX 4090 → offload CPU obligatoire (lent, mais fonctionnel).
        'vram_gb': 38,
        'disk_gb': 40,
        'resolution': 2048,
        # Alignés sur qwen_image_backend.SUPPORTED_MODELS (default_steps / default_true_cfg) :
        # Qwen attend 50 étapes et un true_cfg de 4.0, PAS les 30/7.5 de l'ère SD. Sans ces clés,
        # get_model_defaults() retombait sur les valeurs SD et bridait le modèle par défaut.
        'default_steps': 50,
        'default_guidance_scale': 4.0,
        'description': 'Qwen Image 2 (20B) — #1 open source, text rendering, 2K natif',
        'description_long': "Qwen-Image 2 (Alibaba, 20B) : parmi les meilleurs modèles image "
                            "open-source, rendu du texte dans l'image remarquable et 2K natif. "
                            "Qualité proche des services propriétaires, au prix d'une VRAM élevée.",
        'license': 'apache-2.0',
    },
    'qwen-image-edit': {
        'model_id': 'qwen-image-edit',
        'hf_id': 'Qwen/Qwen-Image-Edit-2511',
        'type': 'image',
        'mode': 'edit',
        'pipeline': 'qwen_image',
        # ⚠️ NON MESURÉ — borne prudente. Qwen-Image-Edit partage la dorsale MMDiT 20B de
        # Qwen-Image : les 12 Go déclarés ici à l'origine étaient impossibles. En attendant une
        # mesure, on prend celle de la dorsale (38) : sur-estimer coûte de l'offload,
        # sous-estimer fait tenter FULL_GPU et fait tomber l'hôte. À MESURER.
        'vram_gb': 38,
        'disk_gb': 25,
        'resolution': 2048,
        # Idem qwen-image-2 : valeurs du backend Qwen, pas celles de SD.
        'default_steps': 50,
        'default_guidance_scale': 4.0,
        'description': 'Qwen Image Edit — édition multi-image, 14 images, 2K',
        'description_long': "Qwen-Image-Edit (Alibaba) : édition d'images guidée par instruction "
                            "— retouche, fusion et composition jusqu'à 14 images de référence, "
                            "sortie 2K. Pour modifier une image existante plutôt qu'en créer une.",
        'license': 'apache-2.0',
    },
}

# ─── FLUX.2 [klein] 4B (Black Forest Labs) ───────────────────────────────────
# Apache 2.0 — distilled 4-step model, <1s/image, T2I + image-conditioned
# HF: black-forest-labs/FLUX.2-klein-4B
# Pipeline: diffusers Flux2KleinPipeline (diffusers >= 0.37)
FLUX2_KLEIN_MODELS = {
    'flux2-klein-4b': {
        'model_id': 'flux2-klein-4b',
        'hf_id': 'black-forest-labs/FLUX.2-klein-4B',
        'type': 'image',
        'mode': 't2i',
        'pipeline': 'flux2_klein',
        'vram_gb': 13,
        'disk_gb': 16,
        'resolution': 1024,
        'description': 'FLUX.2 Klein 4B — ultra-rapide (<1 s), Apache 2.0',
        'description_long': "FLUX.2 Klein 4B (Black Forest Labs) : version distillée ultra-rapide "
                            "de FLUX.2 — image en moins d'une seconde, licence Apache 2.0. Parfait "
                            "pour itérer sur des idées avant un rendu final sur un modèle lourd.",
        'license': 'apache-2.0',
        'default_guidance_scale': 1.0,
        'default_steps': 4,
    },
}

# =============================================================================
# LOGO GENERATION MODELS
# =============================================================================

LOGO_MODELS = {
    # Shakker-Labs FLUX Logo Design LoRA — best open-source logo model (2025-2026)
    # HF benchmark #1 for local logo generation. Replaces logo-redmond-v2 and amazing-logos-v2.
    'flux-lora-logo-design': {
        'model_id': 'flux-lora-logo-design',
        'hf_id': 'Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design',
        'base_model': 'black-forest-labs/FLUX.1-dev',
        'type': 'image',
        'pipeline': 'flux',
        'model_type': 'lora',
        'category': 'logo',
        'trigger_words': ['wablogo', 'logo', 'Minimalist'],
        'lora_scale': 0.8,
        # LoRA sur FLUX.1-dev : c'est la DORSALE qui coûte (12B en bf16 ≈ 24 Go), pas la LoRA.
        # 16 sous-estimait la base — d'où le `vram_warning` « max 768 px avec MODEL_OFFLOAD ».
        'vram_gb': 24,
        'disk_gb': 24,
        'resolution': 768,
        'min_resolution': 512,
        'max_resolution': 768,
        # FLUX uses rectified flow — guidance_scale 3.5–7.5 (NOT 7.5–20 like SD)
        'default_guidance_scale': 3.5,
        'default_steps': 24,
        'license': 'flux-1-dev-non-commercial',
        'description': 'FLUX Logo Design LoRA — logos pro, open-source, max 768 px',
        'description_long': "FLUX Logo Design (Shakker-Labs) : LoRA spécialisé création de logos "
                            "professionnels sur base FLUX, réglages dédiés appliqués "
                            "automatiquement. Référence open-source du domaine.",
        'prompt_tips': [
            'Dual Combination: "wablogo, Minimalist, Dual Combination: mountain and coffee cup"',
            'Font Combination: "wablogo, logo, Minimalist, Font Combination: rocket with letter S"',
            'Text below: "wablogo, Minimalist, coffee bean icon, Text Below Graphic: word \'BREW\'"',
            'guidance_scale recommandé : 3.5 (FLUX — pas 7.5 ni 20)',
        ],
    },
}

# =============================================================================
# FLUX BASE MODELS
# =============================================================================

FLUX_MODELS = {
    # FLUX.1-dev est DÉJÀ sur disque (31,4 GiB, dossier diffusion/flux/) depuis l'ajout du LoRA
    # logo, qui s'en sert comme `base_model`. Il n'était pourtant exposé NULLE PART comme modèle
    # sélectionnable : 31 GiB de poids de premier plan inaccessibles à l'utilisateur.
    # Aucun téléchargement ni code backend requis — `_load_flux_pipeline()` saute l'application
    # du LoRA dès que model_type != 'lora' (diffusers_backend.py:526).
    'flux-1-dev': {
        'model_id': 'flux-1-dev',
        'hf_id': 'black-forest-labs/FLUX.1-dev',
        'base_model': 'black-forest-labs/FLUX.1-dev',
        'type': 'image',
        'mode': 'text-to-image',
        'pipeline': 'flux',
        'model_type': 'base',
        # 12B en bf16 ≈ 24 Go de poids + encodeur T5. 16 sous-estimait la dorsale.
        'vram_gb': 24,
        'disk_gb': 32,
        'resolution': '1024x1024',
        # FLUX = rectified flow : guidance 3.5, JAMAIS 7.5-20 comme SD (cf. LOGO_MODELS)
        'default_guidance_scale': 3.5,
        'default_steps': 28,
        'license': 'flux-1-dev-non-commercial',
        'description': 'FLUX.1-dev — adhérence au prompt de référence',
        'description_long': (
            "FLUX.1-dev (Black Forest Labs, 12B) : référence open-weights pour l'adhérence au "
            "prompt et l'esthétique générale. Déjà présent localement — il servait uniquement de "
            "modèle de base au LoRA logo. Rectified flow : guidance 3.5 et ~28 étapes. "
            "Licence non commerciale (recherche/usage interne)."
        ),
    },
}

# =============================================================================
# COMBINED DICTIONARY
# =============================================================================

IMAGER_MODELS = {
    **HUNYUAN_MODELS,
    **COGVIDEOX_MODELS,
    **LTX_MODELS,
    **MOCHI_MODELS,
    **STABLE_DIFFUSION_MODELS,
    **QWEN_IMAGE_MODELS,
    **FLUX_MODELS,
    **FLUX2_KLEIN_MODELS,
    **LOGO_MODELS,
}


# =============================================================================
# VRAM D'EXÉCUTION — RÉALIGNEMENT SUR LA SOURCE UNIQUE
# =============================================================================
# Les `vram_gb` déclarés ci-dessus étaient une SECONDE déclaration du même fait, et ils avaient
# dérivé : qwen-image-2 annonçait 16 Go pour 38 MESURÉS, flux-1-dev 16 pour 24. Conséquence
# concrète : le catalogue (et donc l'UI, et le tirage) croyait que ces modèles tenaient sur une
# 4090, alors que la couche mémoire savait le contraire — d'où des offloads « inexplicables »
# côté utilisateur, et pire, des tentatives de FULL_GPU sur un modèle 38 Go (crash 29/07).
#
# 🔴 C'EST ICI QUE LE CHIFFRE FAIT FOI — ce fichier est le manifeste des modèles imager :
# `model_registry._discover_imager_models()` l'ingère tel quel dans le catalogue `AIModel`,
# et c'est le catalogue qui alimente le tirage (`select_model`) et l'UI. Un `vram_gb` faux ici
# se propage à toute la chaîne.
#
# `MODEL_SIZE_PRESETS` (memory_manager) est une heuristique de repli qui devine une taille à
# partir d'un CHEMIN de modèle : elle est indexée par familles ('qwen-image', 'flux'…), pas par
# id de modèle. Elle ne peut donc PAS écraser le manifeste — elle est moins précise (elle ne
# distingue pas la variante fp8 d'un modèle de sa version pleine).
#
# On ne recopie donc rien : on VÉRIFIE seulement que les deux tables ne se contredisent pas,
# et on le signale. C'est cette contradiction, restée silencieuse, qui a produit le crash du
# 29/07/2026 (manifeste 16 Go / mesure 38 Go pour Qwen-Image).
def _check_vram_consistency() -> dict:
    """Écarts manifeste ↔ presets : {model_id: (déclaré, preset)}. Ne modifie RIEN."""
    try:
        from wama.model_manager.services.memory_manager import preset_vram_gb
    except Exception:          # pragma: no cover — jamais bloquant au démarrage
        return {}
    drift = {}
    for model_id, cfg in IMAGER_MODELS.items():
        preset = preset_vram_gb(model_id)
        declared = cfg.get('vram_gb')
        # Seul un écart SIGNIFICATIF compte : le preset est une estimation de famille, il est
        # normal qu'une variante (fp8, distilled) s'en écarte un peu.
        if preset is not None and declared is not None and abs(float(declared) - preset) > 4.0:
            drift[model_id] = (declared, preset)
    return drift


VRAM_DRIFT = _check_vram_consistency()
if VRAM_DRIFT:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "[ImagerModels] vram_gb du manifeste s'écarte des presets mémoire — À ARBITRER "
        "(le manifeste fait foi, mais un écart signale une mesure non reportée) : %s",
        ", ".join(f"{k} manifeste={a} preset={b}" for k, (a, b) in VRAM_DRIFT.items())
    )

# =============================================================================
# DÉFAUTS D'APPLICATION — SOURCE UNIQUE
# =============================================================================
# Avant : l'id du modèle par défaut était écrit EN DUR dans 5 vues (views.py 197, 247, 324,
# 389, 1262 = 'stable-diffusion-v1-5', un modèle de 2022) — donc tout utilisateur qui ne
# choisissait pas explicitement recevait le plus faible modèle du parc. On centralise ici pour
# que le défaut se change en UN point, et jamais par recopie dans une vue.
# ⚠️ Ce n'est PAS le tirage : depuis le 29/07/2026 le modèle est choisi par la brique commune
# `select_model()` (cf. `utils/model_selection.py::select_imager_model`), qui connaît la VRAM
# libre. Ces constantes ne servent plus que de REPLI (catalogue vide, model_manager KO).
# Elles doivent donc tenir sur la carte : un repli qui déborde redonne de l'offload subi.
# Qwen-Image-2 tenait ce rôle jusque-là — 38 Go mesurés pour un MMDiT 20B, soit offload garanti
# sur 24 Go. Il reste parfaitement sélectionnable à la main (l'offload devient un choix).
DEFAULT_IMAGE_MODEL = 'hunyuan-image-2.1'   # 16 Go + 4 de marge = 20 ≤ 24 → FULL_GPU
# T2V : LTX-13B-distilled remplace CogVideoX-5b (2024, 21 GB VRAM) — plus récent, 14 GB VRAM
# (8 en fp8) et déjà sur disque. CogVideoX-5b T2V a été retiré du parc local (vague 2).
DEFAULT_VIDEO_MODEL = 'ltx-video-13b-0.9.8-distilled'
# I2V : CogVideoX-5b-I2V CONSERVÉ — seule capacité image→vidéo du parc, et effectivement
# utilisée pour animer des images. Dépôt HF distinct du T2V : le retrait de l'un n'affecte
# pas l'autre.
DEFAULT_I2V_MODEL = 'cogvideox-5b-i2v'


def get_model_defaults(model_id: str) -> dict:
    """
    Paramètres de génération par défaut D'UN MODÈLE, lus depuis sa déclaration.

    Évite le second piège des défauts en dur : 512x512 / 30 étapes / guidance 7.5 sont les
    valeurs de l'ère SD 1.5 et donnent de mauvais résultats sur un modèle 1024 px en rectified
    flow (Qwen, FLUX). Les vues doivent appeler ceci plutôt que d'écrire des littéraux.

    Retourne : {'width', 'height', 'steps', 'guidance_scale'}.
    """
    cfg = IMAGER_MODELS.get(model_id) or {}

    # ⚠ La clé 'resolution' a DEUX formalismes dans les déclarations existantes :
    #   - str 'LxH'  (vidéo : '720x480', '1216x704') → résolution de travail exacte
    #   - int  N     (image : 2048 pour qwen, 1024 pour klein, 768 pour le logo) → côté MAXIMUM
    #     supporté, pas un défaut : générer du 2048x2048 par défaut serait lent et hasardeux.
    # On les distingue ici plutôt que de laisser un parse rater en silence. (Uniformiser les
    # déclarations serait le vrai correctif — hors périmètre de cette passe.)
    resolution = cfg.get('resolution')
    width = height = 512
    if isinstance(resolution, str) and 'x' in resolution.lower():
        try:
            width, height = (int(v) for v in resolution.lower().split('x', 1))
        except (ValueError, TypeError):
            width = height = 512
    elif isinstance(resolution, (int, float)) and resolution > 0:
        # Côté max déclaré → on plafonne le DÉFAUT à 1024 (natif de tous les modèles récents).
        width = height = min(int(resolution), 1024)

    return {
        'width': width,
        'height': height,
        'steps': int(cfg.get('default_steps') or 30),
        'guidance_scale': float(cfg.get('default_guidance_scale') or 7.5),
    }


# =============================================================================
# ENVIRONMENT SETUP HELPERS
# =============================================================================

def setup_hf_cache_for_model(cache_dir: str) -> None:
    """
    Set HuggingFace cache environment variables for a specific model directory.

    Call this BEFORE any import of transformers / diffusers / huggingface_hub
    to ensure ALL downloads (weights, tokenizer, configs) go to the right place.

    Args:
        cache_dir: Absolute path string to the model's dedicated directory.
    """
    os.environ['HF_HUB_CACHE'] = cache_dir
    os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir


def setup_hf_cache_for_hunyuan() -> str:
    """Setup HuggingFace cache for Hunyuan models. Returns the cache dir."""
    cache_dir = str(HUNYUAN_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_cogvideox() -> str:
    """Setup HuggingFace cache for CogVideoX models. Returns the cache dir."""
    cache_dir = str(COGVIDEOX_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_ltx() -> str:
    """Setup HuggingFace cache for LTX models. Returns the cache dir."""
    cache_dir = str(LTX_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_mochi() -> str:
    """Setup HuggingFace cache for Mochi models. Returns the cache dir."""
    cache_dir = str(MOCHI_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_qwen_image() -> str:
    """Setup HuggingFace cache for Qwen Image models. Returns the cache dir."""
    cache_dir = str(QWEN_IMAGE_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_flux2_klein() -> str:
    """Setup HuggingFace cache for FLUX.2 Klein models. Returns the cache dir."""
    cache_dir = str(FLUX2_KLEIN_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


# =============================================================================
# QUERY HELPERS
# =============================================================================

def get_model_info(model_name: str) -> dict:
    """
    Get model information including its dedicated cache directory.

    Args:
        model_name: Model ID from IMAGER_MODELS

    Returns:
        Dictionary with model configuration + cache_dir key
    """
    if model_name not in IMAGER_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(IMAGER_MODELS.keys())}")

    info = IMAGER_MODELS[model_name].copy()

    if model_name in HUNYUAN_MODELS:
        info['cache_dir'] = str(HUNYUAN_DIR)
    elif model_name in COGVIDEOX_MODELS:
        info['cache_dir'] = str(COGVIDEOX_DIR)
    elif model_name in LTX_MODELS:
        info['cache_dir'] = str(LTX_DIR)
    elif model_name in MOCHI_MODELS:
        info['cache_dir'] = str(MOCHI_DIR)
    elif model_name in QWEN_IMAGE_MODELS:
        info['cache_dir'] = str(QWEN_IMAGE_DIR)
    elif model_name in FLUX_MODELS:
        info['cache_dir'] = str(FLUX_DIR)
    elif model_name in FLUX2_KLEIN_MODELS:
        info['cache_dir'] = str(FLUX2_KLEIN_DIR)
    elif model_name in LOGO_MODELS:
        info['cache_dir'] = str(FLUX_DIR) if info.get('pipeline') == 'flux' else str(LOGO_DIR)
    else:
        info['cache_dir'] = str(STABLE_DIFFUSION_DIR)

    return info


def list_available_models() -> dict:
    """List all available imager models grouped by family."""
    return {
        'hunyuan': HUNYUAN_MODELS,
        'cogvideox': COGVIDEOX_MODELS,
        'ltx': LTX_MODELS,
        'mochi': MOCHI_MODELS,
        'stable_diffusion': STABLE_DIFFUSION_MODELS,
        'qwen_image': QWEN_IMAGE_MODELS,
        'flux2_klein': FLUX2_KLEIN_MODELS,
        'logo': LOGO_MODELS,
    }


def get_video_models() -> dict:
    """Get all video generation models."""
    return {
        **COGVIDEOX_MODELS,
        **LTX_MODELS,
        **MOCHI_MODELS,
    }


def get_image_models() -> dict:
    """Get all image generation models (excluding logo and video)."""
    return {
        **HUNYUAN_MODELS,
        **STABLE_DIFFUSION_MODELS,
        **QWEN_IMAGE_MODELS,
        **FLUX2_KLEIN_MODELS,
    }


def get_hunyuan_directory() -> Path:
    return Path(HUNYUAN_DIR)


def get_stable_diffusion_directory() -> Path:
    return Path(STABLE_DIFFUSION_DIR)


def get_cogvideox_directory() -> Path:
    return Path(COGVIDEOX_DIR)


def get_ltx_directory() -> Path:
    return Path(LTX_DIR)


def get_mochi_directory() -> Path:
    return Path(MOCHI_DIR)


def get_flux_directory() -> Path:
    return Path(FLUX_DIR)


def get_logo_directory() -> Path:
    return Path(LOGO_DIR)


def get_qwen_image_directory() -> Path:
    return Path(QWEN_IMAGE_DIR)


def get_flux2_klein_directory() -> Path:
    return Path(FLUX2_KLEIN_DIR)


def get_logo_models() -> dict:
    return LOGO_MODELS


def is_logo_model(model_name: str) -> bool:
    return model_name in LOGO_MODELS


def is_lora_model(model_name: str) -> bool:
    if model_name not in IMAGER_MODELS:
        return False
    return IMAGER_MODELS[model_name].get('model_type') == 'lora'


def get_model_trigger_words(model_name: str) -> list:
    if model_name not in IMAGER_MODELS:
        return []
    return IMAGER_MODELS[model_name].get('trigger_words', [])


def get_model_prompt_tips(model_name: str) -> list:
    if model_name not in IMAGER_MODELS:
        return []
    return IMAGER_MODELS[model_name].get('prompt_tips', [])
