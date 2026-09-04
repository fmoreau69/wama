"""geometry/ — placement monde, projections, formes spatiales, métriques de placement."""
from .shapes import rect_intersect_sat, point_traj_to_shape  # noqa: F401
from . import placement_metrics  # noqa: F401  (auto-enregistre la FunctionSpec)
from .placement_metrics import track_position_spread, placement_spread  # noqa: F401
from . import depth_geometry  # noqa: F401  (auto-enregistre les FunctionSpec profondeur)
from .depth_geometry import (deproject_depth, fit_plane_ransac, plane_pitch_height,  # noqa: F401
                             ground_plane_from_depth, contact_depth)
from . import ego_rotation  # noqa: F401  (auto-enregistre la FunctionSpec)
from .ego_rotation import estimate_ego_rotation, yaw_disagreement  # noqa: F401
