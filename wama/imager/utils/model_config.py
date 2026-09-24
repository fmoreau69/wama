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
#  3. Dans le backend, passer cache_dir=str(MON_MODELE_DIR) à from_pretrained() — c'est
#     la SEULE chose à faire. ⚠ NE JAMAIS muter HF_HUB_CACHE / HF_HOME : ils sont posés UNE
#     FOIS au démarrage (settings.py) vers le cache PARTAGÉ des sous-dépendances.
#     (Cette étape prescrivait encore la mutation jusqu'au 2026-09-14 : la règle avait été
#     retirée d'AGENTS.md le 2026-09-03, ce commentaire était resté en retard.)
#
#  4. Ajouter l'entrée dans IMAGER_MODELS (ou le groupe approprié) avec
#     au minimum : model_id, hf_id, type, mode, vram_gb, description.
#
#  5. Mettre à jour _discover_imager_models() dans model_registry.py.
#
#  Le modèle PRINCIPAL va dans son répertoire (cache_dir=) ; ses SOUS-DÉPENDANCES (t5, bert,
#  tokenizers, backbones…) vont au cache partagé AI-models/cache/huggingface/ — c'est leur
#  place, pas une dérive. Règle complète : AGENTS.md, « ajout d'un nouveau modèle AI ».
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

FASTWAN_DIR = MODEL_PATHS.get('diffusion', {}).get('fastwan',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "FastWan2.2-TI2V-5B-FullAttn-Diffusers")

