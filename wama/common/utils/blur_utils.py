"""Floutage d'image — primitives par IMAGE, remontées dans le commun le 2026-09-07.

⚠ POURQUOI ICI ET PAS AU REGISTRE DES FONCTIONS (question de Fabien) : la taxonomie de types
n'a AUCUN type image — ses 11 supertypes sont analytiques (`detections`, `depth_map`,
`timeseries`, `scalar`…), et les 58 fonctions du registre sont des étapes de PIPELINE sur des
artefacts. Ces primitives-ci travaillent par FRAME, à l'intérieur d'une boucle de décodage,
des milliers de fois par vidéo : ce n'est pas un nœud, c'est une brique de nœud.
*L'opération « anonymiser une vidéo » serait, elle, une fonction légitime — grain grossier,
vidéo → vidéo, déclarable en `binding='app'` comme les 20 fonctions app-bound existantes.*

Elles vivaient dans `wama/anonymizer/core/`, ce qui attachait deux backends à leur app et
bloquait leur passage au substrat transversal. Aucune dépendance Django, aucune dépendance
d'app : `cv2`, `numpy`, et la géométrie de `bounds`.
"""
from math import sqrt

import cv2
import numpy as np
from .bounds import Bounds


def _shape_alpha(polygons, shape, *, scale, grow, feather, margin):
    """(x0, y0, alpha) d'UNE forme : sa couverture (0 → 1) dans sa boîte élargie de `margin`,
    agrandissement, élargissement et fondu extérieur compris ; None si elle est vide."""
    parts = [np.asarray(p, dtype=np.float32).reshape(-1, 2) for p in polygons or [] if len(p) >= 3]
    if not parts:
        return None
    height, width = shape[:2]
    points = np.concatenate(parts)
    centre = (points.min(axis=0) + points.max(axis=0)) / 2
    parts = [(s - centre) * scale + centre for s in parts]
    points = np.concatenate(parts)
    x0 = max(0, int(np.floor(points[:, 0].min())) - margin)
    y0 = max(0, int(np.floor(points[:, 1].min())) - margin)
    x1 = min(width, int(np.ceil(points[:, 0].max())) + margin + 1)
    y1 = min(height, int(np.ceil(points[:, 1].max())) + margin + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(s - (x0, y0)).astype(np.int32).reshape(-1, 1, 2) for s in parts],
                 255)
    if not mask.any():
        return None
    if grow:
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                          (2 * grow + 1, 2 * grow + 1)))
    alpha = mask.astype(np.float32) / 255.0
    if feather:
        alpha = np.maximum(alpha, cv2.GaussianBlur(alpha, (feather, feather), 0))
    return x0, y0, alpha


