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
import cv2
import numpy as np
from .bounds import Bounds


def _shape_alpha(polygons, shape, *, enlargement, grow, feather, margin):
    """(x0, y0, alpha) d'UNE forme : sa couverture (0 → 1) dans sa boîte élargie de `margin`,
    agrandissement, élargissement et fondu extérieur compris ; None si elle est vide.
    L'agrandissement est celui d'un rectangle (`Bounds.scale`, non borné à l'image : la forme
    garde ses proportions au bord), la forme y est portée par `detections.fit_polygons` et
    dessinée par `detections.polygons_to_mask` — les gestes communs des détections."""
    from .detections import box_of_polygons, fit_polygons, polygons_to_mask
    polygons = [p for p in polygons or [] if len(p) >= 3]
    if not polygons:
        return None
    height, width = shape[:2]
    box = box_of_polygons(polygons)
    scaled = Bounds(*box).scale(None, enlargement)
    polygons = fit_polygons(polygons, box, [scaled.x_min, scaled.y_min, scaled.x_max, scaled.y_max])
    x0 = max(0, scaled.x_min - margin)
    y0 = max(0, scaled.y_min - margin)
    x1 = min(width, scaled.x_max + margin + 1)
    y1 = min(height, scaled.y_max + margin + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    mask = polygons_to_mask([[[x - x0, y - y0] for x, y in polygon] for polygon in polygons],
                            (y1 - y0, x1 - x0))
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
    options = dict(enlargement=max(float(roi_enlargement or 1.0), 1e-6), grow=grow,
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


def _rounded_mask(height, width, radius):
    """Masque 0/255 d'un rectangle de `height` × `width` aux coins arrondis de `radius` pixels,
    borné au demi-petit côté."""
    mask = np.zeros((height, width), np.uint8)
    r = int(max(0, min(radius, (min(height, width) - 1) // 2)))
    if r == 0:
        mask[:] = 255
        return mask
    cv2.rectangle(mask, (r, 0), (width - 1 - r, height - 1), 255, -1)
    cv2.rectangle(mask, (0, r), (width - 1, height - 1 - r), 255, -1)
    for cx, cy in ((r, r), (width - 1 - r, r), (r, height - 1 - r), (width - 1 - r, height - 1 - r)):
        cv2.circle(mask, (cx, cy), r, 255, -1)
    return mask


def blur_box_inside(im0, box, *, intensity, rounded_edges, progressive_blur, roi_enlargement,
                    min_sigma=2.0):
    """Floute UN rectangle avec des finitions TENUES DANS LA ZONE (boîte × `roi_enlargement`,
    en aire comme `Bounds.scale`) — rien n'est ajouté au-delà :
      • `intensity` (1–99) : écart-type du flou en POURCENTAGE du petit côté de la boîte (plancher
        `min_sigma` px). Le flou suit la taille de l'objet, pas la résolution de la vidéo : un
        noyau fixe en pixels rase une petite plaque en aplat et laisse une grande trop nette ;
      • le flou se calcule sur la zone ÉLARGIE de trois écarts-types, puis se compose : il se
        mélange au voisinage au lieu d'être un rectangle découpé ;
      • `rounded_edges` : rayon des coins de la zone, en pixels pris SUR la zone ;
      • `progressive_blur` (0–100) : part de la marge zone − boîte où le flou se fond vers le
        bord de la zone. La boîte détectée reste floutée en ENTIER : c'est l'agrandissement de
        la zone qui fait la place de l'arrondi et du fondu.
    Rend l'image modifiée en place."""
    height, width = im0.shape[:2]
    x0, y0, x1, y1 = [float(v) for v in box[:4]]
    w, h = x1 - x0, y1 - y0
    if w <= 1 or h <= 1:
        return im0
    sigma = max(float(min_sigma), float(intensity) / 100.0 * min(w, h))
    grow = (max(float(roi_enlargement or 1.0), 1.0) ** 0.5 - 1) / 2
    mx, my = grow * w, grow * h
    zx0, zy0, zx1, zy1 = x0 - mx, y0 - my, x1 + mx, y1 + my
    pad = int(3 * sigma) + 2
    rx0, ry0 = max(0, int(zx0) - pad), max(0, int(zy0) - pad)
    rx1, ry1 = min(width, int(np.ceil(zx1)) + pad), min(height, int(np.ceil(zy1)) + pad)
    if rx1 <= rx0 or ry1 <= ry0:
        return im0
    region = im0[ry0:ry1, rx0:rx1]
    zw, zh = max(1, int(round(zx1 - zx0))), max(1, int(round(zy1 - zy0)))
    local = _rounded_mask(zh, zw, rounded_edges or 0)
    mask = np.zeros(region.shape[:2], np.uint8)
    ox, oy = int(round(zx0)) - rx0, int(round(zy0)) - ry0
    sx0, sy0 = max(0, ox), max(0, oy)
    sx1, sy1 = min(mask.shape[1], ox + zw), min(mask.shape[0], oy + zh)
    if sx1 <= sx0 or sy1 <= sy0:
        return im0
    mask[sy0:sy1, sx0:sx1] = local[sy0 - oy:sy1 - oy, sx0 - ox:sx1 - ox]
    band = max(0.0, min(float(progressive_blur or 0), 100.0)) / 100.0 * min(mx, my)
    if band >= 0.5:
        t = np.clip(cv2.distanceTransform(mask, cv2.DIST_L2, 5) / band, 0.0, 1.0)
        alpha = t * t * (3.0 - 2.0 * t)
    else:
        alpha = (mask > 0).astype(np.float32)
    # La boîte détectée reste floutée en ENTIER : arrondi et fondu ne vivent que dans la marge
    # (sans marge, un coin arrondi entamait la boîte d'un petit objet).
    bx0, by0 = max(0, int(np.floor(x0)) - rx0), max(0, int(np.floor(y0)) - ry0)
    bx1, by1 = min(alpha.shape[1], int(np.ceil(x1)) - rx0), min(alpha.shape[0], int(np.ceil(y1)) - ry0)
    if bx1 > bx0 and by1 > by0:
        alpha[by0:by1, bx0:bx1] = 1.0
    blurred = cv2.GaussianBlur(region, (0, 0), sigma)
    alpha = alpha[:, :, None]
    im0[ry0:ry1, rx0:rx1] = (blurred * alpha + region * (1.0 - alpha)).astype(np.uint8)
    return im0


def blur_detections_inside(im0, detections, *, intensity, rounded_edges, progressive_blur,
                           roi_enlargement):
    """Le floutage d'une image aux finitions tenues dans la zone (`blur_box_inside`), TOUTES
    classes — candidat esthétique (Fabien, 2026-10-29) : le cam_analyzer l'emploie pour
    l'affichage ; l'Anonymizer garde `blur_detections` tant que l'essai n'a pas convaincu. Une
    détection à forme (segmentation) passe par `blur_shapes`, comme dans `blur_detections`."""
    from .detections import valid_box
    shapes = [det['polygons'] for det in detections or [] if det.get('polygons')]
    if shapes:
        im0 = blur_shapes(im0, shapes, blur_ratio=normalize_blur_ratio(
            max(3, int(intensity))), rounded_edges=rounded_edges,
            progressive_blur=progressive_blur, roi_enlargement=roi_enlargement)
    for det in detections or []:
        if det.get('polygons'):
            continue
        box = valid_box(det.get('box'), im0.shape) if det.get('interpolated') else det.get('box')
        if box is None:
            continue
        im0 = blur_box_inside(im0, box, intensity=intensity, rounded_edges=rounded_edges,
                              progressive_blur=progressive_blur, roi_enlargement=roi_enlargement)
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
