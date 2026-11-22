"""Print / run time with a firmware-like trapezoidal motion planner.

Each move accelerates from its entry speed to its feed and decelerates to its
exit speed at the active acceleration. Corner speeds follow the junction
deviation model (Marlin / Klipper-style): the sharper the corner the slower.
A forward and a backward pass make every speed reachable within the
acceleration limit, like a firmware look-ahead planner with unlimited buffer.

Extruder-only moves (retract / unretract) take ``|E| / feed``. ``M204``
commands in the program change the print (``P``/``S``) and travel
(``T``/``S``) acceleration from that line on.
"""
from __future__ import annotations

import math

import numpy as np

from gcodeproducer.core.gcode.gcode_constants import (EPS_E, MOTION_COMMENT, MOTION_DEFAULTS, MOTION_HEADER_LINES,
                                                      MOTION_KEYS)


def motion_settings(program) -> dict:
    """Motion settings stored on the program by the slicer or in its ``;MOTION`` header, else defaults."""
    out = dict(MOTION_DEFAULTS)
    stored = dict(getattr(program, "motion", None) or {})
    if not stored:
        for ln in program.lines[:MOTION_HEADER_LINES]:
            text = (ln.comment or "").strip()
            if text.startswith(MOTION_COMMENT + " "):
                for word in text.split()[1:]:
                    key, _, value = word.partition("=")
                    if key in MOTION_KEYS:
                        try:
                            stored[key] = float(value)
                        except ValueError:
                            pass
                break
    out.update({k: v for k, v in stored.items() if v is not None})
    return out


def motion_comment(motion) -> str:
    """The ``;MOTION`` header text for ``motion``."""
    return MOTION_COMMENT + " " + " ".join(f"{k}={float(motion[k]):g}" for k in MOTION_KEYS)


def _accelerations(program, n, motion):
    """Per-line (print, travel) acceleration following M204 commands."""
    printing = np.full(n, float(motion["print_acceleration"]))
    travel = np.full(n, float(motion["travel_acceleration"] or motion["print_acceleration"]))
    changes = [(i, ln.params) for i, ln in enumerate(program.lines) if ln.cmd == "M204"]
    for i, p in changes:
        if "S" in p:
            printing[i:] = travel[i:] = float(p["S"])
        if "P" in p:
            printing[i:] = float(p["P"])
        if "T" in p:
            travel[i:] = float(p["T"])
    return np.maximum(printing, 1.), np.maximum(travel, 1.)


def estimate_times(program, sim, motion=None) -> np.ndarray:
    """Seconds spent on each program line (0 for non-motion lines)."""
    motion = motion or motion_settings(program)
    n = len(program.lines)
    times = np.zeros(n)
    if not n:
        return times
    feed = np.where(np.isfinite(sim.feed) & (sim.feed > 0), sim.feed, MOTION_DEFAULTS["feed"]) / 60.0
    printing, travel = _accelerations(program, n, motion)
    # extruder-only moves
    e_only = sim.motion & ~sim.moved & (np.abs(sim.de) > EPS_E)
    times[e_only] = np.abs(sim.de[e_only]) / feed[e_only]

    idx = np.flatnonzero(sim.moved)
    if not len(idx):
        return times
    length = sim.dist[idx]
    d = np.stack((sim.x[idx] - sim.px[idx], sim.y[idx] - sim.py[idx], sim.z[idx] - sim.pz[idx]), axis=1)
    unit = d / np.maximum(length, 1e-12)[:, None]
    extruding = sim.de[idx] > EPS_E
    accel = np.where(extruding, printing[idx], travel[idx])
    vmax = feed[idx]

    # junction speed between consecutive moves; anything in between (a retract,
    # a dwell) stops the head
    m = len(idx)
    junction = np.zeros(m + 1)
    if m > 1:
        cos_theta = -(unit[1:] * unit[:-1]).sum(axis=1)
        sin_half = np.sqrt(np.clip(.5 * (1. - cos_theta), 0., 1.))
        a = np.minimum(accel[1:], accel[:-1])
        jd = float(motion["junction_deviation"])
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.sqrt(a * jd * sin_half / np.maximum(1. - sin_half, 1e-9))
        v = np.where(sin_half >= 1. - 1e-9, np.inf, v)          # straight on
        v = np.minimum(v, np.minimum(vmax[1:], vmax[:-1]))
        contiguous = idx[1:] == idx[:-1] + 1
        between = ~contiguous
        if between.any():
            # non-motion lines (comments, fan, M204) don't stop the planner;
            # extruder-only moves do
            for k in np.flatnonzero(between):
                if e_only[idx[k] + 1:idx[k + 1]].any():
                    v[k] = 0.
        junction[1:m] = v

    two_a_l = 2. * accel * length
    speeds = junction.tolist()
    reach = two_a_l.tolist()
    for i in range(m):                     # forward: entry speed limits exit speed
        limit = math.sqrt(speeds[i] * speeds[i] + reach[i])
        if speeds[i + 1] > limit:
            speeds[i + 1] = limit
    for i in range(m - 1, -1, -1):         # backward: must be able to stop in time
        limit = math.sqrt(speeds[i + 1] * speeds[i + 1] + reach[i])
        if speeds[i] > limit:
            speeds[i] = limit
    v0 = np.asarray(speeds[:-1])
    v1 = np.asarray(speeds[1:])
    vm = vmax
    accel_d = (vm * vm - v0 * v0) / (2. * accel)
    decel_d = (vm * vm - v1 * v1) / (2. * accel)
    cruise = accel_d + decel_d <= length
    peak = np.sqrt(np.maximum((two_a_l + v0 * v0 + v1 * v1) / 2., 0.))
    peak = np.where(cruise, vm, np.minimum(peak, vm))
    t = (peak - v0) / accel + (peak - v1) / accel
    t = t + np.where(cruise, (length - accel_d - decel_d) / vm, 0.)
    times[idx] = np.maximum(t, length / vm)
    return times


def estimate_time(program, sim, motion=None) -> float:
    return float(estimate_times(program, sim, motion).sum())
