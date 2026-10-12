"""
Les modèles de l'anonymizer pour un jeu de classes — par la brique COMMUNE de couverture
(`common/services/model_coverage.couvrir_classes`), seule source : le catalogue.

Ce module ne garde que ce que l'app y DÉCLARE (stratégie, tâches admises, ensemble par classe —
`select_best_models_by_precision`) et la lecture des classes d'un fichier de poids
(`get_model_classes`, qui vérifie qu'un modèle CHOISI par l'utilisateur couvre la demande).

L'ancien sélecteur mono-modèle est RETIRÉ le 2026-10-12 (`REMOVAL_LEDGER R117`, décision de
Fabien) : il découvrait les modèles à côté du catalogue (base, puis scan disque), les devinait
par leur NOM de fichier (`yolo11{taille}.pt`) et retombait sur un modèle écrit en dur — un repli
silencieux sur un autre modèle que celui qui convient. Rien ne couvre les classes → la tâche
s'arrête en les nommant.
"""

import os
import logging
from typing import List, Dict
from ultralytics import YOLO
from .yolo_utils import get_model_path

logger = logging.getLogger(__name__)

# Cache pour éviter de recharger les modèles à chaque fois
_MODEL_CLASSES_CACHE: Dict[str, Dict[str, str]] = {}

# Known classes for specialty ONNX models (when metadata extraction is not possible)
# Maps specialty directory name to expected classes
SPECIALTY_MODEL_CLASSES = {
    'faces': {'0': 'face'},
    'plates': {'0': 'plate'},
    'faces&plates': {'0': 'face', '1': 'plate'},
}

def get_model_classes(model_path: str) -> Dict[str, str]:
    """
    Extract class names from a YOLO model.

    Supports both PyTorch (.pt) and ONNX (.onnx) formats.
    For ONNX models in specialty directories (faces, plates), uses predefined class mapping.

    Args:
        model_path: Absolute path to the model file

    Returns:
        Dictionary mapping class IDs (str) to class names (lowercase)
        Example: {'0': 'person', '1': 'bicycle', ...}
    """
    # Check cache first
    if model_path in _MODEL_CLASSES_CACHE:
        return _MODEL_CLASSES_CACHE[model_path]

    model_path_lower = model_path.lower()
    is_onnx = model_path_lower.endswith('.onnx')

    # For ONNX models in specialty directories, use predefined classes
    if is_onnx:
        classes = _get_onnx_model_classes(model_path)
        if classes:
            _MODEL_CLASSES_CACHE[model_path] = classes
            logger.info(f"Loaded {len(classes)} classes from ONNX model {os.path.basename(model_path)}")
            return classes

    # For PyTorch models, use ultralytics YOLO to extract classes
    try:
        model = YOLO(model_path)
        # Get class names from model
        names_dict = model.model.names  # {0: 'person', 1: 'bicycle', ...}

        # Convert to lowercase and string keys for consistency
        classes = {str(k): v.lower() for k, v in names_dict.items()}

        # Cache the result
        _MODEL_CLASSES_CACHE[model_path] = classes

        logger.info(f"Loaded {len(classes)} classes from {os.path.basename(model_path)}")
        return classes

    except Exception as e:
        logger.error(f"Failed to load model {model_path}: {e}")
        return {}


