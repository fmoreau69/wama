"""
Les DÉTECTIONS d'un média, sur disque — le type de donnée commun `detections`
(`common/catalog/data_types.DataType.DETECTIONS` : objets détectés par frame — frame, bbox,
classe, piste).

Née le 2026-10-04 (décision de Fabien : « on sépare détection/segmentation et floutage dans
l'anonymizer ») : la détection devient un PROCESS de la card, son résultat doit donc VIVRE entre
deux lancements. Le floutage, l'aperçu « détection » et demain une fonction du monde Data lisent
le même document.

Le document (JSON, une ligne par frame QUI A des détections — un média sans objet ne coûte rien) :

    {"kind": "detections", "version": 1,
     "media": "image" | "video", "width": W, "height": H, "fps": F, "frame_count": N,
     "engine": "yolo" | "sam3", "models": [...], "classes": [...], "prompt": "...",
     "frames": [{"i": 0, "d": [{"track": "m0:3", "label": "face", "conf": 0.91,
                               "box": [x1, y1, x2, y2], "polygons": [[[x, y], ...], ...]}]}]}

  • `box` toujours ; `polygons` quand le modèle SEGMENTE (contour de l'objet, en pixels, un ou
    plusieurs morceaux) — c'est ce que le floutage suit plutôt que le rectangle ;
  • `track` : identifiant de PISTE préfixé du rang du modèle (`m<rang>:<id>`) — deux modèles
    numérotent leurs pistes indépendamment ; sans piste (SAM3 image par image), absent.

Le module ne connaît ni Django ni l'anonymizer : géométrie (masque ↔ polygones), lecture et
écriture, interpolation des trous d'une piste, dessin d'aperçu.
"""
from __future__ import annotations

import json
import os

KIND = 'detections'
VERSION = 1


def new_document(*, media: str, width: int, height: int, fps: float = 0.0,
                 frame_count: int = 1, engine: str = '', models=(), classes=(),
                 prompt: str = '') -> dict:
    """Un document vide, prêt à recevoir ses frames (`add`)."""
    return {'kind': KIND, 'version': VERSION, 'media': media, 'width': int(width or 0),
            'height': int(height or 0), 'fps': float(fps or 0.0),
            'frame_count': int(frame_count or 0), 'engine': engine, 'models': list(models),
            'classes': list(classes), 'prompt': prompt or '', 'frames': []}


def detection(*, box, label: str = '', conf: float = 1.0, track=None, polygons=None) -> dict:
    """Une détection au format du document : entiers pour les pixels, confiance arrondie."""
    entry = {'label': str(label or ''), 'conf': round(float(conf), 3),
             'box': [int(round(float(v))) for v in list(box)[:4]]}
    if track is not None:
        entry['track'] = str(track)
    if polygons:
        entry['polygons'] = polygons
    return entry


def add(doc: dict, frame_index: int, detections) -> None:
    """Range les détections d'UNE frame (rien n'est écrit pour une frame vide). Deux appels
    pour la même frame (deux modèles) se réunissent."""
    found = [d for d in (detections or []) if d]
    if not found:
        return
    index = doc.setdefault('_index', {})
    at = index.get(frame_index)
    if at is None:
        index[frame_index] = len(doc['frames'])
        doc['frames'].append({'i': int(frame_index), 'd': found})
    else:
        doc['frames'][at]['d'].extend(found)


def write(path: str, doc: dict) -> str:
    """Écrit le document (frames ordonnées) ; rend le chemin."""
    clean = {k: v for k, v in doc.items() if not k.startswith('_')}
    clean['frames'] = sorted(clean.get('frames') or [], key=lambda f: f['i'])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as out:
        json.dump(clean, out, separators=(',', ':'), ensure_ascii=False)
    return path


def read(path: str) -> dict:
    """Lit un document ; lève `ValueError` si ce n'en est pas un."""
    with open(path, encoding='utf-8') as source:
        doc = json.load(source)
    if not isinstance(doc, dict) or doc.get('kind') != KIND:
        raise ValueError(f"{os.path.basename(path)} : pas un document de détections")
    return doc


