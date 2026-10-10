"""Détection par un ENSEMBLE de modèles — l'union de leurs documents `detections` (2026-10-10).

POURQUOI. Anonymiser, c'est ne rien rater : une plaque oubliée suffit à casser l'anonymisation.
Le banc des plaques en caméra embarquée l'a mesuré — aucun détecteur seul ne dépasse 60 % de
rappel, mais leurs erreurs diffèrent (EgoBlur 59,5 %, RT-DETR 40 %, leur union 64,6 %). Jusqu'ici
l'union n'était possible qu'entre modèles ultralytics, dans `Anonymize` ; un détecteur d'une autre
famille (`transformers`, TorchScript) ne pouvait pas y entrer.

COMMENT. Les modèles ultralytics passent ENSEMBLE par `Anonymize` (une passe chacun, suivi et
pistes compris — rien ne change pour eux) ; chaque autre modèle passe par SON backend, résolu
par la porte commune (`backend_instance_for_key` : moteur déclaré au catalogue ↔ `ENGINE`), et
rend son propre document ; `detections.merge` les réunit. L'interpolation des trous, faite au
floutage, relie les détections par leur position : un détecteur sans suivi en profite aussi.

Consommateurs : l'anonymizer (process « Détection ») et le banc de rappel
(`model_manager/services/bench.py`), qui mesure chaque modèle par le MÊME chemin que celui qui
servira — un banc qui appellerait YOLO à sa façon mesurerait autre chose que ce qui floute.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Moteur des modèles que `Anonymize` charge lui-même (`YOLO(chemin)`).
ULTRALYTICS = 'ultralytics'


def engine_of(model_key: str) -> str:
    """Le moteur DÉCLARÉ au catalogue (`composition.runtime.engine`) — '' si inconnu."""
    if not model_key:
        return ''
    try:
        from wama.model_manager.models import AIModel
        composition = (AIModel.objects.filter(model_key=model_key)
                       .values_list('composition', flat=True).first()) or {}
    except Exception:
        return ''
    return ((composition.get('runtime') or {}).get('engine') or '')


def _scaled(progress, rank: int, count: int):
    """La progression d'UNE passe ramenée à sa part de l'ensemble (sinon la barre repartirait
    de zéro à chaque détecteur)."""
    if progress is None:
        return None
    return lambda done, total: progress(rank * max(total, 1) + done, count * max(total, 1))


def detect_with_models(models, *, user=None, source_dir=None, destination_dir=None,
                       **kwargs) -> dict:
    """Le document `detections` de l'ENSEMBLE `models` sur le média de `kwargs['media_path']`.

    `models` : descripteurs `{'model_key', 'path', 'name', 'classes', 'engine'?}` (forme de la
    couverture de classes) ; `engine` absent se lit au catalogue, et un modèle sans moteur
    déclaré est réputé ultralytics (les poids YOLO historiques). `kwargs` : ceux du process de
    détection (`classes2blur`, `detection_threshold`, `on_frame`, `progress`…), transmis à chaque
    détecteur — avec, pour un détecteur hors ultralytics, SES classes à la place de la demande.
    """
    from wama.common.backends.anonymize import Anonymize
    from wama.common.backends.manager import backend_instance_for_key
    from wama.common.utils import detections as dets

    models = [dict(m) for m in models or []]
    for m in models:
        m.setdefault('engine', engine_of(m.get('model_key')) or ULTRALYTICS)
    yolo = [m for m in models if m['engine'] == ULTRALYTICS]
    others = [m for m in models if m['engine'] != ULTRALYTICS]
    passes = (1 if yolo else 0) + len(others)
    progress = kwargs.pop('progress', None)

    docs, rank = [], 0
    if yolo:
        engine = Anonymize(source_dir=source_dir, destination_dir=destination_dir)
        with_path = [m for m in yolo if m.get('path')]
        # Aucun chemin désigné : le modèle par défaut d'`Anonymize`, comme avant l'ensemble.
        engine.load_model(**({'models': with_path} if with_path else {}))
        docs.append(engine.detect(**kwargs, progress=_scaled(progress, rank, passes)))
        rank += 1
    for m in others:
        detector = backend_instance_for_key(m['model_key'], user)
        wanted = m.get('classes') or kwargs.get('classes2blur')
        logger.info("[ensemble] %s (%s) : %s", m['model_key'], m['engine'], wanted)
        docs.append(detector.detect(**{**kwargs, 'classes2blur': wanted},
                                    progress=_scaled(progress, rank, passes)))
        rank += 1
    doc = dets.merge(docs)
    logger.info("[ensemble] %d détecteur(s), %d détection(s)", passes, dets.count(doc))
    return doc
