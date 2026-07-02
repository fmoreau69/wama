"""
Sélection intelligente de modèles — centralisée pour toutes les apps WAMA.

S'appuie sur le catalogue `AIModel` (source de vérité : téléchargé ? chargé ? VRAM,
capacités via `capabilities` — canonique ; `extra_info` = opérationnel/transition) et la
VRAM live (`memory_monitor`). Unifie les logiques
jusque-là dupliquées par app (anonymizer `ModelSelector`, transcriber `manager`, et le
`backend_selector` VRAM-aware qui était planifié).

Principe : model_manager = cerveau + source de vérité ; les apps appellent ce service
(ou en font de fins adaptateurs). Voir `memory/project_model_manager_centralization.md`.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_free_vram_gb() -> Optional[float]:
    """VRAM libre (Go) du GPU le plus libre, ou None si indéterminable."""
    try:
        from .memory_monitor import WAMAMemoryMonitor
        gpus = WAMAMemoryMonitor().get_gpu_usage()
        if gpus:
            return max((g.free_gb for g in gpus), default=None)
    except Exception as e:
        logger.debug(f"[model_selector] free VRAM indéterminable : {e}")
    return None


def _supports(model, requires, classes) -> bool:
    """Filtre capacités via `capabilities` (source canonique) — `requires` = clés truthy ;
    `classes` ⊆ capabilities['classes'].

    Réconciliation C1 (REMOVAL_LEDGER F3) : `capabilities` est LA source (lue aussi par WamaModelCaps,
    lang_routing, get_registry_models). `extra_info` = repli de TRANSITION (ancien emplacement, +
    l'alias historique `class_list` des modèles YOLO) tant que la découverte n'a pas tout basculé.
    """
    caps = model.capabilities or {}
    ei = model.extra_info or {}
    if requires and not all(caps.get(k) or ei.get(k) for k in requires):
        return False
    if classes:
        supported = set(caps.get('classes') or ei.get('classes') or ei.get('class_list') or [])
        if not set(classes).issubset(supported):
            return False
    return True


def _best_by_vram(models, budget_gb: Optional[float]):
    """
    Parmi `models`, choisir le meilleur compromis qualité/VRAM :
      - déjà chargé prioritaire (tuple de tri),
      - sinon le plus « gros » (vram_gb) qui TIENT dans le budget (meilleure qualité sans OOM),
      - si rien ne tient, le plus léger (meilleure chance de charger).
    """
    if budget_gb is None:
        return max(models, key=lambda m: (m.is_loaded, m.vram_gb or 0))
    fit = [m for m in models if (m.vram_gb or 0) <= budget_gb]
    if fit:
        return max(fit, key=lambda m: (m.is_loaded, m.vram_gb or 0))
    return min(models, key=lambda m: (m.vram_gb or 0))


def select_model(
    source: str,
    *,
    model_type: Optional[str] = None,
    requires: Optional[List[str]] = None,
    classes: Optional[List[str]] = None,
    prefer_loaded: bool = True,
    downloaded_only: bool = True,
    vram_budget_gb: Optional[float] = None,
    candidates: Optional[List[str]] = None,
    name_contains: Optional[str] = None,
    priority: Optional[List[str]] = None,
    availability_probe=None,
):
    """
    Choisit le meilleur `AIModel` pour `source` (valeur ModelSource), ou None.

    Args:
        source:          app/source ('transcriber', 'anonymizer', 'imager', …).
        model_type:      filtre ModelType ('speech', 'vision', …).
        requires:        capacités requises (clés truthy de `capabilities` ; repli `extra_info`).
        classes:         classes à couvrir (⊆ `capabilities['classes']` — ex. anonymizer).
        prefer_loaded:   si un candidat est déjà chargé (is_loaded), le renvoyer d'office
                         (règle keep_loaded — évite un rechargement coûteux en batch).
        downloaded_only: ne considérer que les modèles téléchargés.
        vram_budget_gb:  budget VRAM explicite ; si None, lecture de la VRAM libre live.
        candidates:      restreindre à une liste de model_key.
        name_contains:   sous-chaîne (model_key ou name), insensible à la casse.
        priority:        ordre de préférence (sous-chaînes de model_key/name). Si fourni,
                         DOMINE la VRAM : le 1er palier de priorité ayant des candidats
                         l'emporte (utile aux apps « par moteur » à défaut délibéré, ex.
                         Transcriber whisper-first — ≠ logique VRAM-greedy).
        availability_probe: callable(AIModel)->bool — disponibilité RUNTIME au-delà du
                         catalogue (ex. import Python réellement possible). Permet de
                         couvrir les apps « backend-class » sans se fier au seul
                         is_downloaded du catalogue.

    Returns:
        AIModel | None.
    """
    from ..models import AIModel

    qs = AIModel.objects.filter(source=source, is_available=True)
    if downloaded_only:
        qs = qs.filter(is_downloaded=True)
    if model_type:
        qs = qs.filter(model_type=model_type)
    if candidates:
        qs = qs.filter(model_key__in=candidates)

    models = list(qs)
    if name_contains:
        nc = name_contains.lower()
        models = [m for m in models if nc in m.model_key.lower() or nc in (m.name or '').lower()]

    models = [m for m in models if _supports(m, requires, classes)]

    # Disponibilité runtime (au-delà du catalogue) : ex. l'import Python du backend.
    if availability_probe:
        def _probe(m):
            try:
                return bool(availability_probe(m))
            except Exception as e:
                logger.debug(f"[model_selector] probe a échoué pour {m.model_key}: {e}")
                return False
        models = [m for m in models if _probe(m)]

    if not models:
        logger.info(f"[model_selector] aucun modèle pour source={source} "
                    f"(type={model_type}, classes={classes}, requires={requires})")
        return None

    budget = vram_budget_gb if vram_budget_gb is not None else get_free_vram_gb()

    def _pick(pool):
        # keep_loaded prioritaire, puis meilleur compromis VRAM.
        if prefer_loaded:
            loaded = [m for m in pool if m.is_loaded]
            if loaded:
                return _best_by_vram(loaded, budget)
        return _best_by_vram(pool, budget)

    # Priorité explicite : le 1er palier ayant des candidats l'emporte (domine la VRAM).
    if priority:
        for p in priority:
            pl = p.lower()
            tier = [m for m in models if pl in m.model_key.lower() or pl in (m.name or '').lower()]
            if tier:
                choice = _pick(tier)
                logger.info(f"[model_selector] {source} → {choice.model_key} (priorité « {p} »)")
                return choice

    choice = _pick(models)
    logger.info(f"[model_selector] {source} → {choice.model_key} (vram_gb={choice.vram_gb}, budget={budget})")
    return choice


def list_models(source: str, downloaded_only: bool = True) -> List[dict]:
    """Liste des modèles d'une source (dicts to_dict — description courte/longue + vram)."""
    from ..models import AIModel
    qs = AIModel.objects.filter(source=source, is_available=True)
    if downloaded_only:
        qs = qs.filter(is_downloaded=True)
    return [m.to_dict() for m in qs]


