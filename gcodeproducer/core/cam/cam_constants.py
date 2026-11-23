"""Shared cam constants and declarative tables."""
from __future__ import annotations
from gcodeproducer.core.geometry.geometry_constants import (
    BINARY_BOX_EDGES as EDGES,
    BINARY_BOX_FACES as FACES,
)
from gcodeproducer.core.parameters.param import Param
import math

KINDS = ("pocket", "profile", "drill", "engrave", "slot", "waterfall", "contour3d")

KIND_LABELS = {"pocket": "Pocket", "profile": "Profile", "drill": "Drill", "engrave": "Engrave", "slot": "Slot",
               "waterfall": "3D Waterfall", "contour3d": "3D Contour"}

SURFACE_KINDS = ("waterfall", "contour3d")   # always limited by the model surface (3-axis, no undercuts)

STRATEGY_ALIASES = {
    "pocket": {"raster": "raster_y", "trochoidal": "adaptive"},
    "waterfall": {"raster": "raster_y", "trochoidal": "adaptive"},
    "contour3d": {"contour": "meander", "raster": "meander"},
}

SURFACE_TOLERANCE = 1e-3       # mm: model material this far above a level blocks the cutter at that level
SHADOW_SEAL = 1e-5             # mm: closes hairline gaps between projected triangles
SURFACE_MIN_RESOLUTION = .05   # mm: finest drop-cutter height grid
SURFACE_CELLS_PER_DIAMETER = 40
SURFACE_REUSE_MIN_POINTS = 16  # cache simplification only for longer spans
SURFACE_SIMPLIFY = .005        # mm: 3D polyline simplification tolerance
SURFACE_MAX_POINTS = 2_000_000
SURFACE_ENGAGEMENT_STATIONS = (.25, .75, 1.)
SURFACE_ENGAGEMENT_FORWARD = (0., .25, .5, .75)
SURFACE_CHORD_SAMPLES_MIN = 16
SURFACE_CHORD_SAMPLES_MAX = 64
SURFACE_MOVE_STEP_RADIUS = .5

ADAPTIVE_ENGAGEMENT_BATCH_DIAMETERS = 4.

ADAPTIVE_PEEL_ADVANCE_FACTORS = (1., .75, .5, .25, .125)
ADAPTIVE_PEEL_CHORD_ERROR = .01
ADAPTIVE_PEEL_MIN_SEGMENTS = 24
ADAPTIVE_PEEL_MAX_SEGMENTS = 4096
ADAPTIVE_PEEL_SAMPLE_STEP_RADII = .2
ADAPTIVE_PEEL_HEADINGS = (0., -35., 35.)  # degrees relative to the desired direction
ADAPTIVE_PEEL_RADIUS_FACTORS = (1., .8, 1.2)
ADAPTIVE_LINK_WAYPOINT_LIMIT = 24
ADAPTIVE_LINK_HISTORY_STEPS = 6
ADAPTIVE_LINK_HISTORY_SAMPLES = 8
ADAPTIVE_LINK_BUFFER_QUADS = 16
ADAPTIVE_BRANCH_LIMIT = 16
ADAPTIVE_FRONTIER_SAMPLES = 12
ADAPTIVE_ENTRY_RADIUS_FACTOR = .9  # less than cutter radius: the flat lap must cover the core
ADAPTIVE_ENTRY_LIMIT = 20_000
ADAPTIVE_CAM_POINT_LIMIT = 20_000  # resource guard; exceeding it never authorizes a cut
ADAPTIVE_CAM_COMPONENTS = 4
ADAPTIVE_CAM_LIMIT = .18  # default sampled width limit for peels and finish moves
ADAPTIVE_BLEND_RADIUS_FACTORS = (1., .5, .25)
ADAPTIVE_BLEND_TURN_THRESHOLD = math.radians(15.)
ADAPTIVE_BLEND_MAX_CHORD_ANGLE = math.radians(10.)
ADAPTIVE_POCKET_AREA_EPS = 1e-8  # mm²; numerical residue, not a machining tolerance

