"""Lisseur de trajectoire 2D — filtre de Kalman (vitesse constante) + lisseur RTS.

DOMICILE UNIQUE de cette mécanique depuis le 2026-09-05. Elle vivait dans
`wama_lab/cam_analyzer/utils/trajectory_smoother.py`, où elle ne servait que les OBJETS
mobiles du tracking 360°. Le jour où la même mécanique a dû servir la NAVETTE
(`driving.ego_trajectory_filter`), la règle « toute logique pure et réutilisable va dans
wama_data » l'a fait remonter ici ; l'ancien module DÉLÈGUE (mêmes chiffres, attesté par un
test de non-régression sur empreinte enregistrée AVANT le déplacement).

Ce que fait le passage ARRIÈRE (Rauch-Tung-Striebel), et pourquoi il compte : le filtre avant
seul a un RETARD de phase (comme une EMA) ; le passage arrière ré-estime chaque état avec le
futur ET le passé, donc le jitter de mesure est absorbé SANS déformer la manœuvre réelle.
C'est exactement la propriété que l'EMA d'affichage n'a pas (cf. `CAM_ANALYZER_CHAINE
§INVENTAIRE D.3`).

Modèle : état [x, y, vx, vy], transition vitesse-constante, bruit de processus piloté par
l'accélération (`sigma_a`, m/s²), bruit de mesure `sigma_m` (m). Lib helper (pas de
FunctionSpec, comme `collision`/`extrapolation` — exception §7bis) ; le FunctionSpec vit sur
les fonctions qui l'emploient.
"""
import numpy as np


def kalman_rts_cv(points, sigma_a=2.5, sigma_m=1.5):
    """Lisse une série [(t, x, y)] triée par t → [(t, x, y, vx, vy)] aux mêmes instants.

    Doublons de `t` tolérés (moyennés : un même objet vu par deux caméras au même instant).
    Moins de 3 points : renvoie l'entrée avec vitesses nulles (rien à lisser).
    """
    if not points:
        return []
    # Moyenne les doublons de timestamp (même véhicule vu par 2 caméras au même instant).
    acc = {}
    for t, x, y in points:
        e = acc.setdefault(round(float(t), 4), [0.0, 0.0, 0])
        e[0] += float(x)
        e[1] += float(y)
        e[2] += 1
    ts = sorted(acc)
    xs = np.array([[acc[t][0] / acc[t][2], acc[t][1] / acc[t][2]] for t in ts])
    n = len(ts)
    if n < 3:
        return [(t, float(x), float(y), 0.0, 0.0) for t, (x, y) in zip(ts, xs)]

    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
    R = np.eye(2) * (sigma_m ** 2)
    x = np.array([xs[0][0], xs[0][1], 0.0, 0.0])
    P = np.diag([sigma_m ** 2, sigma_m ** 2, 25.0, 25.0])

    x_pred = np.zeros((n, 4)); P_pred = np.zeros((n, 4, 4))
    x_filt = np.zeros((n, 4)); P_filt = np.zeros((n, 4, 4))
    Fs = np.zeros((n, 4, 4))

    for i in range(n):
        dt = ts[i] - ts[i - 1] if i else 0.0
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        q = (sigma_a ** 2)
        G = np.array([0.5 * dt * dt, 0.5 * dt * dt, dt, dt])
        Q = np.outer(G, G) * q * np.array([[1, 0, 1, 0], [0, 1, 0, 1],
                                           [1, 0, 1, 0], [0, 1, 0, 1]])
        xp = F @ x
        Pp = F @ P @ F.T + Q
        z = xs[i]
        S = H @ Pp @ H.T + R
        K = Pp @ H.T @ np.linalg.inv(S)
        x = xp + K @ (z - H @ xp)
        P = (np.eye(4) - K @ H) @ Pp
        x_pred[i], P_pred[i], x_filt[i], P_filt[i], Fs[i] = xp, Pp, x, P, F

    # Passage ARRIÈRE (RTS) : ré-estime chaque état avec l'information future.
    x_s = x_filt.copy(); P_s = P_filt.copy()
    for i in range(n - 2, -1, -1):
        F = Fs[i + 1]
        C = P_filt[i] @ F.T @ np.linalg.inv(P_pred[i + 1])
        x_s[i] = x_filt[i] + C @ (x_s[i + 1] - x_pred[i + 1])
        P_s[i] = P_filt[i] + C @ (P_s[i + 1] - P_pred[i + 1]) @ C.T

    return [(t, float(s[0]), float(s[1]), float(s[2]), float(s[3]))
            for t, s in zip(ts, x_s)]