def get_registry_models(source: str, allowed_ids=None, downloaded_only: bool = False):
    """
    (choices, info) pour le <select> d'une app, PILOTÉ par le registre AIModel (verrou n°1).

    - choices : [(model_id, nom)]  — model_id = model_key sans le préfixe "source:"
    - info    : [{id, name, description, vram, capabilities, downloaded}]

    `allowed_ids` (optionnel) : restreint aux modèles que le backend sait CHARGER — sécurité,
    on ne propose jamais un modèle non chargeable. Retourne ([], []) si le registre n'a rien
    pour cette source → l'appelant doit alors faire un repli sur sa liste backend.
    """
    from ..models import AIModel
    qs = AIModel.objects.filter(source=source, is_available=True)
    if downloaded_only:
        qs = qs.filter(is_downloaded=True)
    qs = qs.order_by('-vram_gb', 'name')
    choices, info = [], []
    for m in qs:
        mid = m.model_key.split(':', 1)[1] if ':' in m.model_key else m.model_key
        if allowed_ids is not None and mid not in allowed_ids:
            continue
        choices.append((mid, m.name))
        info.append({
            'id': mid,
            'name': m.name,
            'description': m.description_short or m.description or '',
            'vram': f"{int(m.vram_gb)}GB" if m.vram_gb else '',
            'capabilities': m.capabilities or {},
            'downloaded': m.is_downloaded,
        })
    return choices, info


def describe_model(model_key: str, tier: str = 'short') -> str:
    """Description d'un modèle. tier='short' → une ligne (fallback long) ; 'long' → paragraphe."""
    from ..models import AIModel
    m = AIModel.objects.filter(model_key=model_key).first()
    if not m:
        return ''
    if tier == 'long':
        return m.description or m.description_short or ''
    return m.description_short or m.description or ''
