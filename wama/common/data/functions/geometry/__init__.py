"""geometry/ — placement monde, projections, formes spatiales, métriques de placement."""
from .shapes import rect_intersect_sat, point_traj_to_shape  # noqa: F401
from . import placement_metrics  # noqa: F401  (auto-enregistre la FunctionSpec)
from .placement_metrics import track_position_spread, placement_spread  # noqa: F401
