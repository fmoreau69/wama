"""
Estimateur d'ETA WAMA — *seeding* auto-apprenant et hardware-aware.
================================================================================

Fournit, pour un item à traiter, une estimation a priori du temps restant —
affichée IMMÉDIATEMENT (dès le chargement du modèle) par le composant commun
`WamaEta` (`seedSeconds`), au lieu d'attendre que la progression observée donne
un débit. L'estimation s'AFFINE ensuite seule avec les durées réelles mesurées.

Modèle :   ETA ≈ (chargement à froid si modèle non résident) + per_unit × taille

Sources, par ordre de priorité :
  1. **Apprises** — `ModelRuntimeStat` (EMA des durées réelles), bucketisées par
     empreinte hardware → un changement de GPU repart de l'a-priori et réapprend.
  2. **A-priori par modèle** — `AIModel.extra_info['eta']` (calibrable à la main /
     par le test nocturne) : { unit, load_seconds, per_unit_seconds }.
  3. **A-priori par domaine** — table grossière ci-dessous (suffisant en 1ʳᵉ utilisation).

Couplage model_manager : `model_key = "{source}:{model_id}"` (cf. AIModel).

L'API est défensive : aucune exception ne remonte vers les tâches/vues des apps
(en cas de souci on renvoie 0 → WamaEta n'affiche simplement pas de seed).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Lissage EMA : poids des runs récents (s'adapte à la dérive sans surréagir au bruit).
_EMA_ALPHA = 0.3

# A-priori GROSSIER par unité de domaine (1ʳᵉ utilisation d'un modèle, avant tout apprentissage).
# per_unit = secondes de CALCUL par unité ; load = chargement à froid du modèle.
_DEFAULT_PER_UNIT = {
    'audio_sec':  0.25,   # ASR ~4× temps réel
    'video_sec':  6.0,    # génération vidéo : ~6 s de calcul par s produite
    'megapixel':  5.0,    # génération image
    'step':       1.2,    # un pas de diffusion
    'token':      0.03,   # LLM
    'char':       0.03,   # TTS au caractère (~30 s / 1000 car.) ; calibrer par modèle si besoin
    'page':       3.0,    # OCR : ~3 s par page (extraction native ~0 → l'EMA l'apprend par backend)
    'mb':         1.5,    # conversion ffmpeg : ~1.5 s/Mo d'entrée (transcode vidéo ≫ image → EMA par type)
    'item':       25.0,   # générique « par élément »
}
_DEFAULT_LOAD = {
    'audio_sec':  8.0,  'video_sec': 30.0, 'megapixel': 20.0,
    'step':      20.0,  'token':      6.0, 'char':       6.0, 'page': 20.0, 'mb': 1.0, 'item': 15.0,
}


# ── Empreinte hardware ───────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def hardware_fingerprint() -> str:
    """Identifiant court du matériel de calcul (GPU + VRAM) ; 'cpu' à défaut.
    Mémoïsé : le matériel ne change pas en cours de process."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = round(torch.cuda.get_device_properties(0).total_memory / 1e9)
            return f"{name}|{vram}GB"
    except Exception:
        pass
    return "cpu"


def make_key(source: str, model_id: str) -> str:
    """Construit le model_key du registre : '{source}:{model_id}'."""
    return f"{source}:{model_id}"


# ── A-priori (modèle puis domaine) ───────────────────────────────────────────
def _apriori(model_key: str, unit: str) -> Tuple[float, float]:
    """(load_seconds, per_unit_seconds) a priori — extra_info['eta'] du modèle sinon défaut domaine."""
    load = _DEFAULT_LOAD.get(unit, _DEFAULT_LOAD['item'])
    per_unit = _DEFAULT_PER_UNIT.get(unit, _DEFAULT_PER_UNIT['item'])
    try:
        from wama.model_manager.models import AIModel
        m = AIModel.objects.filter(model_key=model_key).only('extra_info').first()
        eta = (m.extra_info or {}).get('eta') if m else None
        if isinstance(eta, dict):
            load = float(eta.get('load_seconds', load))
            per_unit = float(eta.get('per_unit_seconds', per_unit))
    except Exception:
        pass
    return load, per_unit


