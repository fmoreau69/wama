"""
Couverture multi-modèles de l'anonymizer — DÉCIDE, n'exécute plus.

Ce module orchestrait un second pipeline : une chaîne Celery `detect_with_model` × N puis
`merge_and_blur_detections`, avec les masques sérialisés en base64 dans Redis. Ce chemin a été
SUPPRIMÉ le 2026-08-13 : il avait perdu l'interpolation, le format de sortie, le statut RUNNING,
l'ETA, la notification et l'annulation, il décodait la vidéo N+1 fois, et le transport des
masques pleine résolution par Redis pesait plusieurs Go par vidéo.

`Anonymize` (core/anonymize.py) sait désormais charger N modèles et unir leurs zones frame par
frame, dans la tâche unique qui portait déjà tout le reste. Il ne reste donc ici que la
DÉCISION — quels modèles pour quelles classes — déléguée à `common/services/model_coverage.py`.
"""

import logging


logger = logging.getLogger(__name__)


def needs_parallel_detection(classes_to_blur: list, precision_level: int) -> dict:
    """
    Determine if parallel detection is needed.

    Analyzes the requested classes and determines if multiple models are
    required to cover all classes (e.g., face model + COCO model).

    Args:
        classes_to_blur: List of class names to detect
        precision_level: 0-100 precision level (affects model selection)

    Returns:
        dict with:
        - 'parallel': bool - True if multiple models needed
        - 'models': list of model info dicts with classes to detect
        - 'coverage': float - percentage of classes covered
        - 'unsupported': list of classes with no available model
    """
    # `unsupported_classes` et NON `unsupported` : le seul lecteur (tasks.py, avertissement
    # « classes non couvertes » en console) interrogeait `unsupported_classes` alors qu'on
    # rendait `unsupported` — l'avertissement n'a donc JAMAIS pu s'afficher, et une classe que
    # rien ne sait détecter passait en silence. Les deux clés sont rendues : `unsupported`
    # reste pour tout appelant historique, mais elle n'est plus la seule.
    if not classes_to_blur:
        return {
            'parallel': False,
            'models': [],
            'coverage': 0,
            'unsupported': [],
            'unsupported_classes': [],
        }

    from .utils.model_selector import select_best_models_by_precision

    selection = select_best_models_by_precision(
        classes_to_blur=classes_to_blur,
        precision_level=precision_level
    )

    non_couvertes = selection.get('unsupported_classes', [])
    return {
        'parallel': len(selection['models_to_use']) > 1,
        'models': selection['models_to_use'],
        'coverage': selection['coverage'],
        'unsupported': non_couvertes,
        'unsupported_classes': non_couvertes,
    }
