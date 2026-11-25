"""Les ATTRIBUTS d'un objet détecté — couleur, taille, profondeur — rangés dans le document
`detections` (`common/utils/detections.py`), sous `attrs`, objet par objet.

Né le 2026-11-24 (`ROADMAP §17quater` B, décision de Fabien : « couleur et profondeur d'abord,
relations ensuite ») : une étape QUALIFICATION entre la détection et ce qui la consomme (le
floutage de l'anonymizer, demain le Detector et l'annotation du monde Data). Les attributs sont
DÉTERMINISTES et explicables — le concile (2026-11-19) les a validés tels quels : la couleur est
celle de la majorité des pixels de l'objet (teinte, saturation, valeur), la taille sa part de
l'image, la profondeur la médiane de la carte de profondeur sous lui.

    det['attrs'] = {'color': 'red', 'color_share': 0.42,     # couleur majoritaire, sa part
                    'size': 'small', 'area': 0.0041,          # part de l'image couverte
                    'depth': 3.2, 'plane': 'foreground'}      # médiane sous l'objet ; plan

  • `color` : un nom du vocabulaire `COLORS` (anglais, comme les libellés) ;
  • `size`  : `small` (< `SMALL_AREA` de l'image), `medium`, `large` (≥ `LARGE_AREA`) ;
  • `plane` : `foreground` quand l'objet est plus PROCHE que la médiane de la scène, sinon
    `background` ; `depth` est en mètres si le modèle de profondeur le déclare (`metric`, écrit au
    niveau du document), à une échelle près sinon — le plan, lui, ne dépend pas de l'échelle.

Un attribut qu'on ne sait pas dire (objet trop petit, profondeur non calculée sur cette image)
est ABSENT : une sélection ne l'écarte jamais (`detections.without_attributes`) — ce qu'on n'a pas
vu n'est jamais laissé net.

Aucun modèle n'est chargé ici : la carte de profondeur est passée par l'appelant
(`depth_of`, typiquement `common/backends/depth_engine.estimate_depth`), qui l'obtient par la
route des modèles.

Les attributs se DEMANDENT aussi (2026-11-25, `ROADMAP §17quater` B) : un concept compris d'une
description (« red car », « small face in the background ») se lit en concept + attributs
(`read_concept`), avec les MÊMES vocabulaires — ce qu'on sait dire d'un objet est ce qu'on sait
en demander. Le routeur commun en tire son plan (`detection_ensemble.route_concepts`), le
document le garde, la sélection le suit (`detections.within_request`).
"""
from __future__ import annotations

import numpy as np

#: Les couleurs nommées, dans l'ordre où une sélection les propose.
COLORS = ('red', 'orange', 'yellow', 'green', 'cyan', 'blue', 'purple', 'pink', 'brown',
          'white', 'gray', 'black')
#: Les tailles, de la plus petite à la plus grande.
SIZES = ('small', 'medium', 'large')
#: Les plans, du plus proche au plus lointain.
PLANES = ('foreground', 'background')

#: Part de l'image en deçà de laquelle un objet est PETIT, et au-delà de laquelle il est GRAND.
SMALL_AREA = 0.01
LARGE_AREA = 0.10
#: Pixels sous lesquels un objet est trop petit pour qu'on dise sa couleur.
MIN_COLOR_PIXELS = 30

#: Le nom de l'attribut que dit chaque valeur des vocabulaires (`red` → `color`).
VALUE_ATTRIBUTE = {**{c: 'color' for c in COLORS}, **{s: 'size' for s in SIZES},
                   **{p: 'plane' for p in PLANES}}
#: Les graphies qu'un modèle de langue écrit pour une valeur sans écrire son nom.
_SYNONYMS = {'grey': 'gray', 'violet': 'purple', 'big': 'large', 'tiny': 'small'}
#: Les RANGS qu'une description demande (« la plus proche »), et ce qui les classe : l'attribut
#: lu et le sens — le premier de l'image après tri est le seul gardé (`detections.within_request`).
RANKS = {'nearest': ('depth', False), 'farthest': ('depth', True),
         'largest': ('area', True), 'smallest': ('area', False)}
