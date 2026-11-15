"""Canonical feature types plus shared annotation helpers used by readers."""
from __future__ import annotations

import colorsys
import hashlib
import math
from collections import Counter

import numpy as np

from .gcode import GCodeProgram
from .sim import SimResult, simulate
from .workflow import FDM

# id, label, colour (rgb 0..1)
FEATURE_TABLE = [
    ("outer_perimeter",   "Outer perimeter",      (1.00, 0.50, 0.10)),
    ("middle_perimeter",  "Middle perimeter",     (1.00, 0.72, 0.25)),
    ("inner_perimeter",   "Inner perimeter",      (1.00, 0.88, 0.35)),
    ("overhang_perimeter", "Overhang perimeter",  (0.15, 0.30, 1.00)),
    ("infill",            "Infill (sparse)",      (0.78, 0.22, 0.22)),
    ("dense_infill",      "Dense infill",         (0.85, 0.40, 0.40)),
    ("solid_infill",      "Solid infill",         (0.60, 0.25, 0.85)),
    ("top_infill",        "Top solid infill",     (0.95, 0.30, 0.50)),
    ("bridge",            "Bridge",               (0.30, 0.60, 1.00)),
    ("gap_fill",          "Gap fill",             (0.95, 0.95, 0.95)),
    ("skirt",             "Skirt / brim",         (0.00, 0.80, 0.60)),
    ("support",           "Support",              (0.45, 0.85, 0.25)),
    ("support_interface", "Support interface",    (0.20, 0.60, 0.30)),
    ("raft",              "Raft",                 (0.50, 0.50, 0.80)),
    ("prime_tower",       "Prime tower / wipe",   (0.70, 0.70, 0.30)),
    ("shield",            "Ooze shield",          (0.55, 0.55, 0.45)),
    ("ironing",           "Ironing",              (0.90, 0.60, 0.90)),
    ("custom",            "Custom / start-end",   (0.50, 0.50, 0.50)),
    # ---- CAM (machining)
    ("rapid",             "Rapid",                (1.00, 0.30, 0.30)),
    ("plunge",            "Plunge",               (0.95, 0.25, 0.95)),
    ("retract",           "Retract (feed up)",    (0.60, 0.60, 1.00)),
    ("lead_in",           "Lead-in (ramp / helix / arc)", (0.15, 0.90, 0.95)),
    ("lead_out",          "Lead-out",             (0.20, 0.55, 1.00)),
    ("slot",              "Slot",    (1.00, 0.55, 0.00)),
    ("high_engagement",   "High engagement",     (1.00, 0.20, 0.10)),
    ("cut",               "Cut",                  (0.30, 0.85, 0.35)),
    ("hsm",               "HSM",                  (0.20, 0.65, 1.00)),
    ("air",               "Air cut",              (0.55, 0.55, 0.55)),
    ("conflict",          "Conflict (wrong hand / uncertain)", (1.00, 0.95, 0.10)),
    ("collision",         "Collision (material contact)", (1.00, 0.00, 1.00)),
    ("unknown",           "Unknown",              (0.65, 0.65, 0.65)),
]

FEATURE_IDS = [f[0] for f in FEATURE_TABLE]
FEATURE_LABELS = {f[0]: f[1] for f in FEATURE_TABLE}
_FEATURE_COLORS = {f[0]: f[2] for f in FEATURE_TABLE}

CAM_FEATURES = ["rapid", "plunge", "retract", "lead_in", "lead_out", "slot", "high_engagement", "cut", "hsm", "air",
                "conflict", "collision"]
# Feature ids that an operation's own cut moves may legitimately carry (incl. flagged ones).
CAM_CUT_FEATURES = {"cut", "slot", "high_engagement", "hsm", "air", "conflict"}
FEATURE_TOOLTIPS = {"hsm": "HSM: low horizontal (radial) engagement, below the machine HSM threshold",
                    "conflict": "Cut segments the planner could not keep on the requested climb/conventional hand",
                    "collision": "Moves the stock checks flagged: rapid/spindle-off/unexpected contact, below-bottom or deep entry"}