def count(doc: dict) -> int:
    """Le nombre de détections du document (toutes frames)."""
    return sum(len(f.get('d') or []) for f in doc.get('frames') or [])


# ── Géométrie ─────────────────────────────────────────────────────────────────────────────────
def mask_to_polygons(mask, epsilon: float = 1.0, min_area: float = 4.0) -> list:
    """Contours d'un masque (H×W, 0-1 ou 0-255) en polygones entiers, simplifiés à `epsilon`
    pixel près — ce qui rend un masque de segmentation stockable sans perdre son contour."""
    import cv2
    import numpy as np
    m = np.asarray(mask)
    if m.ndim > 2:
        m = m.squeeze()
    if m.size == 0:
        return []
    binary = (m > (0.5 if m.max() <= 1.0 else 127)).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        approx = cv2.approxPolyDP(contour, epsilon, True)
        if len(approx) >= 3:
            polygons.append([[int(x), int(y)] for x, y in approx.reshape(-1, 2)])
    return polygons


def points_to_polygons(points, epsilon: float = 1.0) -> list:
    """Un contour donné en points (ultralytics `masks.xy`) → polygones entiers simplifiés."""
    import cv2
    import numpy as np
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    if len(pts) < 3:
        return []
    approx = cv2.approxPolyDP(pts, epsilon, True).reshape(-1, 2)
    if len(approx) < 3:
        return []
    return [[[int(round(x)), int(round(y))] for x, y in approx]]


def polygons_to_mask(polygons, shape) -> 'object':
    """Le masque (uint8, 0/255) que dessinent des polygones sur une image de forme `shape`."""
    import cv2
    import numpy as np
    mask = np.zeros(tuple(shape[:2]), dtype=np.uint8)
    for polygon in polygons or []:
        pts = np.asarray(polygon, dtype=np.int32).reshape(-1, 1, 2)
        if len(pts) >= 3:
            cv2.fillPoly(mask, [pts], 255)
    return mask


def box_of_polygons(polygons) -> list:
    """Le rectangle englobant de polygones (x1, y1, x2, y2)."""
    xs = [p[0] for polygon in polygons for p in polygon]
    ys = [p[1] for polygon in polygons for p in polygon]
    return [min(xs), min(ys), max(xs), max(ys)] if xs else [0, 0, 0, 0]


def valid_box(box, shape, min_size: int = 5):
    """Le rectangle ramené dans l'image ; None s'il est vide ou plus petit que `min_size`."""
    if box is None or len(box) < 4:
        return None
    height, width = shape[:2]
    x1 = max(0, min(box[0], width))
    y1 = max(0, min(box[1], height))
    x2 = max(0, min(box[2], width))
    y2 = max(0, min(box[3], height))
    if x2 - x1 < min_size or y2 - y1 < min_size:
        return None
    return [x1, y1, x2, y2]


# ── Lecture par frame, interpolation ──────────────────────────────────────────────────────────
# Les primitives de trajectoire sont celles de la bibliothèque de fonctions COMMUNE
# (`wama_data/functions`, où le cam_analyzer prend déjà son lissage et son extrapolation) :
# recouvrement `geometry.shapes.box_iou`, trou comblé en courbe `kinematics.gap_fill.hermite_gap`.
# Importées à l'appel : lire un document ne charge pas toute la bibliothèque.

def _center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _shift(a, b) -> float:
    """Distance entre les centres de deux rectangles, en TAILLES de `a` (sa plus grande dimension)."""
    ax, ay = (a['box'][0] + a['box'][2]) / 2, (a['box'][1] + a['box'][3]) / 2
    bx, by = (b['box'][0] + b['box'][2]) / 2, (b['box'][1] + b['box'][3]) / 2
    size = max(a['box'][2] - a['box'][0], a['box'][3] - a['box'][1], 1)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 / size


