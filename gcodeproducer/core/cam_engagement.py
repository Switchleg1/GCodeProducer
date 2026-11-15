"""2D in-operation removal/engagement estimate, not a 3D machining simulation.

Choose clearing hand from the material remaining on each side, not from the
final wall or a first full-width slot. Tool sweeps are subtracted after each
path/link. The caller supplies depth-aware removal history from earlier
operations; identical planar states may reuse plans. Flute shape, tooth-level
axial engagement, holders and fixtures are not modelled.
"""
from __future__ import annotations

from collections import Counter
import math

import numpy as np
from shapely import intersection, length, linestrings
from shapely.geometry import LineString, box

from .cam_paths import direction_for
from .job import CutCondition

FEED_FIELDS = {
    "hsm": ("low_engagement_feed", 100.0),
    "cut": ("standard_engagement_feed", 100.0),
    "high": ("high_engagement_feed", 75.0),
    "slot": ("slotting_feed", 50.0),
}


def engagement_band(value, machine=None):
    """Machine-set radial bands; no automatic chip-thinning speed increase."""
    if value <= 1e-6:
        return "air"
    percent = round(float(np.clip(value, 0, 1))*100,6)
    low = float(machine.get("hsm_engagement_threshold",40)) if machine else 40
    high = float(machine.get("high_engagement_threshold",80)) if machine else 80
    slot = float(machine.get("slot_engagement_threshold",95)) if machine else 95
    if not 0 < low < high < slot <= 100:
        raise ValueError("Engagement boundaries must satisfy 0 < HSM < High < Slot <= 100")
    if percent >= slot:
        return "slot"
    if percent > high:
        return "high"
    if percent >= low:
        return "cut"
    return "hsm"


def feed_factor(regime, operation, tool, machine=None):
    if regime == "air":
        return 1.0
    regime = {"low":"hsm", "standard":"cut"}.get(regime,regime)
    field, default = FEED_FIELDS[regime]
    override = float(getattr(operation, field, 0) or 0)
    inherited = machine.get(field,default) if machine is not None and regime in ("slot","high") else tool.get(field,default)
    percent = override if override else float(inherited)
    if not math.isfinite(percent) or not 0 < percent <= 300:
        raise ValueError(f"{field} must be 1–300% (operation 0 inherits tool)")
    return percent/100


def measure_segments(points, closed, material, radius):
    """Peak occupied cutter chord at several stations/forward offsets per move.

    Forward chords detect frontal entry from cleared space: a link can have an
    empty centre cross-section but still be slotting at its leading edge.
    Returns left width, right width, engagement and segment length arrays.
    """
    p = np.asarray(points, float)
    q = np.vstack((p, p[0])) if closed else p
    a, b = q[:-1], q[1:]
    delta = b-a
    lengths = np.linalg.norm(delta, axis=1)
    tangent = delta/np.maximum(lengths[:, None], 1e-20)
    normal = np.column_stack((-tangent[:, 1], tangent[:, 0]))
    left = np.zeros(len(a))
    right = np.zeros(len(a))
    forward = radius*np.array([0., .25, .5, .75])
    chord = np.sqrt(np.maximum(radius*radius-forward*forward, 0))
    stations = np.array([.25, .75, 1.])
    for start in range(0, len(a), 512):
        end = start+512
        centres = (a[start:end, None, None, :] + delta[start:end, None, None, :]*stations[None, :, None, None]
                   + tangent[start:end, None, None, :]*forward[None, None, :, None])
        offsets = normal[start:end, None, None, :]*chord[None, None, :, None]
        l = np.stack((centres, centres+offsets), axis=-2).reshape(-1, 2, 2)
        r = np.stack((centres, centres-offsets), axis=-2).reshape(-1, 2, 2)
        count = len(a[start:end])
        lw = length(intersection(linestrings(l), material)).reshape(count, -1)
        rw = length(intersection(linestrings(r), material)).reshape(count, -1)
        best = np.argmax(lw+rw, axis=1)
        left[start:end] = lw[np.arange(count), best]
        right[start:end] = rw[np.arange(count), best]
    engagement = np.clip((left+right)/(2*radius), 0, 1)
    # Sampling must not call a grazing leading-cap contact an air move.
    for i in np.flatnonzero((engagement <= 1e-6) & (lengths > 1e-9)):
        fresh = material.intersection(LineString((a[i], b[i])).buffer(radius)).area
        if fresh > max(1e-9, radius*radius*1e-8):
            engagement[i] = max(.01, min(1., fresh/(2*radius*lengths[i])))
            left[i] = right[i] = engagement[i]*radius
    return left, right, engagement, lengths


def _hand(left, right, engagement, machine=None):
    if engagement <= 1e-6:
        return "air"
    if engagement_band(engagement, machine) == "slot":
        return "neutral"
    difference = right-left
    if abs(difference) <= .2*max(left+right, 1e-12):
        return "mixed"
    # M3 spindle: uncut material on the right of tool travel is climb.
    return "climb" if difference > 0 else "conventional"