_RANK_WORDS = {'nearest': 'nearest', 'closest': 'nearest', 'farthest': 'farthest',
               'furthest': 'farthest', 'largest': 'largest', 'biggest': 'largest',
               'smallest': 'smallest'}
#: Les mots qui disent qu'un objet APPARTIENT à un autre (« face of person », « logo on car ») —
#: son centre est dans la boîte de l'autre (`wama_data…shapes.box_centre_inside`).
RELATION_WORDS = ('of', 'on')
_ARTICLES = ('the', 'a', 'an')

# Teintes OpenCV (0-180) → nom : bornes HAUTES exclues, dans l'ordre. Le rouge enjambe 0.
_HUES = ((8, 'red'), (20, 'orange'), (33, 'yellow'), (78, 'green'), (95, 'cyan'),
         (130, 'blue'), (150, 'purple'), (170, 'pink'), (181, 'red'))


def _mask_of(det: dict, shape) -> 'np.ndarray':
    """Le masque booléen de l'objet : son contour quand il en a un, sa boîte sinon."""
    from wama.common.utils.detections import polygons_to_mask
    h, w = shape[:2]
    if det.get('polygons'):
        mask = np.asarray(polygons_to_mask(det['polygons'], (h, w))) > 0
        if mask.any():
            return mask
    x1, y1, x2, y2 = [int(v) for v in det.get('box') or (0, 0, 0, 0)]
    mask = np.zeros((h, w), dtype=bool)
    mask[max(0, y1):max(0, min(h, y2)), max(0, x1):max(0, min(w, x2))] = True
    return mask


def _pixel_names(hsv: 'np.ndarray') -> 'np.ndarray':
    """Le nom de couleur de chaque pixel HSV (N×3, OpenCV), en rangs de `COLORS`."""
    h, s, v = hsv[:, 0].astype(int), hsv[:, 1].astype(int), hsv[:, 2].astype(int)
    index = {name: i for i, name in enumerate(COLORS)}
    out = np.full(len(hsv), index['red'], dtype=int)
    low = 0
    for high, name in _HUES:
        out[(h >= low) & (h < high)] = index[name]
        low = high
    out[(out == index['orange']) & (v < 150)] = index['brown']
    achromatic = s < 40                     # peu saturé : blanc ou gris, quelle que soit la teinte
    out[achromatic] = np.where(v[achromatic] > 200, index['white'], index['gray'])
    out[v < 50] = index['black']            # trop sombre pour qu'une teinte se dise
    return out


def dominant_color(image_bgr, det: dict) -> dict:
    """La couleur de la MAJORITÉ des pixels de l'objet, et sa part — `{}` quand l'objet est trop
    petit pour la dire (`MIN_COLOR_PIXELS`)."""
    import cv2
    mask = _mask_of(det, image_bgr.shape)
    pixels = image_bgr[mask]
    if len(pixels) < MIN_COLOR_PIXELS:
        return {}
    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    counts = np.bincount(_pixel_names(hsv), minlength=len(COLORS))
    best = int(counts.argmax())
    return {'color': COLORS[best], 'color_share': round(float(counts[best]) / len(hsv), 3)}


def size_of(det: dict, width: int, height: int) -> dict:
    """La part de l'image que couvre la boîte de l'objet, et sa classe de taille."""
    total = float(width or 0) * float(height or 0)
    x1, y1, x2, y2 = [float(v) for v in det.get('box') or (0, 0, 0, 0)]
    if total <= 0:
        return {}
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1) / total
    size = 'small' if area < SMALL_AREA else ('large' if area >= LARGE_AREA else 'medium')
    return {'size': size, 'area': round(area, 4)}


