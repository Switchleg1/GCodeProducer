"""Tool path geometry built from a program (used by the viewer and statistics)."""
from __future__ import annotations

from gcodeproducer.core.gcode.gcode_constants import SOLID_KINDS, EPS_E
import math, numpy as np
from dataclasses import dataclass, field
from gcodeproducer.core.gcode.program import GCodeProgram
from gcodeproducer.core.gcode.sim_result import SimResult
from gcodeproducer.core.gcode.simulation import simulate
from gcodeproducer.core.workflows.workflows_constants import FDM
from .gcode_constants import EXTRUDE, TRAVEL, CUT, RAPID, RETRACT, UNRETRACT
# point events


@dataclass
class Toolpath:
    p0: np.ndarray            # (N,3) float32 segment start
    p1: np.ndarray            # (N,3) float32 segment end
    line: np.ndarray          # (N,) int32 program line index
    layer: np.ndarray         # (N,) int32
    feature: np.ndarray       # (N,) int16 index into feature_names
    kind: np.ndarray          # (N,) int8
    feed: np.ndarray          # (N,) float32 mm/min
    feature_names: list
    ev_pos: np.ndarray        # (M,3) retract / unretract positions
    ev_line: np.ndarray       # (M,)
    ev_layer: np.ndarray
    ev_kind: np.ndarray
    line_pos: np.ndarray      # (L,3) tool position after each line
    line_layer: np.ndarray    # (L,)
    line_changed: np.ndarray  # (L,) bool
    machine: str = FDM
    op: np.ndarray = None           # (N,) int16 index into op_names
    op_names: list = field(default_factory=list)
    engagement: np.ndarray = None   # (N,) float32 CAM radial engagement (nan = n/a)
    stats: dict = field(default_factory=dict)
    distance_ends: np.ndarray = None  # cumulative XYZ distance at each segment end (mm)

    @property
    def num_layers(self) -> int:
        return int(self.line_layer.max()) + 1 if len(self.line_layer) else 0

    def bounds(self, solid_only: bool = True):
        if len(self.p0) == 0:
            return np.zeros(3), np.ones(3)
        mask = np.isin(self.kind, SOLID_KINDS) if solid_only else np.ones(len(self.kind), bool)
        if not mask.any():
            mask = np.ones(len(self.kind), bool)
        pts = np.concatenate([self.p0[mask], self.p1[mask]])
        return pts.min(axis=0), pts.max(axis=0)

    def layer_line_range(self, layer: int):
        idx = np.nonzero(self.line_layer == layer)[0]
        if len(idx) == 0:
            return 0, 0
        return int(idx[0]), int(idx[-1])


def _arc_points(x0, y0, x1, y1, line, cw: bool, max_seg: float = 0.5):
    p = line.params
    if "R" in p and "I" not in p and "J" not in p:
        r = p["R"]
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d == 0 or abs(r) < d / 2:
            return [(x1, y1)]
        h = math.sqrt(max(r * r - d * d / 4, 0.0))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        # choose centre side: for CW with positive R centre lies to the right
        sgn = -1 if (cw ^ (r < 0)) else 1
        cx = mx - sgn * h * dy / d
        cy = my + sgn * h * dx / d
    else:
        cx = x0 + p.get("I", 0.0)
        cy = y0 + p.get("J", 0.0)
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw:
        if sweep >= -1e-9:
            sweep -= 2 * math.pi
    else:
        if sweep <= 1e-9:
            sweep += 2 * math.pi
    length = abs(sweep) * r
    n = max(2, min(360, int(math.ceil(max(length / max_seg, abs(sweep) / math.radians(10))))))
    pts = []
    for k in range(1, n + 1):
        t = k / n
        a = a0 + sweep * t
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a), t))
    pts[-1] = (x1, y1, 1.0)
    return pts