def _get_onnx_model_classes(model_path: str) -> Dict[str, str]:
    """
    Get classes for an ONNX model.

    First tries to extract from ONNX metadata, then falls back to specialty directory mapping.

    Args:
        model_path: Path to ONNX model file

    Returns:
        Dictionary mapping class IDs to class names, or empty dict if not found
    """
    # ── LE FICHIER D'ABORD ────────────────────────────────────────────────────────────────
    # L'ancien ordre testait le dossier de spécialité AVANT d'ouvrir le fichier, et sortait :
    # le bloc de lecture des métadonnées qui suivait était donc MORT pour tous les modèles
    # rangés dans `faces/`, `plates/` ou `faces&plates/` — c'est-à-dire exactement ceux qu'il
    # servait à décrire. Les 5 ONNX de plaques déclarent pourtant `names = {0:'License_Plate'}`
    # dans leurs métadonnées (constaté le 2026-08-12).
    # La lecture est mutualisée avec le catalogue (`model_manager.services.weights_metadata`) :
    # elle existait ici en double, en version onnxruntime (plus coûteuse — elle construisait
    # une session d'inférence pour lire une chaîne).
    try:
        from wama.model_manager.services.weights_metadata import classes_from_weights

        noms = classes_from_weights(model_path)
        if noms:
            logger.info(f"[ModelSelector] Classes lues dans {os.path.basename(model_path)} : {noms}")
            return {str(i): str(n).lower() for i, n in enumerate(noms)}
    except Exception as e:
        logger.debug(f"[ModelSelector] Lecture des métadonnées impossible : {e}")

    # Repli : le dossier de spécialité, pour les exports dépourvus de métadonnées `names`.
    path_parts = model_path.replace('\\', '/').split('/')
    for part in path_parts:
        if part in SPECIALTY_MODEL_CLASSES:
            classes = SPECIALTY_MODEL_CLASSES[part]
            logger.info(f"[ModelSelector] ONNX model in '{part}' directory: using predefined classes {list(classes.values())}")
            return classes

    logger.debug(f"[ModelSelector] No class metadata found in ONNX model: {os.path.basename(model_path)}")
    return {}


def get_model_size_from_precision(precision_level: int) -> str:
    """
    Taille de modèle ('n', 's', 'm', 'l', 'x') pour un niveau de précision 0-100.

    ⚠ Chantier C (2026-09-20, décision Fabien du 15/09) : la déclinaison VISION du curseur est
    REMONTÉE AU COMMUN (`model_coverage.size_for_intent`, mêmes seuils 20/40/60/80) — cette
    fonction ne fait plus que l'appeler, sous son nom historique (tasks, params et gabarit le
    citent). Le comportement est inchangé au cran près (garde : `tests_intent_vision`).
    """
    from wama.common.services.model_coverage import size_for_intent
    return size_for_intent(precision_level)


def should_use_segmentation(precision_level: int) -> bool:
    """
    Segmentation préférée à partir de 50 — même remontée au commun que ci-dessus
    (`model_coverage.segmentation_for_intent`).
    """
    from wama.common.services.model_coverage import segmentation_for_intent
    return segmentation_for_intent(precision_level)


# =============================================================================
# COUVERTURE MULTI-MODÈLES — délègue à la brique commune
# =============================================================================
#
# PORTAGE 2026-08-12. Ce bloc portait sa propre logique de recouvrement, en trois étapes
# (spécialités → COCO → rattrapage) reposant sur une liste écrite à la main,
# `SPECIALTY_CLASSES = {'face','plate',…}`. Elle a été REMPLACÉE — pas doublée — par
# `common/services/model_coverage.py::couvrir_classes()`, qui vient précisément d'ici
# (extrait le 2026-08-04) et qui n'avait jamais été adopté.
#
# Pourquoi la brique commune est meilleure, mesuré sur le catalogue réel :
#   ['face','plate','sign']          → 1 modèle  (contre 2 ici)
#   ['face','plate','sign','person'] → 2 modèles (contre 3, dont un modèle de POSE pour
#                                      'person' — choix arbitraire du premier déclarant)
# Elle fait un recouvrement GLOUTON (le modèle couvrant le plus de classes restantes ; à
# égalité le plus qualitatif via `quality_index`), là où les trois étapes locales fixaient
# l'ordre d'avance et ne pouvaient donc pas être minimales.
#
# CE QUI RESTE ICI, ET DOIT Y RESTER : la POLITIQUE de l'app. « Précision élevée → préférer
# la segmentation et les gros modèles » est une décision de l'anonymizer ; elle se DÉCLARE en
# paramètres (`preferer_segmentation`, `taille_preferee`), appliqués en départage et jamais en
# filtre — mieux vaut couvrir une classe avec un modèle non préféré que ne pas la couvrir.
#
# Supprimés avec ce portage (plus aucun appelant) : `SPECIALTY_CLASSES`,
# `_find_combined_specialty_model`, `_find_specialty_model`, `_find_coco_model`.

#: Tâches admises pour flouter — déclarées UNE fois (`model_config.DETECTION_TASKS`, que le
#: select lit aussi).
from .model_config import DETECTION_TASKS, RECALL_FLOOR, models_per_class_for  # noqa: E402


