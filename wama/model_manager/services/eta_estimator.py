"""
Estimateur d'ETA WAMA — *seeding* auto-apprenant et hardware-aware.
================================================================================

Fournit, pour un item à traiter, une estimation a priori du temps restant —
affichée IMMÉDIATEMENT (dès le chargement du modèle) par le composant commun
`WamaEta` (`seedSeconds`), au lieu d'attendre que la progression observée donne
un débit. L'estimation s'AFFINE ensuite seule avec les durées réelles mesurées.

Modèle :   ETA ≈ (chargement à froid si modèle non résident) + coût fixe + per_unit × taille
           — le coût fixe et le coût par unité APPRIS ensemble (droite des moyennes mobiles,
           `_line`, 2026-10-21) dès que les tailles mesurées s'écartent ; avant, le rapport moyen.

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
    'image':      0.05,   # analyse d'UNE image (photo ou image de vidéo) : un détecteur à taille
                          # d'entrée fixe coûte par image, pas par mégapixel (YOLO ramène à 640 px)
    'item':       25.0,   # générique « par élément »
}
_DEFAULT_LOAD = {
    'audio_sec':  8.0,  'video_sec': 30.0, 'megapixel': 20.0,
    'step':      20.0,  'token':      6.0, 'char':       6.0, 'page': 20.0, 'mb': 1.0, 'image': 5.0,
    'item': 15.0,
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
    """Construit le model_key du registre : '{source}:{model_id}'.

    Un `model_id` qui porte DÉJÀ le préfixe (ex. `VoiceSynthesis.tts_model` stocke la clé du
    catalogue, `synthesizer:coqui-xtts`) est rendu tel quel : jusqu'au 2026-09-29 il devenait
    `synthesizer:synthesizer:coqui-xtts`, une clé que ni le catalogue (a priori) ni l'estimation
    ne relisaient sous le même nom que l'apprentissage.

    Délègue depuis le 2026-09-29 à la brique commune `model_keys.catalog_key` : le test
    « commence par `source:` » laissait passer une clé d'une AUTRE source
    (`huggingface:org/nom` → `synthesizer:huggingface:org/nom`). Une valeur qui n'est pas un
    modèle (vide, `auto`) garde l'ancienne forme préfixée, que rien ne relit sous un autre nom.
    """
    from wama.common.utils.model_keys import AUTO, catalog_key
    model_id = str(model_id)
    if model_id in ('', AUTO):
        return f"{source}:{model_id}"
    return catalog_key(model_id, source)


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


#: Écart relatif minimal entre les tailles apprises pour séparer le coût fixe du coût par unité :
#: en deçà, toutes les mesures parlent de la même taille et seul leur rapport a un sens.
_LINE_MIN_SPREAD = 0.1


def _line(stat) -> Optional[Tuple[float, float]]:
    """(coût fixe, coût par unité) de la droite apprise — durée = fixe + par unité × taille —, ou
    None tant que les tailles mesurées ne s'écartent pas assez (2026-10-21).

    POURQUOI. Le rapport moyen `per_unit_ema_seconds` (durée / taille) prête à chaque unité le coût
    FIXE d'un traitement mesuré sur de petites tailles : le résumé du transcriber s'apprenait
    0,53 s par seconde d'audio, et s'annonçait 75 min pour 141 min d'audio — il en a pris 12 s.
    Mesuré sur la card #2522 : 11 h annoncées au lancement, 9 min 13 s réelles. La droite garde ce que le
    rapport mélangeait ; bornée (aucun coût négatif), elle redevient le rapport quand les mesures
    ne la déterminent pas."""
    try:
        mx, my = stat.size_ema, stat.seconds_ema
        mxx, mxy = stat.size_sq_ema, stat.size_seconds_ema
        if None in (mx, my, mxx, mxy) or stat.samples < 2 or mx <= 0:
            return None
        variance = mxx - mx * mx
        if variance <= (_LINE_MIN_SPREAD * mx) ** 2:
            return None
        slope = (mxy - mx * my) / variance
        fixed = my - slope * mx
        if slope < 0:                       # plus long sur moins de matière : un coût fixe seul
            return max(my, 0.0), 0.0
        if fixed < 0:                       # la droite passerait sous zéro : par l'origine
            return 0.0, (mxy / mxx if mxx > 0 else 0.0)
        return fixed, slope
    except Exception:
        return None


def _learn_line(stat, size: float, seconds: float) -> None:
    """Met à jour les moyennes mobiles de la droite (`_line`) — 1ʳᵉ mesure brute, puis EMA."""
    x, y = float(size), float(seconds)
    first = stat.size_ema is None
    for field, value in (('size_ema', x), ('seconds_ema', y), ('size_sq_ema', x * x),
                         ('size_seconds_ema', x * y)):
        previous = getattr(stat, field)
        setattr(stat, field, value if first or previous is None
                else _EMA_ALPHA * value + (1 - _EMA_ALPHA) * previous)


def _learned_line(model_key: str) -> Optional[Tuple[float, float]]:
    """La droite apprise pour ce matériel (`_line`), ou None."""
    try:
        from wama.model_manager.models import ModelRuntimeStat
        stat = ModelRuntimeStat.objects.filter(
            model_key=model_key, hardware_fingerprint=hardware_fingerprint()).first()
        return _line(stat) if stat else None
    except Exception:
        return None


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


# ── Vitesse d'inférence d'un modèle (2026-10-11) ─────────────────────────────
# La vitesse d'un modèle n'a pas de magasin à elle : c'est son ETA APPRISE sous sa clé de
# CATALOGUE (`AIModel.model_key`, la convention de `make_key`), sur ce matériel. Le banc la
# calibre (`bench.py` : jetons d'un LLM, images d'un détecteur), les exécutions réelles l'affinent.
# Le curseur rapide/qualité la lit (`model_selector.intent_choice`) — pour TOUTES les apps : une
# app dont les modèles ne sont pas chronométrés garde le coût de repli (la VRAM).
# ⚠ Une clé d'OPÉRATION d'app (`anonymizer:blur:img`, `converter:video:gif`…) n'est pas une
# vitesse de modèle : elle mesure une tâche entière, et n'est lue par aucune comparaison.

def learned_speed(model_key: str) -> Optional[Tuple[str, float, int]]:
    """(unité, secondes par unité, échantillons) APPRIS pour ce modèle sur ce matériel, ou None."""
    try:
        from wama.model_manager.models import ModelRuntimeStat
        stat = ModelRuntimeStat.objects.filter(
            model_key=model_key, hardware_fingerprint=hardware_fingerprint(), samples__gte=1
        ).first()
        if stat:
            return stat.unit, stat.per_unit_ema_seconds, stat.samples
    except Exception:
        pass
    return None


def comparable_speeds(model_keys) -> dict:
    """`{model_key: secondes par unité}` APPRISES sur ce matériel pour TOUT le lot, ou {} s'il
    n'est pas comparable : un modèle sans mesure, ou deux unités différentes (des secondes par
    jeton et par image ne se rangent pas ensemble). Règle de lot de l'échelle des signaux : on
    ne compare pas un modèle chronométré à un modèle qui ne l'est pas."""
    keys = list(dict.fromkeys(k for k in model_keys if k))
    if not keys:
        return {}
    try:
        from wama.model_manager.models import ModelRuntimeStat
        rows = ModelRuntimeStat.objects.filter(
            model_key__in=keys, hardware_fingerprint=hardware_fingerprint(), samples__gte=1)
        found = {r.model_key: (r.unit, r.per_unit_ema_seconds) for r in rows}
    except Exception:
        return {}
    if set(found) != set(keys) or len({unit for unit, _ in found.values()}) != 1:
        return {}
    return {key: seconds for key, (_, seconds) in found.items()}


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
        fixed = 0.0
        if learned is not None:
            load, per_unit = learned
            if load is None:
                load, _ = _apriori(model_key, unit)
            line = _learned_line(model_key)
            if line is not None:
                fixed, per_unit = line
        elif fallback_seconds is not None:
            # Cold-start : l'app fournit sa propre estimation (déjà un total, GPU chaud).
            return max(float(fallback_seconds), 0.0)
        else:
            load, per_unit = _apriori(model_key, unit)

        secs = fixed + per_unit * s
        if not model_loaded and load:
            secs += load
        return max(secs, 0.0)
    except Exception:
        return float(fallback_seconds) if fallback_seconds else 0.0


