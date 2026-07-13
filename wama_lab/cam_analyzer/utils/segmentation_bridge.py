"""
Pont SEGMENTATION → DÉTECTION standard.

Convertit un masque de segmentation d'objet (polygone image) en détection bbox-centrée
exploitable par TOUT le pipeline cam_analyzer sans rien réécrire :
  - distance pinhole (distance_speed.py, depuis le bbox),
  - position sol / vue de dessus (pinhole depuis le bbox, ou le point de contact au sol),
  - tracking global multi-caméra (multicam_tracker, via la position monde),
  - prédiction TTC/PET (prediction_adapter),
  - filtres classe/confiance.

Bonus : le POINT DE CONTACT AU SOL est dérivé du masque (barycentre X des points les plus
bas de la silhouette) — plus précis que le bas-centre du bbox pour la projection au sol.

Générique : quand un modèle de segmentation d'objets tourne (SAM3 open-vocab, YOLO-seg…),
on appelle `mask_to_detection` sur chaque masque → le reste de la chaîne est inchangé.
"""


def mask_bbox(polygon):
    """Polygone [[x, y], ...] → bbox englobant [x1, y1, x2, y2]."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def mask_ground_point(polygon, tol=3.0):
    """Point de contact au sol : barycentre X des points les plus bas du masque (silhouette),
    plus fiable que le bas-centre du bbox (qui inclut les débords latéraux)."""
    ys = [p[1] for p in polygon]
    ymax = max(ys)
    low_x = [p[0] for p in polygon if p[1] >= ymax - tol]
    gx = sum(low_x) / len(low_x) if low_x else (min(p[0] for p in polygon) + max(p[0] for p in polygon)) / 2
    return (gx, ymax)


def mask_to_detection(polygon, class_name, confidence, class_id=None,
                      track_id=None, keep_polygon=False):
    """
    Masque de segmentation → dict détection standard pour le pipeline cam_analyzer.

    polygon     : [[x, y], ...] en pixels image.
    class_name  : nom de classe (ex. 'car').
    confidence  : score [0..1].
    track_id    : si le modèle de segmentation suit déjà les objets (sinon None → le
                  tracker global assignera la continuité par position monde).
    keep_polygon: garder la silhouette (utile pour un rendu masque, sinon on l'omet).

    Retourne un dict compatible avec les détections bbox existantes (mêmes clés lues par
    la distance, le tracking, la vue de dessus). Le champ `seg_ground_px` (point de contact
    au sol) sert de position plus précise si présent.
    """
    bbox = mask_bbox(polygon)
    gx, gy = mask_ground_point(polygon)
    det = {
        'type': 'object',
        'source': 'segmentation',
        'class_name': class_name,
        'confidence': float(confidence),
        'bbox': [round(v, 1) for v in bbox],
        'seg_ground_px': [round(gx, 1), round(gy, 1)],
    }
    if class_id is not None:
        det['class_id'] = class_id
    if track_id is not None:
        det['track_id'] = track_id
    if keep_polygon:
        det['seg_polygon'] = polygon
    return det