def build_toolpath(program: GCodeProgram, sim: SimResult | None = None) -> Toolpath:
    sim = sim or simulate(program)
    lines = program.lines
    fff = program.machine == FDM
    fnames: dict = {}
    seg = []        # tuples: x0,y0,z0,x1,y1,z1,line,layer,feat,kind,feed
    ev = []         # x,y,z,line,layer,kind
    X, Y, Z = sim.x, sim.y, sim.z
    PX, PY, PZ = sim.px, sim.py, sim.pz
    DE, F, MOVED, MOT = sim.de, sim.feed, sim.moved, sim.motion

    for i, ln in enumerate(lines):
        if not MOT[i]:
            if ln.cmd == "G10":
                ev.append((X[i], Y[i], Z[i], i, ln.layer, RETRACT))
            elif ln.cmd == "G11":
                ev.append((X[i], Y[i], Z[i], i, ln.layer, UNRETRACT))
            continue
        de = DE[i]
        if not MOVED[i]:
            if de < -EPS_E:
                ev.append((X[i], Y[i], Z[i], i, ln.layer, RETRACT))
            elif de > EPS_E:
                ev.append((X[i], Y[i], Z[i], i, ln.layer, UNRETRACT))
            continue
        cmd = sim.motion_cmd[i]
        if fff:
            kind = EXTRUDE if de > EPS_E else TRAVEL
            if de < -EPS_E:
                ev.append((PX[i], PY[i], PZ[i], i, ln.layer, RETRACT))
        else:
            kind = RAPID if cmd == "G0" else CUT
        fid = fnames.setdefault(ln.feature, len(fnames))
        feed = F[i] if F[i] == F[i] else 0.0
        if cmd in ("G2", "G3"):
            x0, y0, z0 = PX[i], PY[i], PZ[i]
            px, py, pz = x0, y0, z0
            for ax, ay, t in _arc_points(x0, y0, X[i], Y[i], ln, cmd == "G2"):
                az = z0 + (Z[i] - z0) * t
                seg.append((px, py, pz, ax, ay, az, i, ln.layer, fid, kind, feed))
                px, py, pz = ax, ay, az
        else:
            seg.append((PX[i], PY[i], PZ[i], X[i], Y[i], Z[i], i, ln.layer, fid, kind, feed))

    seg_line = np.array([s_[6] for s_ in seg], dtype=np.int64) if seg else np.zeros(0, np.int64)
    if seg:
        a = np.array(seg, dtype=np.float64)
    else:
        a = np.zeros((0, 11))
    e = np.array(ev, dtype=np.float64) if ev else np.zeros((0, 6))
    n_lines = len(lines)
    tp = Toolpath(
        p0=a[:, 0:3].astype(np.float32),
        p1=a[:, 3:6].astype(np.float32),
        line=a[:, 6].astype(np.int32),
        layer=a[:, 7].astype(np.int32),
        feature=a[:, 8].astype(np.int16),
        kind=a[:, 9].astype(np.int8),
        feed=a[:, 10].astype(np.float32),
        feature_names=list(fnames),
        ev_pos=e[:, 0:3].astype(np.float32),
        ev_line=e[:, 3].astype(np.int32),
        ev_layer=e[:, 4].astype(np.int32),
        ev_kind=e[:, 5].astype(np.int8),
        line_pos=np.stack([X, Y, Z], axis=1).astype(np.float32) if n_lines else np.zeros((0, 3), np.float32),
        line_layer=np.array([ln.layer for ln in lines], dtype=np.int32),
        line_changed=np.array([ln.is_changed for ln in lines], dtype=bool),
        machine=program.machine,
    )
    ops: dict = {}
    op_line = np.array([ops.setdefault(ln.op or "", len(ops)) for ln in lines], dtype=np.int16)
    tp.op_names = list(ops)
    tp.op = op_line[seg_line] if len(seg_line) else np.zeros(0, np.int16)
    eng_line = np.array([ln.engagement for ln in lines], dtype=np.float32)
    tp.engagement = eng_line[seg_line] if len(seg_line) else np.zeros(0, np.float32)
    lengths = np.linalg.norm(tp.p1 - tp.p0, axis=1)
    tp.distance_ends = np.cumsum(lengths, dtype=np.float64)
    tp.stats = compute_stats(tp, program, lengths)
    return tp


def compute_stats(tp: Toolpath, program: GCodeProgram, length=None) -> dict:
    if length is None:
        length = np.linalg.norm(tp.p1 - tp.p0, axis=1)
    solid = np.isin(tp.kind, SOLID_KINDS)
    feed = np.where(tp.feed > 0, tp.feed, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.nansum(length / feed) * 60.0
    lo, hi = tp.bounds()
    return {
        "lines": len(program.lines),
        "layers": program.num_layers,
        "segments": int(len(tp.p0)),
        "print_length_mm": float(length[solid].sum()),
        "travel_length_mm": float(length[~solid].sum()),
        "retractions": int((tp.ev_kind == RETRACT).sum()),
        "est_time_s": float(t),
        "changed_lines": int(tp.line_changed.sum()),
        "bounds_min": [round(float(v), 3) for v in lo],
        "bounds_max": [round(float(v), 3) for v in hi],
    }


def format_duration(seconds: float) -> str:
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"