# Ensure directories exist
for dir_path in [HUNYUAN_DIR, STABLE_DIFFUSION_DIR, COGVIDEOX_DIR, LTX_DIR,
                 MOCHI_DIR, FLUX_DIR, LOGO_DIR, QWEN_IMAGE_DIR, FLUX2_KLEIN_DIR, FASTWAN_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# =============================================================================
# ANATOMIE DÉCLARÉE (`composition`) — ce que le chargeur TIRE, pas ce que le dépôt CONTIENT
# =============================================================================
# POURQUOI (2026-09-19, chantier VRAM décision A — `PROJECT_STATUS §④A`) : un modèle composé a
# DEUX empreintes, la somme de ses composants (plein GPU) et son plus gros composant
# (déchargement). Les deux se dérivent du poids PAR COMPOSANT
# (`model_installer.components_for_spec`), qui a besoin de savoir QUELS fichiers comptent.
#
# 🔴 Et sans cette déclaration, ils sont FAUX — mesuré sur les cartes HF ce jour-là : le dépôt
# de Mochi porte 124,3 Go de poids pour un modèle de 56,8, celui de LTX-distilled 86,4 pour
# 44,3, celui de SDXL 45,7 pour 12,9. Un dépôt HuggingFace est un CATALOGUE : il sert
# plusieurs chargeurs (copie monofichier `dit.safetensors` à côté de `transformer/`),
# plusieurs précisions (`…bf16-00001-of-00003`, `…fp16`), plusieurs moteurs (`openvino_model.bin`,
# `diffusion_flax_model.msgpack`) et parfois un pipeline ENTIER en double
# (`Lightricks/…:vae/model_index.json` — d'où un « vae » de 44 Go si on somme le dossier).
#
# Les motifs ci-dessous désignent le jeu que `from_pretrained()` prend PAR DÉFAUT, c'est-à-dire
# celui que référence l'`*.index.json` du composant (vérifié fichier par fichier) — sans
# `variant=`, donc ni `.fp16` ni `.bf16` ni `.non_ema`. La même déclaration sert à
# l'INSTALLATION (`patterns_from_composition` → `allow_patterns`) : ce qu'on pèse est ce qu'on
# tire, et ça ne peut plus diverger.
#
# ⚠ Ce que la composition NE dit PAS : la précision de CHARGEMENT. `ltx-…-distilled-fp8` est le
# MÊME dépôt que la version pleine — sa quantisation est faite au chargement (torchao), pas
# choisie dans les fichiers. Son anatomie est donc identique ; seul son `vram_gb` diffère.

#: Convention diffusers, lue sur les 11 dépôts du parc : un module `transformers` (encodeur de
#: texte, safety checker) range ses poids sous `model*.safetensors`, un module `diffusers` sous
#: `diffusion_pytorch_model*.safetensors`.
_TRANSFORMERS_ROLES = ('text_encoder', 'safety_checker')


def _weight_pattern(role: str, sharded: bool) -> str:
    """Motif des poids d'un composant. `sharded` : le composant est découpé (`-00001-of-0000N`)."""
    stem = 'model' if role.startswith(_TRANSFORMERS_ROLES) else 'diffusion_pytorch_model'
    return f"{role}/{stem}{'-*' if sharded else ''}.safetensors"


def _pipeline_composition(**roles) -> dict:
    """`composition` d'un pipeline diffusers, au schéma de `manifests.builtin.model`.

    Un rôle vaut `True` (jeu de shards), `False` (fichier unique), ou un MOTIF explicite quand la
    convention ne suffit pas à trancher — cas mesuré : `genmo/mochi-1-preview` porte DEUX jeux de
    shards concurrents dans `text_encoder/` (`-of-00002` et `-of-00004`) que rien dans le nom ne
    distingue ; son `model.safetensors.index.json` désigne le second.
    """
    return {
        'components': [{'role': role,
                        'pattern': spec if isinstance(spec, str) else _weight_pattern(role, spec)}
                       for role, spec in roles.items()],
        'runtime': {'engine': 'diffusers'},
    }


# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

# ─── Hunyuan Image (Tencent) ──────────────────────────────────────────────────
HUNYUAN_MODELS = {
    'hunyuan-image-2.1': {
        'model_id': 'hunyuan-image-2.1',
        'engine': 'diffusers',
        'hf_id': 'hunyuanvideo-community/HunyuanImage-2.1-Diffusers',
        'type': 'image',
        'tasks': 't2i',
        'vram_gb': 16,
        # Relevé 2026-09-19 : transformer 32,46 Go + text_encoder 15,45 + text_encoder_2 0,82
        # + vae 0,76 = 49,5 Go de somme, 32,5 Go de plus gros composant. ⚠ `vram_gb` = 16 est
        # donc sous-déclaré même pour le SEUL transformer — signalé, pas corrigé ici (changer
        # ce chiffre change ce que le tirage propose : décision de Fabien).
        'composition': _pipeline_composition(transformer=True, text_encoder=True,
                                            text_encoder_2=False, vae=False),
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
        'engine': 'diffusers',
        'hf_id': 'THUDM/CogVideoX-5b-I2V',
        'type': 'video',
        'tasks': 'i2v',
        'vram_gb': 21,
        'disk_gb': 12,
        # Relevé 2026-09-19 : transformer 10,48 + text_encoder 8,87 + vae 0,80 = 20,2 Go de
        # somme (≈ le preset 21, qui EST une somme), 10,5 Go de plus gros composant — ce qui
        # confirme le « jeu de travail réel ~11 Go en MODEL_OFFLOAD » écrit dans
        # `memory_manager.MODEL_SIZE_PRESETS`. Le déchargement n'est pas un pis-aller ici.
        'composition': _pipeline_composition(transformer=True, text_encoder=True, vae=False),
        # ⚠ Déclarait `fps: 24` jusqu'au 2026-09-23 alors que la tâche imposait 8 i/s — c'est la
        # DÉCLARATION qui était fausse : la carte du modèle (THUDM/CogVideoX-5b-I2V) annonce
        # 6 s, 8 i/s, 49 images, 720×480. Le code avait raison ; la métadonnée qui remplit l'UI
        # (et l'aide sous le sélecteur) mentait.
        'fps': 8,
        'max_frames': 49,
        'resolution': '720x480',
        'description': 'CogVideoX 5B — Image-to-Video',
        'description_long': "CogVideoX 5B I2V (Zhipu/THUDM) : anime une image de référence en "
                            "clip vidéo guidé par le prompt. Limites du modèle : 6 secondes (49 "
                            "images à 8 i/s), 720×480. Au-delà, la vidéo est prolongée par "
                            "segments enchaînés (chaque segment repart de la dernière image).",
    },
}

# ─── LTX-Video (Lightricks) ───────────────────────────────────────────────────
# Seul repo diffusers disponible pour la 0.9.8 : Lightricks/LTX-Video-0.9.8-13B-distilled
# (pas de repo 0.9.8-dev — utiliser 0.9.7-dev ou attendre la sortie officielle)
LTX_MODELS = {
    # ── 13B Distilled — rapide, haute qualité ────────────────────────────────
    'ltx-video-13b-0.9.8-distilled': {
        'model_id': 'ltx-video-13b-0.9.8-distilled',
        'engine': 'diffusers',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-13B-distilled',
        'type': 'video',
        'tasks': 't2v+i2v',
        'vram_gb': 14,
        'disk_gb': 18,
        # Relevé 2026-09-19 : transformer 24,29 + text_encoder 17,74 + vae 2,32 = 44,3 Go de
        # somme, 24,3 de plus gros composant. ⚠ Ce dépôt porte un pipeline ENTIER en double sous
        # `vae/` (son propre `vae/model_index.json`, 421 o comme celui de la racine) : sommer le
        # dossier `vae/` donnerait 44 Go pour le seul VAE. Le motif exact l'évite.
        'composition': _pipeline_composition(transformer=True, text_encoder=True, vae=False),
        'fps': 24,
        # 257 images (≈ 10,7 s) : la longueur maximale recommandée par Lightricks pour un seul
        # passage ; au-delà, prolongation par segments (le modèle fait aussi image→vidéo).
        'max_frames': 257,
        # CONTINUATION (2026-09-23, décision de Fabien) : au-delà d'un passage, le segment
        # suivant est conditionné par les 25 DERNIÈRES images du précédent (`LTXVideoCondition`
        # vidéo, frame_index 0) — il voit le mouvement, pas une photo figée. 25 = 3×8+1 (la
        # contrainte du VAE temporel de LTX), ≈ 1 s à 24 i/s.
        'continuation_frames': 25,
        'resolution': '1216x704',
        'description': 'LTX-Video 13B Distilled — rapide, T2V + I2V',
        'description_long': "LTX-Video 13B Distilled (Lightricks) : génération vidéo rapide, en "
                            "texte-vers-vidéo comme en image-vers-vidéo. La distillation réduit "
                            "fortement le nombre d'étapes — bon choix par défaut pour itérer vite.",
    },
    # ── 13B Distilled FP8 — meilleur ratio qualité/VRAM sur RTX 4090 ─────────
    'ltx-video-13b-0.9.8-distilled-fp8': {
        'model_id': 'ltx-video-13b-0.9.8-distilled-fp8',
        'engine': 'diffusers',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-13B-distilled',
        'type': 'video',
        'tasks': 't2v+i2v',
        'vram_gb': 8,
        'disk_gb': 18,
        'fps': 24,
        # 161 images (≈ 6,7 s) : plafond MESURÉ de la variante fp8 sur la 4090 (au-delà, OOM du
        # pilote — la tâche le bornait déjà en dur). Une borne de MACHINE, déclarée ici pour que
        # l'écran la connaisse.
        'max_frames': 161,
        'continuation_frames': 25,       # même mécanique que la version pleine
        'resolution': '1216x704',
        'quantization': 'fp8',
        # MÊME dépôt, donc MÊME anatomie que la version pleine ci-dessus : la quantisation fp8
        # est faite AU CHARGEMENT (torchao), aucun fichier fp8 n'existe dans le dépôt (vérifié —
        # 59 fichiers, aucun marqueur fp8). Une composition décrit des FICHIERS ; seul `vram_gb`
        # porte l'écart de précision.
        'composition': _pipeline_composition(transformer=True, text_encoder=True, vae=False),
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
        'engine': 'diffusers',
        'hf_id': 'genmo/mochi-1-preview',
        'type': 'video',
        'tasks': 't2v',
        'vram_gb': 22,
        'disk_gb': 18,
        # Relevé 2026-09-19 : transformer 37,36 + text_encoder 17,74 + vae 1,71 = 56,8 Go de
        # somme, 37,4 de plus gros composant. Le dépôt porte, EN PLUS : une copie monofichier du
        # pipeline (`dit.safetensors` 37,4 + `encoder`/`decoder`), un transformer bf16
        # (`…index.bf16.json` + 3 shards) et un SECOND jeu de shards de text_encoder
        # (`-of-00002`, 8,87 Go) — c'est l'`index.json` qui désigne le jeu `-of-00004`, d'où le
        # motif explicite : la convention seule ne pouvait pas trancher entre les deux.
        'composition': _pipeline_composition(
            transformer=True, text_encoder='text_encoder/model-*-of-00004.safetensors', vae=False),
        'fps': 30,
        # 84 images (2,8 s) : le plafond que la tâche imposait en dur (le modèle en génère 163
        # nativement, mais pas dans la VRAM de cet hôte). Texte→vidéo SEUL : pas de
        # prolongation possible par segments, la durée est donc bornée à l'écran.
        'max_frames': 84,
        'resolution': '848x480',
        'description': 'Mochi-1 Preview — haute qualité',
        'description_long': "Mochi-1 Preview (Genmo) : génération vidéo haute fidélité à 30 "
                            "images/s, mouvements naturels et bonne adhérence au prompt. Le plus "
                            "gourmand des modèles vidéo — à réserver aux rendus soignés.",
    },
}

# ─── Wan (Alibaba) — servi par `wan_video_backend` ────────────────────────────
# FastWan 2.2 TI2V 5B (FastVideo) : Wan 2.2 TI2V 5B distillé DMD, 3 pas sans CFG. Réglages du
# README du dépôt : 1280×704, 121 images, 24 i/s.
# `tasks` = t2v+i2v — le TI2V de son nom est MESURÉ, pas supposé (2026-09-16) : son
# `model_index.json` déclare `expand_timesteps = True`, la branche de diffusers qui conditionne
# par la PREMIÈRE IMAGE encodée au VAE (`pipeline_wan_i2v.py:425`) au lieu de canaux
# supplémentaires — d'où un transformer à 48 canaux pour 48 canaux latents. L'encodeur d'image
# CLIP, absent du dépôt, est un composant OPTIONNEL de ce pipeline : rien ne manque.
# ⚠ `vram_gb` = SOMME des composants comptés par la sonde (~22,8 Go bf16), pas un pic : le
# text_encoder ne sert qu'une fois, le backend tourne en MODEL_OFFLOAD (preset `fastwan`).
# ⚠ Aucune génération GPU encore jouée : le pas DMD reste une hypothèse (`probe_fastwan`).
WAN_MODELS = {
    'fastwan-2.2-ti2v-5b': {
        'model_id': 'fastwan-2.2-ti2v-5b',
        'engine': 'diffusers',
        'hf_id': 'FastVideo/FastWan2.2-TI2V-5B-FullAttn-Diffusers',
        'type': 'video',
        'tasks': 't2v+i2v',
        'vram_gb': 23,
        'disk_gb': 24,
        'fps': 24,
        'max_frames': 121,
        'resolution': '1280x704',
        'default_steps': 3,
        'default_guidance_scale': 1.0,
        'license': 'apache-2.0',
        # Relevé 2026-09-19 : transformer 9,31 + text_encoder 10,58 + vae 2,63 = 22,5 Go de
        # somme — à 1,3 % des ~22,8 Go que `probe_fastwan` avait comptés sur le périphérique
        # `meta`, par une voie entièrement différente (paramètres × 2 octets). Deux mesures
        # indépendantes qui concordent. Et le plus gros composant n'est que 10,6 Go : en
        # déchargement, ce modèle tient largement sur une 4090 — c'est l'encodeur de texte, pas
        # le transformer, qui plafonne.
        'composition': _pipeline_composition(transformer=False, text_encoder=True, vae=False),
        # Les LIMITES (5 s natives, 24 i/s, 1280×704) ne sont PAS recopiées dans la description
        # courte : l'aide sous le sélecteur les DÉRIVE des capacités (`fps`, `max_frames`,
        # `resolution` ci-dessus — `WamaModelHelp`), un seul fait, jamais deux (2026-09-23).
        'description': 'FastWan 2.2 TI2V 5B — distillé 3 pas',
        'description_long': "FastWan 2.2 (FastVideo) : Wan 2.2 TI2V 5B distillé en 3 pas de "
                            "débruitage, pour générer une vidéo à partir d'un texte beaucoup plus "
                            "vite que les modèles non distillés. Limites du modèle : 5 secondes au "
                            "plus en un passage (121 images à 24 i/s — au-delà, la vidéo est "
                            "prolongée par segments enchaînés, chacun repartant de la dernière "
                            "image : la continuité n'est pas garantie), "
                            "cadence fixe de 24 i/s, résolution native 1280×704 (en dessous, la "
                            "qualité baisse). Le nombre de pas, le guidage et donc le prompt "
                            "négatif sont imposés par la distillation (sans effet ici).",
    },
}

# ─── Stable Diffusion (image generation) ─────────────────────────────────────
STABLE_DIFFUSION_MODELS = {
    'stable-diffusion-v1-5': {
        'model_id': 'stable-diffusion-v1-5',
        # Le CHEMIN RÉEL, et non « un des deux » (question Fabien, 2026-09-06). Deux backends
        # déclarent servir ce modèle — `DiffusersBackend` (moteur `diffusers`) et
        # `ImaginAiryBackend` (moteur `imaginairy`) — mais ils ne sont pas à égalité :
        # `BackendManager.BACKEND_PRIORITY = ['diffusers', 'imaginairy']` et « first available
        # will be used ». Les deux sont installés, donc diffusers gagne À L'EXÉCUTION.
        # ImaginAiry est un REPLI hérité, et un repli n'est pas un second moteur : c'est une
        # décision de l'app au lancement, pas une propriété du modèle.
        #
        # ⚠ Sur ses 4 modèles déclarés, imaginairy n'en sert plus qu'UN au catalogue :
        # `openjourney-v4`, `dreamlike-art-2` et `stable-diffusion-2-1` ont été retirés comme
        # obsolètes (cf. AGENTS.md §Supprimés). Sa liste `SUPPORTED_MODELS` est donc périmée
        # aux trois quarts — signalé, pas corrigé : retirer un backend est une décision.
        'engine': 'diffusers',
        'hf_id': 'stable-diffusion-v1-5/stable-diffusion-v1-5',
        'type': 'image',
        'pipeline': 'sd',
        # t2i + image de référence OPTIONNELLE (StableDiffusionImg2ImgPipeline,
        # diffusers_backend._generate_img2img) — nourrit l'appariement entrée↔modèle.
        'tasks': 't2i+i2i',
        'vram_gb': 4,
        # Relevé 2026-09-19, corrigé le 20 : unet 3,20 + text_encoder 0,46 + vae 0,31 = 4,0 Go de
        # somme, 3,2 de plus gros composant — cohérent avec les 4 Go déclarés. Le dépôt porte 4
        # formes de chaque poids (`.bin`, `.fp16.bin`, `.fp16.safetensors`, `.non_ema.*`) : 32,9 Go
        # au total pour 4,0 Go de modèle.
        # ⚠ `safety_checker` RETIRÉ de la déclaration : son `model_index.json` le DÉCLARE, mais
        # aucun poids n'est installé pour lui sur ce disque (la dérivation automatique l'a écarté
        # par la MESURE là où ma liste écrite à la main le gardait, comptant 1,13 Go absent).
        # Contrairement à SDXL, ce dépôt-ci n'a PAS de variante `.fp16` installée : le `variant`
        # demandé par le backend n'existe pas, diffusers retombe sur la pleine précision.
        'composition': _pipeline_composition(unet=False, text_encoder=False, vae=False),
        'description': 'Stable Diffusion 1.5 — classique (compatibilité LoRA)',
        'description_long': "Stable Diffusion 1.5 (Runway/CompVis) : le classique historique de la "
                            "génération d'images, porté par le plus vaste écosystème de LoRA et de "
                            "fine-tunes. Qualité datée en natif, mais base de compatibilité inégalée.",
    },
    'stable-diffusion-xl': {
        'model_id': 'stable-diffusion-xl',
        'engine': 'diffusers',
        'hf_id': 'stabilityai/stable-diffusion-xl-base-1.0',
        'type': 'image',
        'pipeline': 'sdxl',
        # t2i + image de référence OPTIONNELLE (StableDiffusionXLImg2ImgPipeline).
        'tasks': 't2i+i2i',
        'vram_gb': 10,
        # 🔴 CORRIGÉ le 2026-09-20 : la variante FP16, pas la pleine précision. Ma déclaration de
        # la veille désignait `unet/diffusion_pytorch_model.safetensors` (9,56 Go), écrit depuis la
        # CARTE HF — or ce que la machine a sur disque et ce que le backend DEMANDE sont les
        # fichiers `.fp16` : `diffusers_backend.py:304` passe `variant="fp16"` dès que le dtype est
        # float16, ce qui est le cas sur la 4090. Empreinte réelle : unet 4,78 + text_encoder_2
        # 1,29 + text_encoder 0,23 + vae 0,16 = 6,5 Go, et non 12,9.
        # *Le dépôt dit ce qu'on PEUT tirer, le snapshot dit ce qu'on a TIRÉ — et c'est le second
        # que le chargeur ouvre.* C'est la dérivation automatique (`model_anatomy`) qui a relevé
        # l'écart, sur les 10 pipelines installés : 9 déclarations identiques, celle-ci fausse.
        # ⚠ LIMITE ASSUMÉE : l'anatomie décrit la variante que WAMA charge. Changer la politique
        # de dtype (bf16, fp32 sur une carte plus grande) change les fichiers, donc l'anatomie —
        # le schéma `composition` ne sait pas dire « fp16 ici, fp32 là ».
        # ⚠ Non déclarés VOLONTAIREMENT : `vae_1_0` (VAE ALTERNATIF, non chargé par défaut) et
        # les copies OpenVINO (`unet/openvino_model.bin`, `vae_decoder/`, `vae_encoder/`) — un
        # autre moteur, pas un composant de plus.
        'composition': _pipeline_composition(
            unet='unet/diffusion_pytorch_model.fp16.safetensors',
            text_encoder='text_encoder/model.fp16.safetensors',
            text_encoder_2='text_encoder_2/model.fp16.safetensors',
            vae='vae/diffusion_pytorch_model.fp16.safetensors'),
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
        'engine': 'diffusers',
        'hf_id': 'Qwen/Qwen-Image-2512',
        'type': 'image',
        'tasks': 't2i',
        'pipeline': 'qwen_image',
        # 38 Go MESURÉS le 29/07/2026 (annoncé 16 jusque-là). Un MMDiT de 20B en bf16 pèse
        # ~40 Go de poids : 16 était structurellement impossible. Conséquence de l'écart : le
        # backend tentait FULL_GPU sur une carte de 24 Go → débordement en RAM hôte sous WSL2.
        # ⛔ Ne tient PAS sur une RTX 4090 → offload CPU obligatoire (lent, mais fonctionnel).
        'vram_gb': 38,
        'disk_gb': 40,
        # Relevé 2026-09-19 : transformer 38,05 + text_encoder 15,45 + vae 0,24 = 53,7 Go de
        # somme, 38,1 de plus gros composant. ⚠ Les 38 déclarés sont donc le PLUS GROS COMPOSANT,
        # là où le 21 de CogVideoX et le 23 de FastWan sont des SOMMES : les deux définitions
        # coexistent dans les tables, ce que la décision A vient précisément séparer.
        'composition': _pipeline_composition(transformer=True, text_encoder=True, vae=False),
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
        'engine': 'diffusers',
        'hf_id': 'Qwen/Qwen-Image-Edit-2511',
        'type': 'image',
        'tasks': 'edit',
        'pipeline': 'qwen_image',
        # ⚠️ NON MESURÉ — borne prudente. Qwen-Image-Edit partage la dorsale MMDiT 20B de
        # Qwen-Image : les 12 Go déclarés ici à l'origine étaient impossibles. En attendant une
        # mesure, on prend celle de la dorsale (38) : sur-estimer coûte de l'offload,
        # sous-estimer fait tenter FULL_GPU et fait tomber l'hôte. À MESURER.
        'vram_gb': 38,
        'disk_gb': 25,
        # Relevé 2026-09-19 : transformer 38,05 + text_encoder 15,45 + vae 0,24 — EXACTEMENT le
        # même poids que `qwen-image-2` (même dorsale MMDiT 20B, 5 shards au lieu de 9). La borne
        # prudente de 38 ci-dessus était donc juste : c'est maintenant MESURÉ, plus supposé.
        'composition': _pipeline_composition(transformer=True, text_encoder=True, vae=False),
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
        'engine': 'diffusers',
        'hf_id': 'black-forest-labs/FLUX.2-klein-4B',
        'type': 'image',
        'tasks': 't2i',
        'pipeline': 'flux2_klein',
        'vram_gb': 13,
        'disk_gb': 16,
        # Relevé 2026-09-19 : transformer 7,22 + text_encoder 7,49 + vae 0,16 = 14,9 Go de somme,
        # 7,5 de plus gros composant. Le dépôt porte AUSSI `flux-2-klein-4b.safetensors` à la
        # racine, de 7,22 Go — exactement le poids du `transformer/` : c'est la copie monofichier
        # pour les chargeurs qui ne lisent pas l'arborescence diffusers, pas un composant.
        'composition': _pipeline_composition(transformer=False, text_encoder=True, vae=False),
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
        'engine': 'diffusers',
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
        # ⚠ PAS de `composition` ici, VOLONTAIREMENT (2026-09-19). Son dépôt ne contient qu'un
        # fichier de 0,04 Go : une composition le déclarerait, et le poids par composant
        # répondrait « 0,04 Go » — un chiffre exact sur les FICHIERS et faux sur l'EMPREINTE, qui
        # est celle de `base_model` (FLUX.1-dev, 31,4 Go de somme / 22,2 de plus gros composant).
        # Mieux vaut « indéterminable » qu'un chiffre trompeur. Le schéma `composition` n'a pas de
        # champ pour dire « hérite de la dorsale » — c'est une DÉCISION à prendre (héritage
        # d'empreinte pour les adaptateurs), pas un trou à boucher à la va-vite.
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
        'engine': 'diffusers',
        'hf_id': 'black-forest-labs/FLUX.1-dev',
        'base_model': 'black-forest-labs/FLUX.1-dev',
        'type': 'image',
        'tasks': 'text-to-image',
        'pipeline': 'flux',
        'model_type': 'base',
        # 12B en bf16 ≈ 24 Go de poids + encodeur T5. 16 sous-estimait la dorsale.
        'vram_gb': 24,
        'disk_gb': 32,
        # Relevé 2026-09-19 : transformer 22,17 + text_encoder_2 8,87 (T5) + text_encoder 0,23
        # (CLIP) + vae 0,16 = 31,4 Go de somme, 22,2 de plus gros composant. Les 24 déclarés sont
        # la DORSALE seule, comme le dit le commentaire ci-dessus — donc ni la somme (31,4) ni le
        # pic en déchargement (22,2), mais un troisième chiffre. `disk_gb: 32` est juste.
        # La racine porte en plus `flux1-dev.safetensors` (22,17 Go, monofichier) et
        # `ae.safetensors` (le VAE au format original) : deux copies, pas des composants.
        'composition': _pipeline_composition(transformer=True, text_encoder_2=True,
                                            text_encoder=False, vae=False),
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
    **WAN_MODELS,
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

# 🔴 `setup_hf_cache_for_model(cache_dir)` SUPPRIMÉE le 2026-09-03 (`ROADMAP §5b`).
# Son corps entier était :
#     os.environ['HF_HUB_CACHE'] = cache_dir
#     os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir
# — c'était LE goulot du défaut : les six helpers ci-dessous y convergeaient, et deux backends
# (`wan_video_backend`, `hunyuan_video_backend`) l'appelaient AU NIVEAU MODULE. Importer l'un
# de ces fichiers suffisait donc à rediriger le cache HF de TOUT le processus, le dernier
# importé gagnant — la « course » qui justifie le `--workers 1` du service TTS
# (`start_wama_prod.sh:271`). Mesuré le 03/09 : le test de socle passait en isolé et échouait
# dans la suite, `HF_HUB_CACHE` pointant sur `diffusion/wan`.
#
# Il n'y avait rien à remplacer : `HF_HOME`/`HF_HUB_CACHE` sont posés UNE FOIS au démarrage
# (`settings.py`, en `setdefault`) vers le cache PARTAGÉ, et les 4 `from_pretrained` des deux backends
# passent déjà `cache_dir=` — vérifié un par un avant le retrait. Le modèle principal reste
# donc catégorisé ; ses sous-dépendances vont au cache partagé, qui est leur place.
#
# 🔴 LES SIX `setup_hf_cache_for_*` RETIRÉS le 2026-09-14 (`REMOVAL_LEDGER R61`). Depuis le
# 03/09 ils ne faisaient plus que rendre `str(<FAMILLE>_DIR)`, et n'avaient AUCUN appelant dans
# le code VERSIONNÉ — `hunyuan_video_backend` compris (il lit `settings.MODEL_PATHS` lui-même).
# La jumelle de bac à sable `imager_01` (générée, non versionnée) garde sa propre copie. Le chemin d'une famille se lit à sa constante `*_DIR` ci-dessus ; le rangement du
# modèle passe par `cache_dir=` (AGENTS.md, « ajout d'un nouveau modèle AI »). C'étaient six des
# « résolveurs maison » côté chargement que `ROADMAP §5b` demande de réduire.


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
    elif model_name in WAN_MODELS:
        info['cache_dir'] = str(FASTWAN_DIR)
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
        'wan': WAN_MODELS,
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
        **WAN_MODELS,
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