def _conditions(measured, operation, tool, neutral=False, machine=None):
    left, right, engagement, _ = measured
    return [CutCondition(float(e), engagement_band(e,machine),
                         "neutral" if neutral and e > 1e-6 else _hand(l, r, e,machine),
                         feed_factor(engagement_band(e,machine), operation, tool,machine))
            for l, r, e in zip(left, right, engagement)]


def plan_engagement(paths, job, operation, tool, log=None, initial_material=None):
    """Orient/annotate operation paths using incremental planar material removal."""
    tool_data = tool.resolved() if hasattr(tool,"resolved") else tool
    machine_data = job.machine.resolved()
    engagement_band(.5,machine_data)  # validate machine thresholds even for an all-air operation
    radius = float(tool_data.get("diameter", 0))/2
    if radius <= 0 or not math.isfinite(radius):
        raise ValueError("Engagement estimation requires a positive tool diameter")
    stock = getattr(job.cam_setup, "stock", None)
    if initial_material is not None:
        material = initial_material
    elif stock is not None and stock.allocated:
        lo, hi = stock.bounds
        material = box(lo[0], lo[1], hi[0], hi[1])
    else:
        points = np.concatenate([p.points[:, :2] for p in paths])
        lo, hi = points.min(axis=0)-2*radius, points.max(axis=0)+2*radius
        material = box(lo[0], lo[1], hi[0], hi[1])
        if log:
            log("  engagement uses a conservative XY blank estimate (stock not allocated)")
    mode = direction_for(job, operation) if operation.kind in ("pocket", "profile", "slot") else None
    totals = Counter()
    flipped = slots = handed = 0
    previous = None
    warnings = []
    for path in paths:
        p = np.asarray(path.points, float)
        path.link_condition = None
        if path.stay_down and (previous is None or path.stay_down_from is None or
                               not np.allclose(previous, path.stay_down_from, atol=1e-7, rtol=0)):
            path.stay_down = False
            path.stay_down_from = None
        if previous is not None and path.stay_down and path.stay_down_from is not None:
            link = np.array([previous, p[0]])
            measured = measure_segments(link, False, material, radius)
            condition = _conditions(measured, operation, tool_data, machine=machine_data)[0]
            if condition.hand == "mixed":
                # A balanced frontal entry cuts both sides; it cannot define a
                # unique climb/conventional hand, just like a slot. Keep its
                # measured engagement band (often high) for reduced entry feed.
                condition = CutCondition(condition.engagement, condition.regime, "neutral", condition.feed_factor)
            # Do not knowingly cut a one-sided connector against the requested hand.
            if mode in ("climb", "conventional") and condition.hand not in (mode, "air", "neutral"):
                path.stay_down = False
                path.stay_down_from = None
            else:
                path.link_condition = condition
                material = material.difference(LineString(link).buffer(radius))
                totals[condition.regime] += 1
        measured = measure_segments(p, path.closed, material, radius)
        left, right, engagement, lengths = measured
        slot_limit = float(machine_data.get("slot_engagement_threshold",95))/100-1e-9
        neutral = float(lengths[engagement >= slot_limit].sum()) >= .75*max(float(lengths.sum()), 1e-12)
        active = (engagement > 1e-6) & (engagement < slot_limit)
        vote = float(((right-left)*lengths*active).sum())
        desired = mode
        if mode == "meander" and not neutral and abs(vote) > 1e-9:
            desired = "climb" if handed % 2 == 0 else "conventional"
        if mode and not neutral and abs(vote) > 1e-9:
            reverse = (desired == "climb" and vote < 0) or (desired == "conventional" and vote > 0)
            if reverse:
                p = np.vstack((p[0], p[:0:-1])) if path.closed else p[::-1].copy()
                path.points = p
                if not path.closed:
                    path.stay_down = False
                    path.stay_down_from = None
                    path.link_condition = None
                measured = measure_segments(p, path.closed, material, radius)
                flipped += 1
            handed += 1
        slots += int(neutral)
        path.cut_conditions = _conditions(measured, operation, tool_data, neutral, machine_data)
        totals.update(c.regime for c in path.cut_conditions)
        if desired in ("climb", "conventional") and not neutral:
            checked = [(c, d) for c, d in zip(path.cut_conditions, measured[3])
                       if c.hand not in ("neutral", "air")]
            wrong = sum(d for c, d in checked if c.hand != desired)
            if wrong > .02*max(sum(d for _, d in checked), 1e-12):
                message = (f"{operation.name}: local material switches sides along a path; "
                           f"not every non-slot segment can remain {desired}. Inspect engagement/direction.")
                if message not in warnings:
                    warnings.append(message)
        loop = np.vstack((p, p[0])) if path.closed else p
        material = material.difference(LineString(loop).buffer(radius))
        previous = loop[-1]
    if log:
        log(f"  {operation.name}: remaining-material direction, {flipped} paths reversed; "
            f"{slots} full-slot/neutral paths (do not choose cutting hand)")
        log("  engagement moves: " + ", ".join(f"{k}={totals[k]}" for k in ("slot", "high", "cut", "hsm", "air")))
        for warning in warnings:
            log("ENGAGEMENT WARNING: " + warning)
    return warnings
