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
    # État : [x, vx, ax, y, vy, ay] (2 axes indépendants).
    x = np.zeros(6)
    x[0], x[3] = traj[0, 1], traj[0, 2]
    P = np.eye(6) * 10.0
    H = np.zeros((2, 6)); H[0, 0] = 1; H[1, 3] = 1
    R = np.eye(2) * r
    for i in range(1, len(traj)):
        dt = traj[i, 0] - traj[i - 1, 0]
        if dt <= 0:
            continue
        F = np.eye(6)
        for base in (0, 3):
            F[base, base + 1] = dt
            F[base, base + 2] = 0.5 * dt * dt
            F[base + 1, base + 2] = dt
        # Bruit process (accélération aléatoire).
        G = np.array([0.5 * dt * dt, dt, 1.0])
        Qb = np.outer(G, G) * q
        Q = np.zeros((6, 6)); Q[0:3, 0:3] = Qb; Q[3:6, 3:6] = Qb
        # Prédiction.
        x = F @ x
        P = F @ P @ F.T + Q
        # Mise à jour.
        z = np.array([traj[i, 1], traj[i, 2]])
        y = z - H @ x
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ y
        P = (np.eye(6) - K @ H) @ P
    return np.array([x[0], x[3], x[1], x[4], x[2], x[5]])   # [x,y,vx,vy,ax,ay]


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
