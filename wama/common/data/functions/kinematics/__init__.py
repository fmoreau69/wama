"""kinematics/ — vitesse / accélération / TTC / collision / extrapolation."""
from .extrapolation import extrapolate_speed_accel, extrapolate_kalman  # noqa: F401
from .collision import collision_detection  # noqa: F401
