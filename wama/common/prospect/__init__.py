"""
PROSPECT — indicateurs de sécurité par prédiction de trajectoire (SSM : TTC, PET).

Brique WAMA généraliste et AUTONOME (numpy pur, zéro dépendance app), portée du code
MATLAB PROSPECT de l'utilisateur. Destinée à migrer vers `wama_data` ou à rester en
`common/` si `wama_lab` l'utilise.

Pipeline :
  1. extrapolate_speed_accel / extrapolate_kalman : prédire les positions futures.
  2. point_traj_to_shape : positions → rectangles orientés (empreintes).
  3. collision_detection : TTC (collision simultanée) + PET (collision décalée) via SAT.
"""
from .geometry import rect_intersect_sat, point_traj_to_shape
from .extrapolation import extrapolate_speed_accel, extrapolate_kalman
from .collision import collision_detection

__all__ = [
    "rect_intersect_sat",
    "point_traj_to_shape",
    "extrapolate_speed_accel",
    "extrapolate_kalman",
    "collision_detection",
]
