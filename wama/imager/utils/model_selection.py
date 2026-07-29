"""
Tirage du modèle imager — ADOPTION de la brique commune `select_model()` (model_manager).

Chaîne complète, sans logique propre à l'app :

    manifeste (`model_config.IMAGER_MODELS`)
        → ingest (`model_registry._discover_imager_models` → catalogue `AIModel`)
            → tirage (`model_manager.services.select_model`)
                → application (vues / tâches)

Avant (2026-07-29), l'imager n'avait AUCUN tirage : la vue prenait `DEFAULT_IMAGE_MODEL`, une
constante en dur. Elle pointait sur `qwen-image-2` — 38 Go mesurés, donc **offload CPU garanti**
sur une RTX 4090 pour tout utilisateur qui ne choisissait pas explicitement. C'est exactement ce
que `select_model()` sait éviter : il connaît la VRAM libre et le budget.

Le seul apport de ce module est de traduire « je ne veux pas d'offload » en un **budget** :
`select_model()` retient le plus gros modèle qui rentre dans le budget qu'on lui donne — donc en
lui passant `VRAM libre − marge`, on obtient le meilleur modèle qui tourne **entièrement sur le
GPU**. Aucune règle de sélection n'est réécrite ici.
"""

import logging
from typing import Optional

from .model_config import (
    DEFAULT_I2V_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, IMAGER_MODELS,
)

logger = logging.getLogger(__name__)

# Marge laissée libre sur la carte pendant une génération (activations, fragmentation,
# décodage VAE). Même valeur que `MemoryManager.get_memory_strategy()` : en dessous, la couche
# mémoire bascule en MODEL_OFFLOAD — donc viser au-delà, c'est viser un offload évitable.
FULL_GPU_HEADROOM_GB = 4.0

# Le catalogue `AIModel` préfixe ses clés par la source (`imager:qwen-image-2`).
_CATALOG_PREFIX = 'imager:'

# Repli si le catalogue est vide (première installation, sync jamais lancé) ou si le
# model_manager est indisponible. Ces trois-là tiennent sur 24 Go.
_FALLBACK = {
    'image': DEFAULT_IMAGE_MODEL,
    'video': DEFAULT_VIDEO_MODEL,
    'i2v': DEFAULT_I2V_MODEL,
}


def _budget_gb(avoid_offload: bool) -> Optional[float]:
    """VRAM utilisable pour tenir ENTIÈREMENT sur le GPU, ou None (= laisser select_model décider)."""
    if not avoid_offload:
        return None
    try:
        from wama.common.services.resource_governor import effective_free_gb
        free = effective_free_gb()
    except Exception:
        return None
    if not free:
        return None
    return max(0.0, free - FULL_GPU_HEADROOM_GB)


def _fits_kind(cfg: dict, kind: str) -> bool:
    """
    Ce modèle du manifeste sait-il faire CE travail ? Lu sur les métadonnées déclarées
    (`type`, `mode`, `model_type`, `category`) — aucune liste de noms en dur.

    ⚠️ Les LoRA spécialisées sont EXCLUES du tirage générique : sans ce filtre, une demande
    « une image de … » pouvait tirer `flux-lora-logo-design`, qui n'a de sens que sur une
    demande de logo. Une spécialité se choisit, elle ne se tire pas.
    """
    if cfg.get('model_type') == 'lora' or cfg.get('category') == 'logo':
        return False
    mode = str(cfg.get('mode', ''))
    if kind == 'i2v':
        return cfg.get('type') == 'video' and 'image-to-video' in mode
    if kind == 'video':
        return cfg.get('type') == 'video' and mode != 'image-to-video'
    return cfg.get('type') == 'image'


def select_imager_model(kind: str = 'image', requested: Optional[str] = None,
                        avoid_offload: bool = True) -> str:
    """
    Modèle à utiliser pour une génération.

    Args:
        kind:          'image', 'video' (text-to-video) ou 'i2v' (image-to-video).
        requested:     choix explicite de l'utilisateur. Respecté TEL QUEL — y compris s'il
                       impose un offload : c'est alors un choix assumé, pas une surprise.
        avoid_offload: ne tirer que parmi les modèles qui tiennent entièrement sur le GPU.

    Returns:
        Un `model_id` du manifeste.
    """
    if requested and requested not in ('', 'auto'):
        return requested

    fallback = _FALLBACK.get(kind, DEFAULT_IMAGE_MODEL)

    candidates = [mid for mid, cfg in IMAGER_MODELS.items() if _fits_kind(cfg, kind)]
    if not candidates:
        return fallback

    try:
        from wama.model_manager.services import select_model
    except Exception as exc:
        logger.debug("[ImagerSelect] model_manager indisponible (%s) → défaut %s", exc, fallback)
        return fallback

    try:
        chosen = select_model(
            source='imager',
            # ⚠️ Le catalogue préfixe ses clés par la source (`imager:qwen-image-2`), alors que
            # le manifeste et les vues manipulent l'id nu (`qwen-image-2`). Sans ce préfixe le
            # filtre `model_key__in` ne matche RIEN et le tirage retombe silencieusement sur le
            # défaut — il a l'air de fonctionner, mais il ne tire pas.
            candidates=[f'{_CATALOG_PREFIX}{mid}' for mid in candidates],
            prefer_loaded=True,                  # keep_loaded : réutilise un modèle déjà résident
            vram_budget_gb=_budget_gb(avoid_offload),
        )
    except Exception as exc:
        logger.debug("[ImagerSelect] select_model a échoué (%s) → défaut %s", exc, fallback)
        return fallback

    if chosen is None:
        # Aucun modèle ne tient sans offload : plutôt que de refuser, on rend la main au défaut
        # (il fonctionnera, avec offload) — mais on le DIT, sinon la lenteur reste inexpliquée.
        logger.info(
            "[ImagerSelect] aucun modèle '%s' ne tient dans le budget GPU → %s (offload probable)",
            kind, fallback)
        return fallback

    model_id = chosen.model_key.removeprefix(_CATALOG_PREFIX)
    logger.info("[ImagerSelect] %s → %s (%s Go)", kind, model_id, chosen.vram_gb)
    return model_id