REFERENCE_CHORD_ERROR = .01  # mm; circles are polygonal, not fitted G2/G3 arcs
REFERENCE_MIN_SEGMENTS = 64
REFERENCE_MAX_SEGMENTS = 8192

MATERIALS = (
    ("soft_wood", "Soft wood", 600., .05),
    ("hard_wood", "Hard wood", 400., .04),
    ("soft_plastic", "Soft plastic", 300., .03),
    ("hard_plastic", "Hard plastic", 200., .02),
    ("non_iron_metal", "Non-iron metal", 300., .03),
    ("steel", "Steel", 80., .015),
)

MATERIAL_KEYS = {m[0] for m in MATERIALS}

FEED_FIELDS = {
    "hsm": ("low_engagement_feed", 100.0),
    "cut": ("standard_engagement_feed", 100.0),
    "high": ("high_engagement_feed", 75.0),
    "slot": ("slotting_feed", 50.0),
}
# Plunge (moves down into material) as a % of the tool feed: machine default, operation override.
PLUNGE_FEED_FIELD = ("plunge_feed_modifier", 30.0)

MAX_POINTS = 20000          # guard against absurdly many laps on a microscopic contour

RAMP_ANGLE = 10.0                     # default for legacy setups
LEAD_ANGLE_RANGE = (.1, 89.)

RAMP_TAN=math.tan(math.radians(RAMP_ANGLE))

DIRECTIONS = ("climb", "conventional", "meander")


FACE_NAMES = ("bottom", "top", "Y minimum", "Y maximum", "X minimum", "X maximum")


def material_parameters():
    params = [Param("auto_cutting_data", "bool", False, label="Calculate from SFM / chip load",
                    group="Cutting calculation", help="Enable after calibrating the per-material data. Legacy tools retain fixed feeds/RPM."),
              Param("max_spindle_rpm", "float", 24000., min=1, unit="rpm", group="Cutting calculation",
                    help="Tool RPM ceiling, also respected for manual RPM requests."),
              Param("lead_feed_percent", "float", 35., min=1, max=100, unit="%", group="Cutting calculation",
                    label="Lead-in feed", help="Automatic lead-in/ramp feed as a percentage of calculated normal feed. "
                    "The plunge feed is the machine's Plunge feed modifier.")]
    for key, label, sfm, chip in MATERIALS:
        group = f"Cut data: {label}"
        params += [Param(f"{key}_sfm", "float", sfm, min=.1, unit="ft/min", group=group, label="SFM"),
                   Param(f"{key}_chip_load", "float", chip, min=.0001, unit="mm/tooth", decimals=4,
                         group=group, label="Chip load")]
        for process, percent in (("slot",15.),("pocket",25.),("profile",40.)):
            params.append(Param(f"{key}_{process}_axial", "float", percent, min=1, max=200,
                                unit="% D", group=group, label=f"{process.title()} axial depth",
                                help=f"Automatic {process} stepdown for {label} only (choose the machining category in Material / stock). "
                                     "Percentage of tool diameter, capped by Max depth/pass; the operation depth override takes precedence."))
    return params
# Surface-following paths (3D Contour, Waterfall following the surface): dips narrower
# than SURFACE_DIP_FILL are filled, by at most SURFACE_DIP_DEPTH (raise only), so
# height-grid noise does not saw the cutter up and down while real corners are kept.
SURFACE_DIP_FILL = .5    # mm
SURFACE_DIP_DEPTH = .05  # mm
# Interpolated surface heights are used where the four nearest cells differ by at
# most this many cell sizes (slopes up to about 50 degrees); across a steeper step
# (a wall) the cell's own height is kept, so the path does not climb the wall early.
SURFACE_FOLLOW_SPREAD = 4.
# Lead-in / lead-out: on every entry or exit, only the first entry / last exit of each
# layer (depth), or never.
LEAD_MODES = (("every", "Every entry"), ("layer", "Layer entry"), ("none", "None"))
LEAD_MODE_KEYS = frozenset(key for key, _ in LEAD_MODES)
