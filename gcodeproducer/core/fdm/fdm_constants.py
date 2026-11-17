"""Shared fdm constants and declarative tables."""
from __future__ import annotations

SUPPORT_MODES = ("none", "buildplate", "everywhere", "blocks")

FILL_FEATURES = frozenset(("infill", "solid_infill", "top_infill"))
WALL_FEATURES = frozenset(("outer_perimeter", "inner_perimeter", "middle_perimeter"))
FILL_LOOKAHEAD = 32                      # candidates per feature, even on dense layers
TRAVEL_VERTEX_LIMIT = 96                 # bound the per-travel visibility search
TRAVEL_WAYPOINT_INSET = .01              # mm inside the layer outline before G-code rounding