def record_run(model_key: str, size: float, unit: str = 'item',
               process_seconds: float = 0.0, load_seconds: Optional[float] = None,
               user=None) -> None:
    """
    Enregistre une exécution RÉELLE pour affiner l'estimation (EMA, par hardware).

    Args:
        process_seconds : durée de TRAITEMENT mesurée (hors chargement).
        load_seconds    : durée de CHARGEMENT à froid mesurée ; None si le modèle était déjà résident.
        user            : le propriétaire de l'élément. Un compte de TEST n'apprend rien
                          (`nightly_tests.is_test_account`) : ses entrées sont des témoins
                          synthétiques — une image de 8×8 px rapportée au mégapixel a donné
                          828 338 s/Mpx à l'anonymizer (mesuré le 2026-09-29).
    """
    if user is not None:
        try:
            from wama.common.services.nightly_tests import is_test_account
            if is_test_account(user):
                logger.debug("record_run ignoré (%s) : compte de test", model_key)
                return
        except Exception:
            pass
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
        # La droite (coût fixe + par unité) : l'estimation la lit dès que les tailles s'écartent.
        _learn_line(stat, s, max(float(process_seconds), 0.0))
        stat.samples = stat.samples + 1
        stat.save()
    except Exception as e:
        logger.debug("record_run ETA ignoré (%s): %s", model_key, e)