def _same_object(a, b, min_iou: float, elapsed: int = 1) -> bool:
    """Deux détections, à `elapsed` frames d'écart, sont-elles le même objet ? La PISTE le dit
    quand les deux en ont une ; sinon la position — même classe, et recouvrement, ou un
    déplacement d'au plus une demi-taille plus une taille par frame écoulée (mesuré sur la card
    #1026 : des visages de 8 px qui avancent de 6 px par image ne se recouvrent plus du tout
    après trois images)."""
    if a.get('label') != b.get('label'):
        return False
    if a.get('track') is not None and b.get('track') is not None and a['track'] == b['track']:
        return True
    from wama_data.functions.geometry.shapes import box_iou
    if box_iou(a['box'], b['box']) >= min_iou:
        return True
    return _shift(a, b) <= 0.5 + max(1, elapsed)


#: Maillons sur lesquels se mesure la vitesse d'un bord de trou : une différence sur UN maillon
#: suit le tremblement de la boîte détectée (card #1026 : −22 px/image sur un visage immobile en
#: moyenne). Le cam_analyzer lit, lui, des vitesses LISSÉES.
VELOCITY_LINKS = 3


def _edge_velocity(det, frame, links_of, incoming):
    """Vitesse du centre (pixels par image) de `det` (à `frame`) : en y ARRIVANT (`incoming`,
    on remonte ses maillons entrants `links_of` = {id(dét.): maillon}) ou en en REPARTANT (ses
    maillons sortants) — mesurée de bout en bout sur au plus `VELOCITY_LINKS` maillons. Un
    maillon est (frame, dét., frame suivante, dét. suivante). None sans maillon."""
    far_frame, far = frame, det
    for _ in range(VELOCITY_LINKS):
        link = links_of.get(id(far))
        if link is None:
            break
        far_frame, far = (link[0], link[1]) if incoming else (link[2], link[3])
    if far is det:
        return None
    (x0, y0), (x1, y1) = _center(det['box']), _center(far['box'])
    elapsed = frame - far_frame                 # négatif en repartant : le signe se compense
    return ((x0 - x1) / elapsed, (y0 - y1) / elapsed)


