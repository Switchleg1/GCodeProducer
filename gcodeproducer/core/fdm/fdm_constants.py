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
VARIABLE_SAMPLE_STEP = .2                # boundary sample spacing for the medial axis
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
LAYER_ORDER_FILL_FEATURES = FILL_FEATURES | {"gap_fill", "bridge"}   # printed per island after its walls
LAYER_ORDER_LOOP_SAMPLES = 48            # entry candidates per closed loop for nearest-first ordering
FILL_RUN_ANGLE_DECIMALS = 1             # fill lines within this angle rounding share a scan family
FILL_RUN_GAP_FACTOR = 1.5                # scan lines farther apart than this * spacing don't join runs
FILL_RUN_OVERLAP = 1.                    # neighbouring segments join if they overlap or are this * spacing apart
FILL_RUN_MAX_SPACING = 1.5               # mm: families with wider line spacing (sparse) don't form runs
LAYER_ORDER_RELOCATE_PASSES = 2          # passes moving straggler fill paths to their cheapest place
LAYER_ORDER_RELOCATE_MIN = .5            # mm saved before a straggler is moved
VARIABLE_SCRAP_LOOP = 4.                 # wall loops shorter than this * width print as one straight bead
VARIABLE_SCRAP_MIN_SPAN = .05            # mm: shortest bead made from a loop scrap
LAYER_PROCESSES = 16                     # most worker processes for per-layer work
LAYER_PROCESS_MIN = 4                    # fewer layers than this run on threads (pool start-up is not free)
LAYER_WORKERS_ENV = "GCODEPRODUCER_WORKERS"   # environment override of the worker count (0 / 1 = threads)
EMIT_REPLAN_DISTANCE = 1.                # mm: re-plan a layer whose plan starts this far from the last end
EMIT_REPLAN_PASSES = 2                   # re-planning passes before the first travels are routed as planned
