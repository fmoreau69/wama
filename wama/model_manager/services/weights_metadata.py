"""
Lecture des FAITS inscrits DANS un fichier de poids — licence, classes, tâche, entraînement.

POURQUOI ICI. Le catalogue ne savait renseigner `license` que par une requête HuggingFace, donc
uniquement pour les modèles portant un `hf_id` : 22 sur 101 (mesuré le 2026-08-12). Les 70 autres
sont découverts par scan disque et n'ont aucune identité de plateforme — alors que leurs poids
PORTENT la licence. `.pt` ultralytics ≥ 8.3 et tout export `.onnx` inscrivent `license` en clair.

CE QUE CE MODULE FAIT — et ne fait pas.
  • Il LIT ce qui est écrit dans le fichier. Aucune déduction depuis un nom de fichier ou un
    dossier : c'est la doctrine de `backfill_platform_refs` (« le silence vaut mieux qu'une
    correspondance inventée »). Un `.pt` ultralytics 8.0.x n'a pas de champ `license` → on rend
    None, on ne conclut pas « AGPL parce que c'est du YOLO ».
  • Il rend aussi `toolkit_version`, `date`, `train_base` et `train_data` : ce ne sont pas des
    champs du catalogue, mais ce sont les indices qui permettent à un humain d'ÉTABLIR une
    provenance. Exemple réel : `yolo11l_face_plate_signs.pt` porte
    `train_args.model = '/bigpool/data/panoramax/yolo/…'` — ce qui a confirmé indépendamment
    l'appariement par taille avec `Panoramax/detect_face_plate_sign`.

DOMICILE. `model_manager/services/` et non `common/` : c'est le domicile déjà établi de la
logique modèle inter-apps (`model_selector.py`, `model_registry.py`). `anonymizer/utils/
model_selector._get_onnx_model_classes` lisait déjà les métadonnées ONNX de son côté — il
délègue désormais ici (zéro duplication), et son repli « dossier de spécialité » ne s'applique
plus qu'APRÈS avoir ouvert le fichier, ce qui était le bon ordre depuis le début.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

#: Clés rendues par `read_metadata`. Toutes optionnelles : un poids peut n'en porter aucune.
CHAMPS = ('license', 'names', 'task', 'imgsz', 'toolkit_version', 'date',
          'train_base', 'train_data', 'description')


def _vide() -> dict:
    return {c: None for c in CHAMPS}


def _normalize_license(brut) -> Optional[str]:
    """
    'AGPL-3.0 License (https://ultralytics.com/license)' → 'agpl-3.0'.

    Délègue à `common.services.license_audit.normaliser_licence` : la normalisation appartient au
    DOMAINE licence, pas au lecteur de poids, qui n'en est qu'un producteur parmi d'autres (la
    carte HuggingFace et les métadonnées PyPI en sont deux autres). Elle vivait ici en premier
    parce que c'est ici qu'elle est apparue ; elle a été remontée quand la vue licences a eu
    besoin de recouper les mêmes graphies (2026-08-12).
    """
    from wama.common.services.license_audit import normaliser_licence

    return normaliser_licence(brut) or None


def _lire_onnx(chemin: str) -> dict:
    """Métadonnées d'un export ONNX (`metadata_props`). Ultralytics y écrit names/task/license."""
    infos = _vide()
    try:
        import onnx
    except ImportError:
        logger.debug("[weights_metadata] paquet `onnx` absent — ONNX non lisible")
        return infos
    try:
        modele = onnx.load(chemin, load_external_data=False)
    except Exception as e:
        logger.debug(f"[weights_metadata] ONNX illisible {os.path.basename(chemin)}: {e}")
        return infos

    meta = {kv.key: kv.value for kv in modele.metadata_props}
    infos['license'] = _normalize_license(meta.get('license'))
    infos['task'] = meta.get('task') or None
    infos['toolkit_version'] = meta.get('version') or None
    infos['date'] = meta.get('date') or None
    infos['description'] = meta.get('description') or None
    infos['imgsz'] = meta.get('imgsz') or None
    infos['names'] = _parser_names(meta.get('names'))
    return infos


