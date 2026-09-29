"""
Extrapolation de trajectoire Prédiction : prédiction des positions futures d'un objet
à partir de sa trajectoire observée.

Méthodes :
  - `extrapolate_speed_accel` : vitesse + accélération constantes (portage de
    ExtrTraj_ExtrTraj_WithSpeedAndAccel.m).
  - `extrapolate_kalman` : filtre de Kalman à accélération constante (2D), qui lisse
    l'observé puis prédit le futur (le code MATLAB était incomplet côté user → on
    fournit une implémentation standard propre).

Autonome (numpy pur).
"""
import numpy as np


def extrapolate_speed_accel(traj, n_future, dt=None, threshold_speed=0.0):
    """
    traj      : (M, 3) trajectoire observée [t, X, Y] (M >= 3 conseillé).
    n_future  : nombre de pas à extrapoler après le dernier point observé.
    dt        : pas de temps des pas futurs (défaut = dernier dt observé).
    Retourne  : (M + n_future, 3) trajectoire observée + extrapolée.
    """
    traj = np.asarray(traj, dtype=float)
    m = len(traj)
    if m < 2:
        return traj.copy()
    if dt is None:
        dt = traj[-1, 0] - traj[-2, 0]

    # Vitesse et accélération estimées sur les 3 derniers points (comme Prédiction).
    if m >= 3:
        p1, p2, p3 = traj[-3, 1:3], traj[-2, 1:3], traj[-1, 1:3]
        dt1 = traj[-2, 0] - traj[-3, 0]
        dt2 = traj[-1, 0] - traj[-2, 0]
        v1 = (p2 - p1) / max(dt1, 1e-9)
        v2 = (p3 - p2) / max(dt2, 1e-9)
        a = (v2 - v1) / max(dt2, 1e-9)
    else:
        v2 = (traj[-1, 1:3] - traj[-2, 1:3]) / max(dt, 1e-9)
        a = np.zeros(2)

    speed = np.hypot(v2[0], v2[1])
    vdir = v2 / speed if speed > 1e-9 else np.zeros(2)
    accel = float(np.dot(a, vdir)) if speed > 1e-9 else 0.0

    out = [traj[i].copy() for i in range(m)]
    pos = traj[-1, 1:3].copy()
    t = traj[-1, 0]
    for _ in range(n_future):
        t += dt
        if speed > threshold_speed:
            dist = speed * dt + accel * dt * dt
            pos = pos + vdir * dist
            speed = max(0.0, speed + accel * dt)
        # sinon : objet à l'arrêt, position figée
        out.append(np.array([t, pos[0], pos[1]]))
    return np.array(out)


def _ca_kalman_smooth(traj, q=1.0, r=0.5):
    """Filtre de Kalman à accélération constante (2D). Lisse l'observé et renvoie
    l'état final [x, y, vx, vy, ax, ay]. q = bruit process, r = bruit mesure."""
    traj = np.asarray(traj, dtype=float)
    # État par axe : [position, vitesse, accélération] ; colonnes = axes x et y.
    # Les deux axes sont INDÉPENDANTS et partagent F, Q, H, R et la covariance initiale :
    # leur covariance reste donc identique, un seul P 3×3 sert les deux (c'était un état
    # 6×6 bloc-diagonal, deux fois le même bloc — 2026-09-29, 40 % de la prédiction TTC/PET).
    X = np.zeros((3, 2))
    X[0] = traj[0, 1], traj[0, 2]
    P = np.eye(3) * 10.0
    H = np.array([1.0, 0.0, 0.0])
    I3 = np.eye(3)
    for i in range(1, len(traj)):
        dt = traj[i, 0] - traj[i - 1, 0]
        if dt <= 0:
            continue
        F = np.array([[1.0, dt, 0.5 * dt * dt], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
        # Bruit process (accélération aléatoire).
        G = np.array([0.5 * dt * dt, dt, 1.0])
        Q = np.outer(G, G) * q
        # Prédiction.
        X = F @ X
        P = F @ P @ F.T + Q
        # Mise à jour (mesure scalaire de la position sur chaque axe).
        S = P[0, 0] + r
        K = P[:, 0] / S
        X = X + np.outer(K, traj[i, 1:3] - X[0])
        P = (I3 - np.outer(K, H)) @ P
    return np.array([X[0, 0], X[0, 1], X[1, 0], X[1, 1], X[2, 0], X[2, 1]])   # [x,y,vx,vy,ax,ay]


def extrapolate_kalman(traj, n_future, dt=None, q=1.0, r=0.5):
    """
    Extrapolation par Kalman à accélération constante.
    traj : (M, 3) observé [t, X, Y]. Retourne (M + n_future, 3).
    """
    traj = np.asarray(traj, dtype=float)
    m = len(traj)
    if m < 2:
        return traj.copy()
    if dt is None:
        dt = traj[-1, 0] - traj[-2, 0]
    st = _ca_kalman_smooth(traj, q=q, r=r)     # [x,y,vx,vy,ax,ay]
    px, py, vx, vy, ax, ay = st
    out = [traj[i].copy() for i in range(m)]
    t = traj[-1, 0]
    for _ in range(n_future):
        t += dt
        px += vx * dt + 0.5 * ax * dt * dt
        py += vy * dt + 0.5 * ay * dt * dt
        vx += ax * dt
        vy += ay * dt
        out.append(np.array([t, px, py]))
    return np.array(out)