def depth_of(depth_map, det: dict, scene_depth: float) -> dict:
    """La profondeur médiane sous l'objet et son plan, par rapport à la médiane de la scène
    (`scene_depth`) — `{}` quand la carte ne dit rien sous lui."""
    mask = _mask_of(det, depth_map.shape)
    values = np.asarray(depth_map)[mask]
    values = values[np.isfinite(values)]
    if not len(values):
        return {}
    depth = float(np.median(values))
    return {'depth': round(depth, 2),
            'plane': 'foreground' if depth < float(scene_depth) else 'background'}


def qualify(doc: dict, frames, *, color: bool = True, size: bool = True, depth=None,
            depth_every: int = 1) -> dict:
    """Le document QUALIFIÉ — une copie, l'original intact : chaque détection reçoit ses
    attributs (`attrs`). `frames` rend `(index, image BGR)` des images qui portent des
    détections, dans l'ordre (`iter_frames`). `depth` : une fonction image → carte de profondeur
    (même taille ou non : le masque se pose sur la carte), appelée une image sur `depth_every`
    (une vidéo : une par seconde suffit à dire un plan) ; sur les autres, un objet SUIVI (`track`)
    reprend la profondeur mesurée de sa piste, les autres n'en ont pas."""
    out = {**doc, 'frames': [{**frame, 'd': [dict(d) for d in frame.get('d') or []]}
                             for frame in doc.get('frames') or []]}
    out.pop('_index', None)
    by_index = {frame['i']: frame for frame in out['frames']}
    width, height = doc.get('width') or 0, doc.get('height') or 0
    step = max(1, int(depth_every or 1))
    track_depths = {}
    for index, image in frames:
        frame = by_index.get(index)
        if frame is None or image is None:
            continue
        depth_map = depth(image) if depth is not None and index % step == 0 else None
        scene = float(np.nanmedian(depth_map)) if depth_map is not None else None
        for det in frame['d']:
            attrs = dict(det.get('attrs') or {})
            if color:
                attrs.update(dominant_color(image, det))
            if size:
                attrs.update(size_of(det, width or image.shape[1], height or image.shape[0]))
            if depth_map is not None:
                found = depth_of(depth_map, det, scene)
                attrs.update(found)
                if found and det.get('track'):
                    track_depths.setdefault(det['track'], []).append(found)
            if attrs:
                det['attrs'] = attrs
    if track_depths:
        for frame in out['frames']:
            for det in frame['d']:
                measured = track_depths.get(det.get('track'))
                if measured and 'plane' not in (det.get('attrs') or {}):
                    planes = [m['plane'] for m in measured]
                    det['attrs'] = {**(det.get('attrs') or {}),
                                    'depth': round(float(np.median([m['depth'] for m in measured])), 2),
                                    'plane': max(set(planes), key=planes.count)}
    out['qualified'] = [name for name, on in (('color', color), ('size', size),
                                              ('depth', depth is not None)) if on]
    return out


def read_concept(phrase: str) -> tuple:
    """`(concept, attributs)` d'un concept COMPRIS d'une description — « red car » →
    `('car', {'color': 'red'})`, « small face in the background » → `('face', {'size': 'small',
    'plane': 'background'})`. Lus : les valeurs des vocabulaires (`VALUE_ATTRIBUTE`) en tête du
    groupe nominal, une par attribut, et le plan en fin (« in the foreground »). Un concept qui ne
    serait plus rien sans eux reste tel quel (« white »), sans attribut. Aucun modèle, aucune
    langue devinée : la description a déjà été comprise en anglais par la pipeline de prompts."""
    text = ' '.join(str(phrase or '').split())
    words = text.split(' ') if text else []
    attrs = {}
    for plane in PLANES:
        for tail in (('in', 'the', plane), ('in', plane)):
            if len(words) > len(tail) and tuple(w.casefold() for w in words[-len(tail):]) == tail:
                attrs['plane'] = plane
                words = words[:-len(tail)]
                break
        if 'plane' in attrs:
            break
    while len(words) > 1:
        value = words[0].casefold()
        value = _SYNONYMS.get(value, value)
        name = VALUE_ATTRIBUTE.get(value)
        if name is None or name in attrs:
            break
        attrs[name] = value
        words = words[1:]
    return ' '.join(words), attrs