# Features a 3D printer speed modifier can act on (excludes custom/unknown and CAM features).
PRINT_FEATURES = [f for f in FEATURE_IDS if f not in ("custom", "unknown") and f not in CAM_FEATURES]
FDM_FEATURES = PRINT_FEATURES


def feature_label(fid: str) -> str:
    return FEATURE_LABELS.get(fid, fid)


def feature_color(fid: str) -> tuple:
    c = _FEATURE_COLORS.get(fid)
    if c is not None:
        return c
    # stable colour for dynamic names (e.g. CAM operation names)
    h = int(hashlib.md5(fid.encode("utf-8")).hexdigest()[:8], 16)
    hue = (h % 360) / 360.0
    return colorsys.hsv_to_rgb(hue, 0.65, 0.95)


# --------------------------------------------------------------------------
# generic annotation helpers
# --------------------------------------------------------------------------
def assign_layers_by_z(program: GCodeProgram, sim: SimResult | None = None, tol: float = 0.005) -> None:
    """Fallback layer detection for FDM files without layer comments.

    A new layer starts at the first Z change after the last extrusion when
    the next extrusion happens at a different height.
    """
    sim = sim or simulate(program)
    ext = sim.extruding
    layer = 0
    layer_z = None
    zs: list = []
    first_z_change = None
    last_ext = -1
    pending_start = 0
    starts = []
    for i in range(len(program.lines)):
        if sim.motion[i] and abs(sim.z[i] - sim.pz[i]) > 1e-9 and first_z_change is None and i > last_ext:
            first_z_change = i
        if ext[i]:
            z = sim.z[i]
            if layer_z is None:
                layer_z = z
                zs.append(z)
                starts.append(0)
            elif abs(z - layer_z) > tol:
                start = first_z_change if first_z_change is not None and first_z_change > last_ext else i
                starts.append(start)
                layer_z = z
                zs.append(z)
            last_ext = i
            first_z_change = None
    if not starts:
        for ln in program.lines:
            ln.layer = 0
        program.layer_z = [0.0]
        return
    bounds = starts[1:] + [len(program.lines)]
    li = 0
    for idx, ln in enumerate(program.lines):
        while li < len(bounds) and idx >= bounds[li]:
            li += 1
        ln.layer = min(li, len(starts) - 1)
    program.layer_z = [float(z) for z in zs]


def assign_layers_by_depth(program: GCodeProgram, sim: SimResult | None = None, resolution: float = 0.05) -> None:
    """CAM layering: every distinct cutting depth becomes a layer (top first)."""
    sim = sim or simulate(program)
    cutting = sim.moved & np.array([c in ("G1", "G2", "G3") for c in sim.motion_cmd])
    if not cutting.any():
        for ln in program.lines:
            ln.layer = 0
        program.layer_z = [0.0]
        return
    # depth levels = heights of planar cuts; ramps/helices join the level they descend to
    planar = cutting & (np.abs(sim.z - sim.pz) < 1e-6)
    src = sim.z[planar] if planar.any() else sim.z[cutting]
    q = np.unique(np.round(src / resolution).astype(np.int64))
    levels = np.sort(q * resolution)[::-1]          # top first
    asc = levels[::-1]
    cur = 0
    nlev = len(levels)
    for i, ln in enumerate(program.lines):
        if cutting[i]:
            z = sim.z[i] + resolution * 0.5
            k = int(np.searchsorted(asc, z, side="right")) - 1   # highest level <= z
            k = max(k, 0)
            cur = nlev - 1 - k
        ln.layer = cur
    program.layer_z = [float(v) for v in levels]


