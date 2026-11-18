"""Machine state simulation.

``simulate(program)`` walks every line keeping track of positioning modes,
G92 offsets, units and the modal feed rate.  It returns per-line arrays that
readers, modules and the tool-path builder all share.
"""
from __future__ import annotations

from gcodeproducer.core.gcode.sim_result import SimResult
from gcodeproducer.core.gcode.gcode_constants import EPS_XYZ, MOTION_COMMANDS
import math, numpy as np
from gcodeproducer.core.gcode.program import GCodeProgram


def simulate(program: GCodeProgram) -> SimResult:
    lines = program.lines
    n = len(lines)
    X = np.empty(n); Y = np.empty(n); Z = np.empty(n); E = np.empty(n)
    F = np.full(n, np.nan)
    DE = np.zeros(n)
    MOT = np.zeros(n, dtype=bool)
    ERel = np.zeros(n, dtype=bool)
    XRel = np.zeros(n, dtype=bool)
    SC = np.ones(n)
    TL = np.full(n, -1, dtype=np.int64)
    tool = -1
    mcmd = [None] * n

    x = y = z = e = 0.0
    feed = math.nan
    xyz_rel = False
    e_rel = False
    e_rel_explicit = None
    scale = 1.0
    modal = None

    for i, ln in enumerate(lines):
        cmd = ln.cmd
        p = ln.params
        if cmd is None and p and modal is not None and ("X" in p or "Y" in p or "Z" in p):
            cmd = modal  # modal motion (common in CNC posts)
        if cmd in MOTION_COMMANDS:
            modal = cmd
            mcmd[i] = cmd
            MOT[i] = True
            if "F" in p:
                feed = p["F"] * scale
            if xyz_rel:
                if "X" in p: x += p["X"] * scale
                if "Y" in p: y += p["Y"] * scale
                if "Z" in p: z += p["Z"] * scale
            else:
                if "X" in p: x = p["X"] * scale
                if "Y" in p: y = p["Y"] * scale
                if "Z" in p: z = p["Z"] * scale
            if "E" in p:
                if e_rel:
                    DE[i] = p["E"] * scale
                    e += DE[i]
                else:
                    ne = p["E"] * scale
                    DE[i] = ne - e
                    e = ne
        elif cmd is not None:
            if cmd[0] == "T" and cmd[1:].isdigit():
                tool = int(cmd[1:])
            elif cmd in ("M6", "M06") and "T" in p:
                tool = int(p["T"])
            if cmd == "G92":
                if not p:
                    x = y = z = e = 0.0
                else:
                    if "X" in p: x = p["X"] * scale
                    if "Y" in p: y = p["Y"] * scale
                    if "Z" in p: z = p["Z"] * scale
                    if "E" in p: e = p["E"] * scale
            elif cmd == "G90":
                xyz_rel = False
                e_rel = bool(e_rel_explicit) if e_rel_explicit is not None else False
            elif cmd == "G91":
                xyz_rel = True
                e_rel = True
            elif cmd == "M82":
                e_rel = False; e_rel_explicit = False
            elif cmd == "M83":
                e_rel = True; e_rel_explicit = True
            elif cmd == "G20":
                scale = 25.4
            elif cmd == "G21":
                scale = 1.0
            elif cmd == "G28":
                if not any(k in p for k in "XYZ"):
                    x = y = z = 0.0
                else:
                    if "X" in p: x = 0.0
                    if "Y" in p: y = 0.0
                    if "Z" in p: z = 0.0
        X[i] = x; Y[i] = y; Z[i] = z; E[i] = e; F[i] = feed
        ERel[i] = e_rel; XRel[i] = xyz_rel
        SC[i] = scale; TL[i] = tool

    def prev(a, init=0.0):
        r = np.empty_like(a)
        if n:
            r[0] = init
            r[1:] = a[:-1]
        return r

    PX, PY, PZ, PE = prev(X), prev(Y), prev(Z), prev(E)
    dx = X - PX; dy = Y - PY; dz = Z - PZ
    dxy = np.hypot(dx, dy)
    dist = np.sqrt(dxy * dxy + dz * dz)
    moved = MOT & (dist > EPS_XYZ)
    # full-circle arcs start and end at the same point but still move
    for i, c in enumerate(mcmd):
        if (c == "G2" or c == "G3") and not moved[i]:
            p = lines[i].params
            if "I" in p or "J" in p or "R" in p:
                moved[i] = True
    return SimResult(X, Y, Z, E, PX, PY, PZ, PE, F, DE, MOT, moved, dist, dxy, ERel, XRel, mcmd, SC, TL)
