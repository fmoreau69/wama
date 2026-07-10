"""
Estimation automatique de la largeur de voie depuis les marquages yolopv2.

Principe : les lignes de voie détectées (yolopv2, class 'lane (yolopv2)') sont projetées
au sol via l'homographie de la caméra, puis on mesure l'écartement latéral entre lignes
adjacentes (clusterisées pour fusionner les fragments d'une même ligne) à une distance de
référence devant la navette. La médiane sur toutes les frames = largeur de voie robuste.

Sert de 1ère passe (« band-grid self-scaling ») pour le gabarit de la vue de dessus ; le
slider UI affine ensuite pour coller précisément aux bordures.
"""
import statistics

import numpy as np
from django.apps import apps


def _cluster(xs, gap=1.3):
    """Fusionne les positions latérales proches (< gap m) en lignes distinctes."""
    xs = sorted(xs)
    out, grp = [], [xs[0]]
    for x in xs[1:]:
        if x - grp[-1] <= gap:
            grp.append(x)
        else:
            out.append(statistics.mean(grp))
            grp = [x]
    out.append(statistics.mean(grp))
    return out


def estimate_lane_width(camera, y_band=(6.0, 14.0), min_samples=20, max_frames=6000):
    """
    Largeur de voie (m) médiane, ou None si calibration absente / échantillons insuffisants.
    y_band = bande longitudinale (m devant la navette) où mesurer (homographie plus fiable
    à moyenne distance).
    """
    homo = getattr(camera, "ground_homography", None)
    if not homo or "homography" not in homo:
        return None
    H = np.array(homo["homography"], dtype=float)

    def proj(px, py):
        v = H @ np.array([px, py, 1.0])
        return (v[0] / v[2], v[1] / v[2]) if abs(v[2]) > 1e-9 else None

    DetectionFrame = apps.get_model("cam_analyzer", "DetectionFrame")
    spacings, n = [], 0
    for f in DetectionFrame.objects.filter(camera=camera).only("detections").iterator(chunk_size=2000):
        lanes = [d for d in (f.detections or [])
                 if d.get("class_name") == "lane (yolopv2)" and d.get("polygon")]
        if len(lanes) < 2:
            continue
        xs = []
        for ln in lanes:
            band = [proj(p[0], p[1]) for p in ln["polygon"]]
            band = [g for g in band if g and y_band[0] <= g[1] <= y_band[1]]
            if band:
                xs.append(statistics.mean(g[0] for g in band))
        if len(xs) < 2:
            continue
        cx = _cluster(xs)
        for i in range(len(cx) - 1):
            d = cx[i + 1] - cx[i]
            if 2.5 <= d <= 5.0:      # plage plausible pour une voie
                spacings.append(d)
        n += 1
        if n >= max_frames:
            break
    if len(spacings) < min_samples:
        return None
    return round(statistics.median(spacings), 2)
