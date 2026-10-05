"""kinematics/ — vitesse / accélération / TTC / collision / extrapolation / lissage / trous."""
from .gap_fill import hermite_gap  # noqa: F401
from .extrapolation import extrapolate_speed_accel, extrapolate_kalman  # noqa: F401
from .collision import collision_detection  # noqa: F401
from .rts_smoother import kalman_rts_cv  # noqa: F401
