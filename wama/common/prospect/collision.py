"""
Détection de collision PROSPECT entre deux trajectoires de rectangles orientés →
TTC (Time To Collision) et PET (Post-Encroachment Time).

Portage de CollisionDetection.m :
  - TTC : premier instant où les 2 empreintes s'intersectent AU MÊME temps.
  - PET : plus petit décalage temporel pour lequel l'empreinte 1 (avancée/reculée
    dans le temps) occupe la même place que l'empreinte 2 au temps courant.

Autonome (numpy). Les temps sont en secondes ; TTC/PET renvoyés en secondes, None si
aucune collision détectée.
"""
import numpy as np

from .geometry import rect_intersect_sat


def _row_rect(shape_row):
    """Ligne (9,) [t, 4 coins] → (4, 2)."""
    return np.array(shape_row[1:9], dtype=float).reshape(4, 2)


def _common_times(t1, t2, tol=1e-6):
    """Indices (i1, i2) des timecodes communs aux deux séries."""
    i1, i2 = [], []
    j = 0
    for a in range(len(t1)):
        while j < len(t2) and t2[j] < t1[a] - tol:
            j += 1
        if j < len(t2) and abs(t2[j] - t1[a]) <= tol:
            i1.append(a)
            i2.append(j)
    return np.array(i1, dtype=int), np.array(i2, dtype=int)


def collision_detection(shape1, shape2, compute_pet=True, max_pet_steps=None):
    """
    shape1, shape2 : (N, 9) trajectoires d'empreintes [t, x1,y1,...,x4,y4].
    Retourne dict {'ttc': float|None, 'pet': float|None, 't_collision': float|None}.
      - ttc : temps (depuis le 1er instant commun) de la 1ère collision simultanée.
      - pet : plus petit |Δt| de collision décalée (post-encroachment).
    """
    shape1 = np.asarray(shape1, dtype=float)
    shape2 = np.asarray(shape2, dtype=float)
    i1, i2 = _common_times(shape1[:, 0], shape2[:, 0])
    result = {'ttc': None, 'pet': None, 't_collision': None}
    if len(i1) < 1:
        return result

    t0 = shape1[i1[0], 0]

    # ── TTC : collision au même instant ──────────────────────────────────
    for k in range(len(i1)):
        r1 = _row_rect(shape1[i1[k]])
        r2 = _row_rect(shape2[i2[k]])
        if rect_intersect_sat(r1, r2):
            result['ttc'] = float(shape1[i1[k], 0] - t0)
            result['t_collision'] = float(shape1[i1[k], 0])
            break

    # ── PET : collision avec décalage temporel (sliding) ─────────────────
    if compute_pet:
        n = len(i1)
        max_delta = max_pet_steps if max_pet_steps is not None else n
        best_pet = None
        for k in range(n):
            r2 = _row_rect(shape2[i2[k]])
            for delta in range(1, max_delta):
                # empreinte 1 avancée de delta pas
                fa = i1[k] + delta
                if fa < len(shape1) and rect_intersect_sat(_row_rect(shape1[fa]), r2):
                    pet = abs(shape1[fa, 0] - shape1[i1[k], 0])
                    best_pet = pet if best_pet is None else min(best_pet, pet)
                    break
                # empreinte 1 reculée de delta pas
                fb = i1[k] - delta
                if fb >= 0 and rect_intersect_sat(_row_rect(shape1[fb]), r2):
                    pet = abs(shape1[fb, 0] - shape1[i1[k], 0])
                    best_pet = pet if best_pet is None else min(best_pet, pet)
                    break
        result['pet'] = float(best_pet) if best_pet is not None else None

    return result
