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
TRAVEL_VISIBILITY_CHUNK = 16            # successors tested together by the lazy travel search
TRAVEL_WAYPOINT_INSET = .01              # mm inside the layer outline before G-code rounding

# Variable-width walls / gap fill (multiples of the line width unless noted)
VARIABLE_SAMPLE_STEP = .125              # boundary sample spacing for the medial axis
VARIABLE_DENSIFY = .25                   # loop vertex spacing where widths may vary
VARIABLE_PRUNE = .5                      # drop medial-axis spurs shorter than this
VARIABLE_MIN_LENGTH = .75                # shortest open thin-wall bead
VARIABLE_MIN_AREA = .05                  # ignore narrow slivers smaller than this * width²
GAP_FILL_MAX_LOOPS = 20                  # concentric gap-fill loops per piece
VARIABLE_RAY_START = 1e-3               # mm off the edge before measuring the material across
GAP_FILL_MIN_AREA = .25                  # ignore gap pieces smaller than this * width²
GAP_CLIPPED_FEATURES = frozenset(("solid_infill", "top_infill"))  # solid lines trimmed by gap fill
VARIABLE_THIN_MIN_AREA = .1             # thin tips smaller than this * width² (e.g. 90° corner crumbs) stay empty
VARIABLE_MITRE_LIMIT = 2.                # keeps loop corners sharp without regrowing narrow tips
LAYER_THREADS = 8                        # per-layer wall / gap-fill geometry threads
GAP_FILL_MITRE_LIMIT = 2.                # corners sharper than ~60° still count as gaps
VARIABLE_LOOP_MIN_AREA = 1.              # narrow-feature loop scraps smaller than this * width² become centre bead
VARIABLE_THIN_REACH = .25                # centre beads may run this far (* width) under the loop ends they join
VARIABLE_PRUNE_RADII = 1.6               # also drop spurs shorter than this many junction radii
