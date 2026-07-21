"""Tests de validation du portage Prédiction
(exécuter : python -m wama.common.data.functions.kinematics.test_prediction)."""
import numpy as np

from ..geometry import rect_intersect_sat, point_traj_to_shape
from . import extrapolate_speed_accel, extrapolate_kalman, collision_detection


def test_sat():
    a = np.array([[0, 0], [2, 0], [2, 2], [0, 2]], float)
    b = np.array([[1, 1], [3, 1], [3, 3], [1, 3]], float)   # chevauche
    c = np.array([[5, 5], [7, 5], [7, 7], [5, 7]], float)   # loin
    assert rect_intersect_sat(a, b) is True
    assert rect_intersect_sat(a, c) is False
    print("SAT: OK")


def test_extrapolation():
    # vitesse constante 10 m/s en x, historique de 8 points à dt=0.5 (t=0→3.5)
    ts = np.arange(0, 4.0, 0.5)
    traj = np.column_stack([ts, 10 * ts, np.zeros_like(ts)])
    ex = extrapolate_speed_accel(traj, n_future=3, dt=0.5)     # → t=5s
    assert abs(ex[-1, 1] - 50.0) < 1e-6, ex[-1]
    kf = extrapolate_kalman(traj, n_future=3, dt=0.5)
    assert abs(kf[-1, 1] - 50.0) < 1.5, kf[-1]                 # Kalman convergé
    print("Extrapolation vitesse+accel & Kalman: OK (x@5s=%.2f / %.2f)" % (ex[-1, 1], kf[-1, 1]))


def test_head_on_ttc():
    dt = 0.2
    ts = np.arange(0, 6 + dt, dt)
    # A part de (0,0) vers +x à 10 m/s ; B part de (50,0) vers -x à 10 m/s → rencontre x=25 à t=2.5s
    A = np.column_stack([ts, 10 * ts, np.zeros_like(ts)])
    B = np.column_stack([ts, 50 - 10 * ts, np.zeros_like(ts)])
    sA = point_traj_to_shape(A, length_m=4, width_m=2)
    sB = point_traj_to_shape(B, length_m=4, width_m=2)
    res = collision_detection(sA, sB)
    assert res['ttc'] is not None, res
    # collision quand les avants se touchent : ~ (25-2)/10 = 2.3s
    assert 2.0 < res['ttc'] < 2.6, res['ttc']
    print("TTC frontal: OK (TTC=%.2fs)" % res['ttc'])


def test_crossing_pet():
    dt = 0.2
    ts = np.arange(0, 6 + dt, dt)
    # A traverse l'origine (vers +x) à t=1s ; B traverse l'origine (vers +y) à t=3s → PET ~2s
    A = np.column_stack([ts, 10 * (ts - 1), np.zeros_like(ts)])
    B = np.column_stack([ts, np.zeros_like(ts), 10 * (ts - 3)])
    sA = point_traj_to_shape(A, length_m=4, width_m=2)
    sB = point_traj_to_shape(B, length_m=4, width_m=2)
    res = collision_detection(sA, sB)
    # pas de collision simultanée (ils ne sont jamais au même endroit en même temps)
    print("Croisement: TTC=%s  PET=%s" % (res['ttc'], res['pet']))
    assert res['pet'] is not None, "PET devrait être détecté (ils partagent le même point)"
    assert 1.5 < res['pet'] < 2.5, res['pet']
    print("PET croisement: OK (PET=%.2fs)" % res['pet'])


if __name__ == "__main__":
    test_sat()
    test_extrapolation()
    test_head_on_ttc()
    test_crossing_pet()
    print("\n*** TOUS LES TESTS Prédiction PASSENT ***")