def compute_layer_z(program: GCodeProgram, sim: SimResult | None = None) -> None:
    """Fill ``program.layer_z`` from the first extrusion of each layer."""
    sim = sim or simulate(program)
    n = program.num_layers
    zs = [math.nan] * n
    ext = sim.extruding if program.machine == FDM else sim.moved
    for i, ln in enumerate(program.lines):
        if ext[i] and math.isnan(zs[ln.layer]):
            zs[ln.layer] = float(sim.z[i])
    last = 0.0
    for k in range(n):
        if math.isnan(zs[k]):
            zs[k] = last
        last = zs[k]
    program.layer_z = zs


def _point_segment_distance(points: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """min distance from each point (k,2) to the set of segments a->b (m,2)."""
    ab = b - a
    denom = np.einsum("ij,ij->i", ab, ab)
    denom[denom == 0] = 1e-12
    ap = points[:, None, :] - a[None, :, :]
    t = np.clip(np.einsum("kmj,mj->km", ap, ab) / denom[None, :], 0.0, 1.0)
    proj = a[None, :, :] + t[..., None] * ab[None, :, :]
    d = np.linalg.norm(points[:, None, :] - proj, axis=2)
    return d.min(axis=1)


def classify_perimeters(program: GCodeProgram, sim: SimResult | None = None,
                        n_perimeters: int | None = None, width: float | None = None) -> int:
    """Split ``inner_perimeter`` loops into ``middle_perimeter`` / ``inner_perimeter``.

    Each inner loop's distance to the outer perimeter of the same layer gives
    its shell index.  Loops in the innermost shell keep ``inner_perimeter``,
    others become ``middle_perimeter``.  Returns the number of lines relabelled.
    """
    if n_perimeters is not None and n_perimeters <= 2:
        return 0
    lines = program.lines
    if not any(ln.feature == "inner_perimeter" for ln in lines):
        return 0
    sim = sim or simulate(program)
    ext = sim.extruding
    travel = sim.motion & sim.moved & ~ext

    # collect loops and outer segments per layer
    loops: dict = {}
    outers: dict = {}
    run: list = []
    run_layer = None

    def flush():
        nonlocal run
        if run:
            loops.setdefault(run_layer, []).append(run)
        run = []

    for i, ln in enumerate(lines):
        if ext[i]:
            if ln.feature == "inner_perimeter":
                if run and ln.layer != run_layer:
                    flush()
                run_layer = ln.layer
                run.append(i)
            else:
                flush()
                if ln.feature == "outer_perimeter":
                    outers.setdefault(ln.layer, []).append(i)
        elif travel[i] or (ln.feature != "inner_perimeter" and ln.cmd is not None):
            flush()
    flush()

    changed = 0
    for layer, lps in loops.items():
        oidx = outers.get(layer)
        if not oidx:
            continue
        oidx = np.array(oidx)
        a = np.stack([sim.px[oidx], sim.py[oidx]], axis=1)
        b = np.stack([sim.x[oidx], sim.y[oidx]], axis=1)
        dists = []
        for lp in lps:
            idx = np.array(lp)
            if len(idx) > 12:
                idx = idx[np.linspace(0, len(idx) - 1, 12).astype(int)]
            pts = np.stack([sim.x[idx], sim.y[idx]], axis=1)
            dists.append(float(np.median(_point_segment_distance(pts, a, b))))
        spacing = width or (min(dists) if dists else 0.0)
        if spacing <= 0:
            continue
        shells = [max(1, int(round(d / spacing))) for d in dists]
        n = n_perimeters if n_perimeters else max(shells) + 1
        for lp, s in zip(lps, shells):
            if s < n - 1:
                for i in lp:
                    lines[i].feature = "middle_perimeter"
                changed += len(lp)
    return changed


def mode_value(values, decimals: int = 3):
    """Most common value after rounding (None if empty)."""
    if len(values) == 0:
        return None
    c = Counter(round(float(v), decimals) for v in values)
    return c.most_common(1)[0][0]