def by_frame(doc: dict, *, interpolate: bool = False, max_gap: int = 0,
             min_iou: float = 0.2) -> dict:
    """{indice de frame: [détections]} — détections RELEVÉES, plus, si `interpolate`, celles que
    l'on déduit dans les TROUS d'un objet : entre une détection et la suivante du MÊME objet
    (`_same_object` : même piste, ou à défaut même place), au plus `max_gap` frames manquantes,
    jamais avant la première ni après la dernière. Une détection déduite porte
    `interpolated: True` et son rectangle seul : un contour ne s'interpole pas.

    Le CENTRE suit une courbe d'Hermite (`hermite_gap`, la même que les fantômes du
    cam_analyzer) : il part à la vitesse d'arrivée de l'objet et rejoint sa vitesse de reprise,
    vitesses lues sur les maillons voisins ; une droite sans elles, ou quand la courbe ferait un
    détour (seuils à l'échelle de l'objet). La TAILLE s'interpole en ligne droite.

    ⚠ Corrigé le 2026-10-05 (card #1026) : seules les détections d'une même PISTE se reliaient.
    Or le suivi ne donne une piste qu'aux objets CONFIRMÉS — 82 détections sur 533 n'en avaient
    pas — et il en donne une NOUVELLE quand il reperd l'objet : 18 trous sur 19 subsistaient."""
    frames = {}
    for frame in doc.get('frames') or []:
        frames.setdefault(int(frame['i']), []).extend(frame.get('d') or [])
    if not interpolate or max_gap <= 0:
        return frames
    seen = sorted(frames)
    position = {index: n for n, index in enumerate(seen)}
    claimed = set()                         # (frame, rang) déjà successeur d'une détection
    links = []                              # (frame, dét., frame suivante, dét. suivante)
    after, before = {}, {}                  # id(dét.) → son maillon sortant / entrant
    for index in seen:
        for det in frames[index]:
            successor = None
            for later in seen[position[index] + 1:]:
                if later - index - 1 > max_gap:
                    break
                # Dans la PREMIÈRE frame qui porte le même objet, le candidat le plus PROCHE.
                matches = [(_shift(det, other), rank, other)
                           for rank, other in enumerate(frames[later])
                           if (later, rank) not in claimed
                           and _same_object(det, other, min_iou, later - index)]
                if matches:
                    _distance, rank, other = min(matches, key=lambda m: m[0])
                    successor = (later, rank, other)
                    break
            if successor is None:
                continue
            later, rank, other = successor
            claimed.add((later, rank))
            link = (index, det, later, other)
            links.append(link)
            after[id(det)], before[id(other)] = link, link
    from wama_data.functions.kinematics.gap_fill import hermite_gap
    deduced = {}
    for link in links:
        index, det, later, other = link
        span = later - index
        if span < 2:
            continue
        # Vitesses aux bords : celle de l'ARRIVÉE (maillons entrants) et de la REPRISE (sortants).
        v0 = _edge_velocity(det, index, before, incoming=True)
        v1 = _edge_velocity(other, later, after, incoming=False)
        w0, h0 = det['box'][2] - det['box'][0], det['box'][3] - det['box'][1]
        w1, h1 = other['box'][2] - other['box'][0], other['box'][3] - other['box'][1]
        size = max(w0, h0, 1)
        c0, c1 = _center(det['box']), _center(other['box'])
        for gap_index in range(index + 1, later):
            ratio = (gap_index - index) / span
            width, height = w0 + (w1 - w0) * ratio, h0 + (h1 - h0) * ratio
            # Seuils à l'échelle de l'objet, dans le rapport de ceux du cam_analyzer (2 m et 4 m
            # pour une voiture d'environ 4,5 m : une demi-taille, une taille) ; et une droite
            # quand les allures aux bords n'expliquent pas la moitié du chemin.
            x, y = hermite_gap(c0, v0, c1, v1, span, ratio, min_bulge=size / 2,
                               overshoot_margin=size, min_speed_share=0.5)
            box = [x - width / 2, y - height / 2, x + width / 2, y + height / 2]
            deduced.setdefault(gap_index, []).append({
                'track': det.get('track'), 'label': det.get('label', ''),
                'conf': det.get('conf', 1.0), 'box': [int(round(v)) for v in box],
                'interpolated': True})
    for index, found in deduced.items():
        frames.setdefault(index, []).extend(found)
    return frames


def max_gap_for(fps: float, wanted: int) -> int:
    """Le trou le plus long que l'on comble : le RÉGLAGE, tel quel.

    ⚠ Jusqu'au 2026-10-05 il était plafonné en silence à 0,5 s de vidéo : un réglage de 50
    images valait 7 à 15 i/s (card #1026) — le réglage mentait. Le plafond protégeait d'un
    flou qui suivrait un autre objet ; c'est désormais le rattachement par piste OU par
    position (`_same_object`) qui l'évite, et le réglage dit ce qu'il fait. `fps` reste lu par
    les appelants qui raisonnent en secondes."""
    return max(0, int(wanted or 0))


