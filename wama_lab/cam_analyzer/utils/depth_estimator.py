"""
Estimation de profondeur monoculaire pour cam_analyzer — SQUELETTE INERTE (préparation).

Piste EXPLORATOIRE documentée dans `CAM_ANALYZER_CHAINE_TRAITEMENT.md` §[E]. Ce module pose le
CONTRAT d'intégration (chargement modèle VRAM-aware + surface d'inférence) SANS aucune inférence
ni téléchargement de poids : `load()`/`estimate_depth()` lèvent `NotImplementedError` tant que le
PoC (usage 4 — re-calage du plan de sol, validé sur la métrique `placement_spread`) n'est pas
décidé et chiffré. Rien dans le pipeline ne l'importe ; le flag ⚑ `depth_estimation` (défaut OFF)
en est le portillon maître.

Modèle candidat : `depth-anything/DA3METRIC-LARGE` (métrique, Apache-2.0). Voir §[E].

⚠ Frontières (partition multi-instances 2026-08-05) — À FAIRE au VRAI onboarding, PAS ici :
  - `wama/settings.py::MODEL_PATHS['vision']['depth']` (le DIR ci-dessous a déjà un fallback) ;
  - déclaration DA3 dans `model_manager/services/model_registry.py` + catalogue `AIModel`
    → territoire session « catalogue » : DEMANDER la déclaration, ne pas y toucher ;
  - la tâche `depth-estimation` est DÉJÀ déclarée (`ModelTask`) ; reste un protocole dans
    `PROTOCOLES` pour que `manage.py bench --task depth-estimation` tourne (phase validation).
⚠ GPU interdit sous WSL2 sur ce poste (crashs hôte) : toute inférence tourne côté runtime/R760xa.

Contrat cible (à porter vers `wama/common/backends/base.py::BaseModelBackend` une fois stabilisé,
en gardant le keep_loaded + réservation gouverneur du patron `yolopv2_segmenter`/`sam3_road_analyzer`) :
  load()                     → charge le modèle (HF_HUB_CACHE posé AVANT import, cache_dir passé) ;
  estimate_depth(frame_bgr)  → carte de profondeur métrique HxW (float32, mètres) ;
  unload()                   → libère la VRAM (gouverneur).
"""
from __future__ import annotations

from django.conf import settings

# « Path d'abord, env vars ensuite, import après » (CLAUDE.md §Ajout d'un nouveau modèle AI).
# Fallback tant que l'entrée settings.py MODEL_PATHS['vision']['depth'] n'est pas ajoutée.
DEPTH_MODEL_ID = 'depth-anything/DA3METRIC-LARGE'  # métrique, Apache-2.0 (cf. §[E])
DEPTH_MODEL_DIR = (settings.MODEL_PATHS.get('vision', {}).get('depth')
                   or settings.AI_MODELS_DIR / "models" / "vision" / "depth-anything-3")

_MODEL = None  # keep_loaded — patron cam_analyzer (yolopv2_segmenter, sam3_road_analyzer)


def is_available() -> bool:
    """Squelette inerte : aucune inférence disponible tant que le PoC n'est pas câblé."""
    return False


def load():
    """SQUELETTE — pose le contrat de chargement VRAM-aware, NE CHARGE RIEN encore.

    Pattern obligatoire au vrai câblage (CLAUDE.md §Ajout d'un nouveau modèle AI) ::

        import os
        cache = str(DEPTH_MODEL_DIR)
        os.environ['HF_HUB_CACHE'] = cache
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache        # AVANT tout import HF
        from transformers import AutoModelForDepthEstimation, AutoImageProcessor
        model = AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL_ID, cache_dir=cache, ...)

    + réservation VRAM via `common/services/resource_governor` (comme `yolopv2_segmenter`).
    """
    raise NotImplementedError(
        "depth_estimator.load : squelette inerte (préparation). PoC usage 4 non câblé — "
        "voir CAM_ANALYZER_CHAINE_TRAITEMENT.md §[E]. Décision + chiffrage requis avant code.")


def estimate_depth(frame_bgr):
    """SQUELETTE — surface d'inférence cible : carte de profondeur métrique HxW (mètres, float32).

    Usage 4 (premier PoC) : le nuage de points reconstruit ré-estime le plan de sol pour
    attaquer le biais d'homographie (23,5 m pinhole vs 6,8 m homographie, cf. §[E]/[3]), puis
    l'A/B se tranche sur `placement_spread` (étalement monde des stationnés).
    """
    raise NotImplementedError(
        "depth_estimator.estimate_depth : non implémenté (piste exploratoire §[E]).")


def unload():
    """SQUELETTE — libèrera la VRAM (gouverneur) au vrai câblage."""
    global _MODEL
    _MODEL = None