def relearn_lines_from_runs(apply: bool = False) -> dict:
    """Amorce la droite (`_line`) des clés de PROCESS qui n'en ont pas encore, depuis les lignes
    d'exécution gardées (`ProcessRun` : durée mesurée + taille `eta_size_s`), dans l'ordre où elles
    ont tourné — un geste unique, le jour où la droite est née (2026-10-21) : sans lui, chaque
    clé attendrait deux nouvelles mesures de tailles différentes. Une clé qui a déjà sa droite
    n'est jamais rejouée (aucune mesure comptée deux fois). Rend `{clé: mesures rejouées}` ;
    `apply=False` ne fait que compter."""
    from django.apps import apps
    from wama.common.models import ProcessRun
    from wama.common.services.process_pipeline import process_of_function
    from wama.common.services.process_runs import ETA_SIZE_KEY, process_eta
    from wama.model_manager.models import ModelRuntimeStat

    fingerprint = hardware_fingerprint()
    pending: dict = {}
    for row in ProcessRun.objects.filter(status='SUCCESS', duration_s__isnull=False) \
            .order_by('finished_at').iterator():
        size = (row.output_summary or {}).get(ETA_SIZE_KEY)
        pipeline, spec = process_of_function(row.process_key)
        if not size or spec is None:
            continue
        try:
            item = apps.get_model(pipeline.app, row.object_type).objects.filter(
                pk=row.object_id).first()
        except LookupError:
            item = None
        eta = process_eta(spec, item) if item is not None else None
        if not eta:
            continue
        # La règle de `record_run` : un compte de TEST n'apprend rien (ses témoins de 8×8 px).
        from wama.common.services.nightly_tests import is_test_account
        if getattr(item, 'user', None) is not None and is_test_account(item.user):
            continue
        pending.setdefault(eta[0], []).append((float(size), float(row.duration_s)))
    replayed = {}
    for key, runs in pending.items():
        stat = ModelRuntimeStat.objects.filter(model_key=key,
                                               hardware_fingerprint=fingerprint).first()
        if stat is None or stat.size_ema is not None:
            continue
        replayed[key] = len(runs)
        if apply:
            for size, seconds in runs:
                _learn_line(stat, size, seconds)
            stat.save(update_fields=['size_ema', 'seconds_ema', 'size_sq_ema', 'size_seconds_ema'])
    return replayed