def _learned(model_key: str, unit: str) -> Optional[Tuple[Optional[float], float]]:
    """(load, per_unit) APPRIS pour ce hardware, ou None si aucun échantillon."""
    try:
        from wama.model_manager.models import ModelRuntimeStat
        stat = ModelRuntimeStat.objects.filter(
            model_key=model_key, hardware_fingerprint=hardware_fingerprint()
        ).first()
        if stat and stat.samples >= 1:
            return stat.load_ema_seconds, stat.per_unit_ema_seconds
    except Exception:
        pass
    return None


# ── API publique ─────────────────────────────────────────────────────────────
def estimate(model_key: str, size: float = 1.0, unit: str = 'item',
             model_loaded: bool = False, fallback_seconds: Optional[float] = None) -> float:
    """
    Estimation (secondes) du temps TOTAL de traitement d'un item.

    Args:
        model_key        : "{source}:{model_id}" (cf. make_key).
        size             : grandeur du domaine (s d'audio/vidéo, mégapixels, steps, tokens…). 1 par défaut.
        unit             : nom de la grandeur (clé de _DEFAULT_*). Cohérent avec record_run.
        model_loaded     : True si le modèle est déjà résident (singleton keep_loaded) → on omet le chargement.
        fallback_seconds : estimation a priori PROPRE à l'app (heuristique statique) utilisée au
                           démarrage à froid — AVANT tout apprentissage — à la place de l'a-priori
                           générique par domaine. Dès qu'un run réel est enregistré, l'appris prime.

    Returns:
        Secondes estimées (>= 0). 0 si rien d'exploitable (WamaEta n'affichera pas de seed).
    """
    try:
        s = float(size) if size and float(size) > 0 else 1.0
        learned = _learned(model_key, unit)
        if learned is not None:
            load, per_unit = learned
            if load is None:
                load, _ = _apriori(model_key, unit)
        elif fallback_seconds is not None:
            # Cold-start : l'app fournit sa propre estimation (déjà un total, GPU chaud).
            return max(float(fallback_seconds), 0.0)
        else:
            load, per_unit = _apriori(model_key, unit)

        secs = per_unit * s
        if not model_loaded and load:
            secs += load
        return max(secs, 0.0)
    except Exception:
        return float(fallback_seconds) if fallback_seconds else 0.0


def record_run(model_key: str, size: float, unit: str = 'item',
               process_seconds: float = 0.0, load_seconds: Optional[float] = None) -> None:
    """
    Enregistre une exécution RÉELLE pour affiner l'estimation (EMA, par hardware).

    Args:
        process_seconds : durée de TRAITEMENT mesurée (hors chargement).
        load_seconds    : durée de CHARGEMENT à froid mesurée ; None si le modèle était déjà résident.
    """
    try:
        from wama.model_manager.models import ModelRuntimeStat
        s = float(size) if size and float(size) > 0 else 1.0
        per_unit_sample = max(float(process_seconds), 0.0) / s

        stat, _ = ModelRuntimeStat.objects.get_or_create(
            model_key=model_key, hardware_fingerprint=hardware_fingerprint(),
            defaults={'unit': unit},
        )
        stat.unit = unit
        # per_unit : 1ʳᵉ mesure = valeur brute, ensuite EMA.
        stat.per_unit_ema_seconds = (
            per_unit_sample if stat.samples == 0
            else _EMA_ALPHA * per_unit_sample + (1 - _EMA_ALPHA) * stat.per_unit_ema_seconds
        )
        if load_seconds is not None:
            ls = max(float(load_seconds), 0.0)
            stat.load_ema_seconds = (
                ls if stat.load_ema_seconds is None
                else _EMA_ALPHA * ls + (1 - _EMA_ALPHA) * stat.load_ema_seconds
            )
        stat.samples = stat.samples + 1
        stat.save()
    except Exception as e:
        logger.debug("record_run ETA ignoré (%s): %s", model_key, e)