# ── Rendu d'un média depuis ses détections ────────────────────────────────────────────────────
def render_media(source: str, frames: dict, paint, output_path: str, *, on_frame=None,
                 progress=None) -> str:
    """Réécrit le média `source` en peignant chaque frame avec SES détections :
    `paint(image, détections) -> image` (le floutage, ou le dessin d'aperçu). Rend le chemin
    RÉELLEMENT écrit — une vidéo sort toujours en `.mp4`, audio d'origine recollé.

    `frames`   : {indice: [détections]} (`by_frame`) ;
    `on_frame` : `callback(indice, image d'origine, image peinte, détections)` — l'aperçu
                 « pendant » de la tâche, qu'elle limite elle-même dans le temps ;
    `progress` : `callback(faites, total)`.

    Une frame sans détection est écrite telle quelle (aucun calcul)."""
    import cv2
    from .video_utils import copy_audio_to_video, is_image
    if is_image(source):
        image = cv2.imread(source)
        if image is None:
            raise RuntimeError(f"Image illisible : {os.path.basename(source)}")
        found = frames.get(0, [])
        painted = paint(image.copy(), found) if found else image
        ext = os.path.splitext(output_path)[1].lower()
        params = ([cv2.IMWRITE_JPEG_QUALITY, 95] if ext in ('.jpg', '.jpeg')
                  else [cv2.IMWRITE_PNG_COMPRESSION, 3] if ext == '.png' else [])
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        if not cv2.imwrite(output_path, painted, params):
            raise RuntimeError(f"Écriture impossible : {os.path.basename(output_path)}")
        if on_frame:
            on_frame(0, image, painted, found)
        if progress:
            progress(1, 1)
        return output_path

    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Vidéo illisible : {os.path.basename(source)}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    size = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    # Intermédiaire MJPEG (qualité haute, codec partout disponible) : ffmpeg ré-encode en H.264
    # et recolle l'audio ensuite (`copy_audio_to_video`).
    temp = os.path.splitext(output_path)[0] + '.avi'
    os.makedirs(os.path.dirname(os.path.abspath(temp)), exist_ok=True)
    writer = cv2.VideoWriter(temp, cv2.VideoWriter_fourcc(*'MJPG'), fps, size, True)
    if not writer.isOpened():
        temp = os.path.splitext(output_path)[0] + '_raw.mp4'
        writer = cv2.VideoWriter(temp, cv2.VideoWriter_fourcc(*'mp4v'), fps, size, True)
    index = 0
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                break
            found = frames.get(index, [])
            painted = paint(image.copy(), found) if found else image
            writer.write(painted)
            if on_frame:
                on_frame(index, image, painted, found)
            index += 1
            if progress:
                progress(index, total or index)
    finally:
        capture.release()
        writer.release()
    final = os.path.splitext(output_path)[0] + '.mp4'
    copy_audio_to_video(source, temp, final)
    if os.path.exists(temp) and os.path.abspath(temp) != os.path.abspath(final):
        try:
            os.remove(temp)
        except OSError:
            pass
    return final


# ── Aperçu « détection » ──────────────────────────────────────────────────────────────────────
#: Couleurs d'aperçu (BGR) : relevée, déduite.
SEEN_COLOR = (0, 200, 255)
DEDUCED_COLOR = (180, 180, 180)


def draw(image, detections, *, boxes: bool = True, labels: bool = True,
         confidence: bool = True):
    """Une COPIE de l'image avec les détections dessinées : contour plein translucide quand la
    détection en porte un, rectangle, libellé et confiance — ce que montre la face « Détection »
    de l'aperçu. Une détection déduite (interpolée) est dessinée en pointillé gris."""
    import cv2
    out = image.copy()
    overlay = out.copy()
    for det in detections or []:
        color = DEDUCED_COLOR if det.get('interpolated') else SEEN_COLOR
        for polygon in det.get('polygons') or []:
            import numpy as np
            pts = np.asarray(polygon, dtype=np.int32).reshape(-1, 1, 2)
            cv2.fillPoly(overlay, [pts], color)
            cv2.polylines(out, [pts], True, color, 2)
    if any(det.get('polygons') for det in detections or []):
        out = cv2.addWeighted(overlay, 0.35, out, 0.65, 0)
    for det in detections or []:
        color = DEDUCED_COLOR if det.get('interpolated') else SEEN_COLOR
        x1, y1, x2, y2 = det['box']
        if boxes:
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 1 if det.get('interpolated') else 2)
        text = ' '.join(t for t in (
            det.get('label', '') if labels else '',
            f"{det.get('conf', 0):.2f}" if confidence and not det.get('interpolated') else '') if t)
        if text:
            cv2.putText(out, text, (x1, max(12, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                        cv2.LINE_AA)
    return out