def blur_shapes(im0, shapes, *, blur_ratio, rounded_edges=0, progressive_blur=0,
                roi_enlargement=1.0):
    """Floute les FORMES des détections segmentées d'une image (`shapes` : une liste de
    polygones par détection) — avec les MÊMES finitions qu'un rectangle : l'agrandissement
    multiplie l'aire (`Bounds.scale`), les bords élargissent de `rounded_edges` pixels (en
    arrondi), le flou progressif fond le bord VERS L'EXTÉRIEUR — la forme elle-même reste
    entièrement floutée, quel que soit le réglage. Les couvertures se réunissent (maximum) et la
    zone qui les contient est floutée UNE fois : deux formes voisines ne se floutent pas l'une
    l'autre en cascade.

    ⚠ Remplace le 2026-10-05 `blur_segmentation` → `apply_mask_blur` (card #1034, SAM3) : ce
    chemin ignorait l'agrandissement et les bords, fondait le bord VERS L'INTÉRIEUR — mesuré sur
    100 images de #1034 au flou progressif 100 : 0,2 % des pixels des formes entièrement
    floutés, les plaques restaient LISIBLES —, et flouait l'IMAGE ENTIÈRE pour chaque détection,
    plus des diagnostics plein cadre imprimés à chaque fois (656 ms par image, plus long que la
    détection). Le flou porte sur la zone des formes élargie de la demi-taille du noyau :
    identique au pixel près dans les formes (le noyau n'y voit rien au-delà), au coût du
    recadrage (proposé dès le 2026-08-19, PROJECT_STATUS « FLOUTAGE ANONYMIZER »)."""
    blur_ratio = normalize_blur_ratio(blur_ratio)
    grow = max(0, int(rounded_edges or 0))
    feather = max(0, int(progressive_blur or 0))
    if feather and feather % 2 == 0:
        feather += 1
    options = dict(scale=sqrt(max(float(roi_enlargement or 1.0), 1e-6)), grow=grow,
                   feather=feather, margin=blur_ratio // 2 + grow + feather + 2)
    pieces = [piece for piece in (_shape_alpha(polygons, im0.shape, **options)
                                  for polygons in shapes or []) if piece]
    if not pieces:
        return im0
    x0 = min(x for x, _y, _a in pieces)
    y0 = min(y for _x, y, _a in pieces)
    x1 = max(x + a.shape[1] for x, _y, a in pieces)
    y1 = max(y + a.shape[0] for _x, y, a in pieces)
    alpha = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
    for x, y, piece in pieces:
        window = alpha[y - y0:y - y0 + piece.shape[0], x - x0:x - x0 + piece.shape[1]]
        np.maximum(window, piece, out=window)
    region = im0[y0:y1, x0:x1]
    blurred = cv2.GaussianBlur(region, (blur_ratio, blur_ratio), 0)
    alpha = alpha[:, :, None]
    im0[y0:y1, x0:x1] = (blurred * alpha + region * (1.0 - alpha)).astype(np.uint8)
    return im0


def apply_progressive_blur(im0, bounds, blur_ratio, progressive_blur):
    """
    Apply progressive blur with elliptical gradient mask.
    The blur is stronger at the center and fades at the edges.

    Args:
        im0: Input image (numpy array)
        bounds: Bounds object defining the area to blur
        blur_ratio: Blur kernel size (must be odd)
        progressive_blur: Progressive blur strength (must be odd)

    Returns:
        Modified image with progressive blur applied
    """
    x, y = bounds.x_min, bounds.y_min
    w, h = bounds.x_max - bounds.x_min, bounds.y_max - bounds.y_min

    # Validate dimensions
    if w <= 0 or h <= 0:
        print(f"[apply_progressive_blur] Invalid dimensions: w={w}, h={h}")
        return im0

    # Area to be blurred
    blur_area = im0[y:y + h, x:x + w]

    # Check if blur area is valid
    if blur_area.size == 0:
        print(f"[apply_progressive_blur] Empty blur area")
        return im0

    # Progressive mask (blurred gradient at center)
    mask = np.zeros((h, w), dtype=np.uint8)
    center, axes = (w // 2, h // 2), (w // 2, h // 2)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)

    # Apply an additional blur to the mask to make it progressive
    blur_strength = max(1, progressive_blur)
    if blur_strength % 2 == 0:
        blur_strength += 1
    smooth_mask = cv2.GaussianBlur(mask, (blur_strength, blur_strength), 0)

    # Convert smoothed mask into 3 channels
    smooth_mask_3ch = cv2.merge([smooth_mask] * 3)

    # Blur the image in the relevant area
    blurred = cv2.GaussianBlur(blur_area, (blur_ratio, blur_ratio), 0)

    # Apply the progressive mask
    blended = (blurred * (smooth_mask_3ch / 255.0) + blur_area * (1 - smooth_mask_3ch / 255.0)).astype(np.uint8)
    im0[y:y + h, x:x + w] = blended

    return im0


def apply_simple_blur(im0, bounds, blur_ratio):
    """
    Apply simple Gaussian blur to a region.

    Args:
        im0: Input image (numpy array)
        bounds: Bounds object defining the area to blur
        blur_ratio: Blur kernel size (must be odd)

    Returns:
        Modified image with blur applied
    """
    x, y = bounds.x_min, bounds.y_min
    w, h = bounds.x_max - bounds.x_min, bounds.y_max - bounds.y_min

    # Validate dimensions
    if w <= 0 or h <= 0:
        print(f"[apply_simple_blur] Invalid dimensions: w={w}, h={h}")
        return im0

    # Area to be blurred
    blur_area = im0[y:y + h, x:x + w]

    # Check if blur area is valid
    if blur_area.size == 0:
        print(f"[apply_simple_blur] Empty blur area")
        return im0

    # Apply Gaussian blur
    blurred = cv2.GaussianBlur(blur_area, (blur_ratio, blur_ratio), 0)
    im0[y:y + h, x:x + w] = blurred

    return im0


def normalize_blur_ratio(blur_ratio):
    """
    Ensure blur ratio is valid (positive and odd).

    Args:
        blur_ratio: Input blur ratio value

    Returns:
        Normalized blur ratio (positive odd integer)
    """
    blur_ratio = int(blur_ratio)
    if blur_ratio <= 0:
        blur_ratio = 1
    if blur_ratio % 2 == 0:
        blur_ratio += 1
    return blur_ratio


def blur_detection(im0, detection_box, label, blur_ratio, rounded_edges, progressive_blur, roi_enlargement):
    """
    Blur a single detection on the image.

    Args:
        im0: Input image (numpy array)
        detection_box: Detection bounding box (xyxy format)
        label: Class label of the detection
        blur_ratio: Blur kernel size
        rounded_edges: Amount to expand the blur area
        progressive_blur: Progressive blur strength (0 to disable)
        roi_enlargement: Scale factor for enlarging the ROI

    Returns:
        Modified image with detection blurred
    """
    # Validate detection_box
    if detection_box is None or len(detection_box) < 4:
        print(f"[blur_detection] Invalid detection_box: {detection_box}")
        return im0

    # Extract bounding box coordinates
    x, y = int(detection_box[0]), int(detection_box[1])
    w, h = int(detection_box[2]) - x, int(detection_box[3]) - y

    # Validate dimensions
    if w <= 0 or h <= 0:
        print(f"[blur_detection] Invalid dimensions: w={w}, h={h} from bbox={detection_box}")
        return im0

    # Ensure coordinates are within image bounds
    img_h, img_w = im0.shape[:2]
    if x < 0 or y < 0 or x >= img_w or y >= img_h:
        print(f"[blur_detection] Coordinates out of bounds: x={x}, y={y} for image {img_w}x{img_h}")
        # Clamp to valid range
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        w = min(w, img_w - x)
        h = min(h, img_h - y)

    # Final dimension check
    if w <= 0 or h <= 0:
        print(f"[blur_detection] Dimensions still invalid after clamping: w={w}, h={h}")
        return im0

    # Create bounds and apply transformations
    try:
        bounds = Bounds(x, y, x + w, y + h).scale(im0.shape, roi_enlargement).expand(im0.shape, rounded_edges)
    except Exception as e:
        print(f"[blur_detection] Error creating bounds: {e}")
        return im0

    # Apply appropriate blur type
    try:
        if label in ['face', 'person'] and progressive_blur > 0:
            im0 = apply_progressive_blur(im0, bounds, blur_ratio, progressive_blur)
        else:
            im0 = apply_simple_blur(im0, bounds, blur_ratio)
    except Exception as e:
        print(f"[blur_detection] Error applying blur: {e}")
        return im0

    return im0


def blur_detections(im0, detections, *, blur_ratio, rounded_edges=5, progressive_blur=0,
                    roi_enlargement=1.0):
    """Floute, sur UNE image, les détections d'un document `detections` (`common/utils/
    detections.py`) : à la FORME quand la détection en porte une (segmentation, `blur_shapes`),
    au rectangle sinon — les mêmes finitions dans les deux cas. Une détection DÉDUITE
    (interpolée, prolongée) a son rectangle ramené dans l'image d'abord.

    C'est le second temps de l'anonymisation depuis le 2026-10-04 : la détection est un process
    à part, ce floutage repart de ce qu'elle a écrit."""
    from .detections import valid_box
    blur_ratio = normalize_blur_ratio(blur_ratio)
    # Les FORMES d'abord, toutes ensemble et toutes classes (le fondu va vers l'extérieur, il ne
    # découvre jamais l'objet — contrairement à l'ellipse d'un rectangle, d'où la règle « visage,
    # personne » qui reste celle des rectangles).
    im0 = blur_shapes(im0, [det['polygons'] for det in detections or [] if det.get('polygons')],
                      blur_ratio=blur_ratio, rounded_edges=rounded_edges,
                      progressive_blur=progressive_blur, roi_enlargement=roi_enlargement)
    for det in detections or []:
        if det.get('polygons'):
            continue
        box = valid_box(det.get('box'), im0.shape) if det.get('interpolated') else det.get('box')
        if box is None:
            continue
        im0 = blur_detection(im0, box, det.get('label', ''), blur_ratio, rounded_edges,
                             progressive_blur, roi_enlargement)
    return im0
