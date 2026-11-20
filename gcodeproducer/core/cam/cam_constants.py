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
    "pocket": {"raster": "raster_y"},
    "waterfall": {"raster": "raster_y"},
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
SURFACE_LEAD_SETTLE = 8

TROCHOID_CHORD_ERROR = .01   # mm; largest deviation from the parametric ellipse
TROCHOID_MIN_SEGMENTS = 16
TROCHOID_MINOR_RATIO_LIMITS = (.5, .9)  # minor / major; keep the paths elliptical, including in square pockets
TROCHOID_MAX_FRONTS = 10_000
TROCHOID_POINT_BUDGET = 2_000_000
TROCHOID_SEAM_TRIALS = 16

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

MAX_POINTS = 20000          # guard against absurdly many laps on a microscopic contour

RAMP_ANGLE=10.0                       # matches the lead-in planner (core.cam_leads)

RAMP_TAN=math.tan(math.radians(RAMP_ANGLE))

DIRECTIONS = ("climb", "conventional", "meander")


FACE_NAMES = ("bottom", "top", "Y minimum", "Y maximum", "X minimum", "X maximum")


def material_parameters():
    params = [Param("auto_cutting_data", "bool", False, label="Calculate from SFM / chip load",
                    group="Cutting calculation", help="Enable after calibrating the per-material data. Legacy tools retain fixed feeds/RPM."),
              Param("max_spindle_rpm", "float", 24000., min=1, unit="rpm", group="Cutting calculation",
                    help="Tool RPM ceiling, also respected for manual RPM requests."),
              Param("lead_feed_percent", "float", 35., min=1, max=100, unit="%", group="Cutting calculation",
                    help="Automatic lead/plunge feed as a percentage of calculated normal feed.")]
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