def select_best_models_by_precision(classes_to_blur: List[str],
                                    precision_level: int = 50) -> Dict:
    """
    Ensemble de modèles couvrant `classes_to_blur`, selon le niveau de précision.

    Args:
        classes_to_blur: classes à détecter (ex. ['face', 'plate', 'car'])
        precision_level: 0=Rapide, 50=Équilibré, 100=Précis

    Returns:
        {
            'models_to_use': [{'id', 'path', 'name', 'type', 'classes'}, …],
            'unsupported_classes': [...],   # nommées, jamais ignorées en silence
            'coverage': 0..1,
        }
    """
    if not classes_to_blur:
        return {'models_to_use': [], 'coverage': 0, 'unsupported_classes': []}

    from wama.common.services.model_coverage import couvrir_classes
    from wama.model_manager.models import AIModel

    resultat = couvrir_classes(
        classes_to_blur,
        source='anonymizer',
        model_type='vision',
        taches_admises=DETECTION_TASKS,
        # DEUX MODÈLES SPÉCIALISÉS PLUTÔT QU'UN 2-EN-1 (décision Fabien, 2026-08-12).
        # Anonymiser, c'est ne rien rater : un visage manqué est une fuite, une passe de
        # détection en plus n'est qu'un coût. Aucun modèle « visages+plaques » du catalogue
        # n'égale deux détecteurs dédiés — mesuré : sur une foule, `yolov9s-face-lindevs`
        # trouve 307 visages là où `yolov8m_face_plate_1080p` en trouve 4.
        # C'est donc l'inverse de l'objectif « le moins de modèles possible », et ça se
        # DÉCLARE ici parce que c'est un arbitrage métier de l'anonymizer, pas de la brique.
        strategie='specialisation',
        # Préférences, pas filtres — DÉRIVÉES par la brique du curseur commun (chantier C) :
        # la déclinaison n/s/m/l/x + segmentation ≥ 50 vit désormais dans `model_coverage`.
        quality_intent=precision_level,
        # ENSEMBLE PAR CLASSE (2026-10-10) : rappel d'abord — plusieurs détecteurs par classe
        # selon le curseur (`model_config.models_per_class_for`), départagés par leur rappel MESURÉ.
        models_per_class=models_per_class_for(precision_level),
        max_modeles=max(4, models_per_class_for(precision_level) * len(classes_to_blur)),
        # La vitesse ne départage que les détecteurs qui trouvent assez (`RECALL_FLOOR`).
        min_relative_recall=RECALL_FLOOR,
    )

    # La brique rend des `model_key` de catalogue ; l'anonymizer manipule ses identifiants
    # historiques (`detect/faces&plates/x.pt`), qui servent de clé de cache aux tâches de
    # détection et d'entrée à `get_model_path`. Une seule requête pour les deux traductions.
    cles = [m['model_key'] for m in resultat['modeles']]
    par_cle = {m.model_key: m for m in AIModel.objects.filter(model_key__in=cles)} if cles else {}

    models_to_use = []
    for m in resultat['modeles']:
        am = par_cle.get(m['model_key'])
        extra = (am.extra_info or {}) if am else {}
        identifiant = extra.get('model_id') or m['model_key']
        chemin = m.get('path') or ''
        if not chemin:
            # `local_path` vide au catalogue : on retombe sur la résolution historique plutôt
            # que d'écarter un modèle que la couverture vient de retenir.
            chemin = get_model_path(identifiant)
        models_to_use.append({
            'id': identifiant,
            # La CLÉ de catalogue voyage (2026-10-10) : c'est elle qui dit le moteur d'un modèle
            # hors ultralytics, que l'ensemble exécute par son backend (`detection_ensemble`).
            'model_key': m['model_key'],
            'path': chemin,
            'name': m['name'],
            'type': (am.capabilities or {}).get('task', 'detect') if am else 'detect',
            'classes': m['classes'],
        })

    logger.info(f"[ModelSelector] {len(models_to_use)} modèle(s) pour {len(classes_to_blur)} classe(s) "
                f"(couverture {resultat['couverture']:.0%}, précision {precision_level})")
    if resultat['classes_non_couvertes']:
        logger.warning(f"[ModelSelector] classes non couvertes : {resultat['classes_non_couvertes']}")

    return {
        'models_to_use': models_to_use,
        'unsupported_classes': resultat['classes_non_couvertes'],
        'coverage': resultat['couverture'],
    }
