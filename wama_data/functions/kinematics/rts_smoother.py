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


def kalman_rts_cv(points, sigma_a=2.5, sigma_m=1.5, command=None):
    """Lisse une série [(t, x, y)] triée par t → [(t, x, y, vx, vy)] aux mêmes instants.

    Doublons de `t` tolérés (moyennés : un même objet vu par deux caméras au même instant).
    Moins de 3 points : renvoie l'entrée avec vitesses nulles (rien à lisser).

    `command` (optionnel) : `callable(t) -> (ux, uy)` en m/s², l'accélération MESURÉE du
    mobile pendant l'intervalle qui se termine en `t`. Elle entre dans la PRÉDICTION
    (`x_pred = F·x + B·u`), pas dans la mesure : le modèle cesse de supposer « accélération
    inconnue de dispersion `sigma_a` » et suppose « accélération connue, à son résidu près ».
    L'appelant doit alors passer un `sigma_a` réduit à ce RÉSIDU — c'est là qu'est tout le
    gain, et le lisseur ne peut pas le deviner à sa place.
    ⚠ Le passage arrière RTS est inchangé **parce que** sa récursion lit `x_pred`, qui porte
    déjà `B·u` ; commander le filtre sans toucher au lisseur serait un défaut silencieux.
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
        if command is not None and dt > 0.0:
            ux, uy = command(0.5 * (ts[i - 1] + ts[i]))    # milieu de l'intervalle propagé
            if ux is not None and uy is not None:
                xp = xp + np.array([0.5 * dt * dt * ux, 0.5 * dt * dt * uy,
                                    dt * ux, dt * uy])
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


def kalman_rts_bias_2d(observations, query_ts, *, sigma_m=0.8, q=0.02, prior_sigma=10.0,
                       gate_sigma=3.0):
    """Biais 2D (est, nord) LENT, observé par PROJECTIONS scalaires — Kalman + lisseur RTS.

    `observations` : [(t, ne, nn, z)] — chaque mesure ne voit que la composante du biais le long
    du vecteur unitaire (ne, nn) : z = ne·b_e + nn·b_n + bruit (`sigma_m`, m). C'est le cas d'un
    recalage LATÉRAL par la voie : une ancre ne dit rien du longitudinal. Des mesures prises sur
    des routes d'orientations différentes (virage, giratoire) rendent les DEUX composantes
    observables ; entre deux ancres, le lisseur porte l'estimation au lieu de la laisser tomber.
    Modèle : marche aléatoire (b_k = b_{k-1} + w, Var(w) = `q`·dt, m²/s), a priori nul de
    dispersion `prior_sigma`. Une mesure dont l'innovation dépasse `gate_sigma` écarts-types est
    ÉCARTÉE (ancre prise sur la mauvaise route, ligne mal lue).
    Rend (b_e[], b_n[], sigma_min[], sigma_max[], n_rejected) aux instants `query_ts` (triés) ;
    `sigma_min`/`sigma_max` = écart-type dans la direction la mieux / la moins bien observée."""
    q_ts = np.asarray(query_ts, dtype=float)
    obs = sorted(((float(t), float(ne), float(nn), float(z)) for t, ne, nn, z in observations),
                 key=lambda o: o[0])
    nodes = np.unique(np.concatenate([q_ts, np.array([o[0] for o in obs], dtype=float)]))
    n = len(nodes)
    zeros = np.zeros(len(q_ts))
    if n == 0:
        return zeros, zeros, zeros + prior_sigma, zeros + prior_sigma, 0
    x_pred = np.zeros((n, 2)); P_pred = np.zeros((n, 2, 2))
    x_filt = np.zeros((n, 2)); P_filt = np.zeros((n, 2, 2))
    x = np.zeros(2)
    P = np.eye(2) * prior_sigma ** 2
    R = sigma_m ** 2
    k, rejected = 0, 0
    for i, t in enumerate(nodes):
        dt = t - nodes[i - 1] if i else 0.0
        P = P + np.eye(2) * q * dt                      # marche aléatoire : x inchangé
        x_pred[i], P_pred[i] = x, P
        while k < len(obs) and obs[k][0] <= t + 1e-9:
            _, ne, nn, z = obs[k]
            k += 1
            h = np.array([ne, nn])
            S = h @ P @ h + R
            innov = z - h @ x
            if innov * innov > gate_sigma ** 2 * S:
                rejected += 1
                continue
            K = P @ h / S
            x = x + K * innov
            P = P - np.outer(K, h @ P)
        x_filt[i], P_filt[i] = x, P
    # Passage ARRIÈRE (RTS) ; transition identité → C = P_filt · P_pred⁻¹ du nœud suivant.
    x_s = x_filt.copy(); P_s = P_filt.copy()
    for i in range(n - 2, -1, -1):
        C = P_filt[i] @ np.linalg.inv(P_pred[i + 1])
        x_s[i] = x_filt[i] + C @ (x_s[i + 1] - x_pred[i + 1])
        P_s[i] = P_filt[i] + C @ (P_s[i + 1] - P_pred[i + 1]) @ C.T
    idx = np.searchsorted(nodes, q_ts)
    idx = np.clip(idx, 0, n - 1)
    eig = np.linalg.eigvalsh(P_s[idx])                  # croissantes
    return (x_s[idx, 0], x_s[idx, 1], np.sqrt(np.maximum(eig[:, 0], 0.0)),
            np.sqrt(np.maximum(eig[:, 1], 0.0)), rejected)