def _parser_names(brut) -> Optional[list]:
    """`\"{0: 'License_Plate'}\"` ou `'[\"a\",\"b\"]'` → ['license_plate']. None si illisible."""
    if not brut:
        return None
    if isinstance(brut, dict):
        return [str(v).lower() for _, v in sorted(brut.items(), key=lambda kv: int(kv[0]))]
    if isinstance(brut, (list, tuple)):
        return [str(v).lower() for v in brut]
    texte = str(brut).strip()
    import ast
    import json
    for lecteur in (json.loads, ast.literal_eval):
        try:
            valeur = lecteur(texte)
        except Exception:
            continue
        if isinstance(valeur, dict):
            return [str(v).lower() for _, v in sorted(valeur.items(), key=lambda kv: int(kv[0]))]
        if isinstance(valeur, (list, tuple)):
            return [str(v).lower() for v in valeur]
    return None


def _lire_pt(chemin: str) -> dict:
    """
    Métadonnées d'un checkpoint ultralytics `.pt`.

    ⚠ `torch.load(weights_only=False)` désérialise du pickle — donc du code. On ne l'accepte QUE
    sous `AI_MODELS_DIR` (poids déjà exécutés par les backends de WAMA au moment de l'inférence) ;
    un chemin hors de cet arbre est refusé plutôt que lu. `weights_only=True` ne convient pas :
    le checkpoint ultralytics contient l'objet modèle, pas un simple state_dict.
    """
    infos = _vide()
    try:
        from django.conf import settings
        racine = os.path.realpath(str(settings.AI_MODELS_DIR))
        if not os.path.realpath(chemin).startswith(racine):
            logger.warning(f"[weights_metadata] refus de désérialiser hors AI_MODELS_DIR : {chemin}")
            return infos
    except Exception:
        return infos

    try:
        import torch
        ck = torch.load(chemin, map_location='cpu', weights_only=False)
    except Exception as e:
        logger.debug(f"[weights_metadata] .pt illisible {os.path.basename(chemin)}: {e}")
        return infos
    if not isinstance(ck, dict):
        return infos

    infos['license'] = _normalize_license(ck.get('license'))
    infos['toolkit_version'] = ck.get('version') or None
    infos['date'] = ck.get('date') or None

    args = ck.get('train_args')
    if isinstance(args, dict):
        infos['task'] = args.get('task') or None
        infos['imgsz'] = args.get('imgsz') or None
        infos['train_base'] = args.get('model') or None      # poids de départ du finetune
        infos['train_data'] = args.get('data') or None       # jeu d'entraînement déclaré

    modele = ck.get('ema') or ck.get('model')
    noms = getattr(modele, 'names', None)
    if noms:
        infos['names'] = _parser_names(noms)
    if not infos['task'] and modele is not None:
        infos['task'] = getattr(modele, 'task', None) or None
    return infos


def read_metadata(chemin: str) -> dict:
    """
    Faits lus dans le fichier de poids. Toujours un dict aux clés `CHAMPS` (valeurs souvent None).

    Ne lève jamais : un poids illisible rend un dict vide, il ne casse pas un balayage de catalogue.
    """
    if not chemin or not os.path.isfile(chemin):
        return _vide()
    ext = os.path.splitext(chemin)[1].lower()
    if ext == '.onnx':
        return _lire_onnx(chemin)
    if ext in ('.pt', '.pth'):
        return _lire_pt(chemin)
    return _vide()


def classes_from_weights(chemin: str) -> Optional[list]:
    """
    Liste ORDONNÉE des classes déclarée par le fichier, ou None.

    Raccourci pour les appelants qui ne veulent que ça (découverte YOLO, sélecteur de l'anonymizer).
    L'ORDRE compte : c'est l'index de classe passé à `predict(classes=[…])`. Les tables codées en
    dur du registre s'en écartaient — `faces&plates` y vaut ['face','plate'] alors que les poids
    déclarent ['plate','face'], et `yolo11l_face_plate_signs.pt` porte en réalité trois classes
    (['sign','plate','face']) dont une invisible au catalogue (constaté le 2026-08-12).
    """
    return read_metadata(chemin).get('names')