def read_request(phrase: str) -> dict:
    """La DEMANDE que porte un concept compris (2026-11-25, `ROADMAP §17quater` B : relations et
    rang) — `{'phrase'}` et, quand ils sont dits, `'rank'` (`RANKS`) et `'of'` (la phrase de
    l'objet auquel il appartient) : « nearest face of red person » → `{'phrase': 'face', 'rank':
    'nearest', 'of': 'red person'}`. Le rang se lit en tête, la relation au premier mot de
    `RELATION_WORDS` entre deux groupes ; `phrase` et `of` se lisent ensuite par `read_concept`.
    Les articles de tête sont ignorés. Rien n'est deviné : ce qui ne suit pas ces formes reste
    la phrase."""
    words = [w for w in ' '.join(str(phrase or '').split()).split(' ') if w]
    while len(words) > 1 and words[0].casefold() in _ARTICLES:
        words = words[1:]
    out = {}
    if len(words) > 1 and words[0].casefold() in _RANK_WORDS:
        out['rank'] = _RANK_WORDS[words[0].casefold()]
        words = words[1:]
    for i, word in enumerate(words):
        if 0 < i < len(words) - 1 and word.casefold() in RELATION_WORDS:
            owner = words[i + 1:]
            while len(owner) > 1 and owner[0].casefold() in _ARTICLES:
                owner = owner[1:]
            out['of'] = ' '.join(owner)
            words = words[:i]
            break
    out['phrase'] = ' '.join(words)
    return out


def measures_of(step) -> set:
    """Ce qu'il faut MESURER sur les objets détectés pour répondre à un pas du plan du routeur
    (`detection_ensemble.route_concepts`) : `attributes` (couleur, taille — `qualify`) pour ses
    attributs, ceux de l'objet auquel il appartient, ou un rang ; `depth` en plus pour un plan
    demandé ou un rang de distance. Une relation sans attribut ne mesure rien : la boîte suffit.
    Chaque app traduit ces mesures en SES réglages (l'anonymizer : son étape « Qualification »)."""
    attrs = [step.get('attrs') or {}, (step.get('of') or {}).get('attrs') or {}]
    rank = RANKS.get(step.get('rank') or '')
    need = {'attributes'} if (any(attrs) or rank) else set()
    if any('plane' in a for a in attrs) or (rank and rank[0] == 'depth'):
        need |= {'attributes', 'depth'}
    return need


def compatible(attrs: dict, wanted: dict) -> bool:
    """Un objet qualifié (`attrs`) répond-il à la demande (`wanted`) ? Un attribut qu'il ne porte
    pas ne l'écarte jamais — ce qu'on n'a pas vu n'est pas laissé net."""
    attrs = attrs or {}
    return all(attrs.get(name) in (None, value) for name, value in (wanted or {}).items())


def iter_frames(source: str, frame_numbers, *, media: str = 'image'):
    """`(index, image BGR)` des images `frame_numbers` d'un média, dans l'ordre — une image se lit une
    fois, une vidéo d'un seul passage (aucun saut : la lecture séquentielle est la seule exacte
    image par image)."""
    import cv2
    wanted = sorted({int(i) for i in frame_numbers})
    if not wanted:
        return
    if media != 'video':
        image = cv2.imread(source, cv2.IMREAD_COLOR)
        if image is not None:
            yield wanted[0], image
        return
    capture = cv2.VideoCapture(source)
    try:
        index, pending = 0, set(wanted)
        last = wanted[-1]
        while index <= last:
            ok, image = capture.read()
            if not ok:
                break
            if index in pending:
                yield index, image
            index += 1
    finally:
        capture.release()
