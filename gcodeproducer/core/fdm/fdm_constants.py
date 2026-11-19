"""Shared fdm constants and declarative tables."""
from __future__ import annotations

BRIDGE_ANGLES = tuple(i * 0.2617993877991494 for i in range(12))  # scan normals every 15 degrees

SHELL_OVERLAP_AREA_EPS = 1e-4            # mm²; ignore near-coincident numerical slivers

SUPPORT_MODES = ("none", "buildplate", "everywhere", "blocks")

FILL_FEATURES = frozenset(("infill", "solid_infill", "top_infill"))
WALL_FEATURES = frozenset(("outer_perimeter", "inner_perimeter", "middle_perimeter"))
FILL_LOOKAHEAD = 32                      # candidates per feature, even on dense layers
TRAVEL_VERTEX_LIMIT = 384               # common per-travel visibility search
TRAVEL_RETRY_VERTEX_LIMIT = 768         # retry only if the first set has no route
TRAVEL_VISIBILITY_CACHE_ROWS = 1024
TRAVEL_WAYPOINT_INSET = .01              # mm inside the layer outline before G-code rounding
