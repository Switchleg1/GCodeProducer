"""2D in-operation removal/engagement estimate, not a 3D machining simulation.

Choose clearing hand from the material remaining on each side, not from the
final wall or a first full-width slot. Tool sweeps are subtracted after each
path/link. The caller supplies depth-aware removal history from earlier
operations; identical planar states may reuse plans. Flute shape, tooth-level
axial engagement, holders and fixtures are not modelled.
"""
from __future__ import annotations

from gcodeproducer.core.cam.cam_constants import FEED_FIELDS
from collections import Counter
import math, numpy as np
from shapely import covers, intersection, intersects, length, linestrings, prepare, total_bounds
from shapely.geometry import LineString, box
from gcodeproducer.core.cam.paths import direction_for
from gcodeproducer.core.jobs.cut_condition import CutCondition


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


def _occupied(lines, material):
    """Length of each chord inside the material.

    Most chords lie wholly inside or outside; prepared predicates settle those and
    only boundary-crossing chords need an exact intersection.
    """
    result = np.zeros(len(lines))
    if material.is_empty or not len(lines):
        return result
    # Work against the material near these chords only: late in a pocket the full
    # remaining-material polygon is large while one batch of chords is local.
    low, high = total_bounds(lines)[:2], total_bounds(lines)[2:]
    if not np.isfinite(np.r_[low, high]).all():
        return result
    material = material.intersection(box(low[0]-1e-6, low[1]-1e-6, high[0]+1e-6, high[1]+1e-6))
    if material.is_empty:
        return result
    prepare(material)
    inside = covers(material, lines)
    result[inside] = length(lines[inside])
    crossing = ~inside & intersects(material, lines)
    if crossing.any():
        result[crossing] = length(intersection(lines[crossing], material))
    return result


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
    for start in range(0, len(a), 64):
        end = start+64
        centres = (a[start:end, None, None, :] + delta[start:end, None, None, :]*stations[None, :, None, None]
                   + tangent[start:end, None, None, :]*forward[None, None, :, None])
        offsets = normal[start:end, None, None, :]*chord[None, None, :, None]
        l = np.stack((centres, centres+offsets), axis=-2).reshape(-1, 2, 2)
        r = np.stack((centres, centres-offsets), axis=-2).reshape(-1, 2, 2)
        count = len(a[start:end])
        lw = _occupied(linestrings(l), material).reshape(count, -1)
        rw = _occupied(linestrings(r), material).reshape(count, -1)
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
    """Compatibility wrapper: the shared EngagementModel classifies every sampler's measurement."""
    from gcodeproducer.core.cam.planner.engagement_model import EngagementModel
    left, right, engagement, _ = measured
    return EngagementModel(operation, tool, machine or {}).classify(left, right, engagement, neutral)


def plan_engagement(paths, job, operation, tool, log=None, initial_material=None):
    """Orient/annotate operation paths using incremental planar material removal.

    Measurement is the material model's planar sampler; classification is the
    shared :class:`EngagementModel` used by every operation and the XYZ sampler.
    """
    from gcodeproducer.core.cam.planner.engagement_model import EngagementModel
    from gcodeproducer.core.cam.planner.material_model import MaterialModel
    model = EngagementModel(operation, tool, job.machine)
    machine_data = model.machine
    radius = float(model.tool.get("diameter", 0))/2
    if radius <= 0 or not math.isfinite(radius):
        raise ValueError("Engagement estimation requires a positive tool diameter")
    stock = getattr(job.cam_setup, "stock", None)
    allocated = stock is not None and stock.allocated
    if initial_material is None and not allocated and log:
        log("  engagement uses a conservative XY blank estimate (stock not allocated)")
    points = np.concatenate([np.asarray(p.points)[:, :2] for p in paths]) if paths else np.zeros((1, 2))
    sampler = MaterialModel(job, stock).planar_sampler(material=initial_material, fallback_points=points, radius=radius)
    mode = direction_for(job, operation) if operation.kind in ("pocket", "profile", "slot", "waterfall") else None
    totals = Counter()
    flipped = slots = handed = conflicts = 0
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
            left, right, engagement, _ = sampler.measure_path(link, False, radius)
            condition = model.classify(left, right, engagement)[0]
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
                sampler.remove_path(link, False, radius)
                totals[condition.regime] += 1
        measured = sampler.measure_path(p, path.closed, radius)
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
                measured = sampler.measure_path(p, path.closed, radius)
                flipped += 1
            handed += 1
        slots += int(neutral)
        path.cut_conditions = model.classify(*measured[:3], neutral=neutral)
        totals.update(c.regime for c in path.cut_conditions)
        if desired in ("climb", "conventional") and not neutral:
            checked = [(c, d) for c, d in zip(path.cut_conditions, measured[3])
                       if c.hand not in ("neutral", "air")]
            wrong = sum(d for c, d in checked if c.hand != desired)
            if wrong > .02*max(sum(d for _, d in checked), 1e-12):
                path.cut_conditions = [CutCondition(c.engagement, c.regime, c.hand, c.feed_factor,
                                                    conflict=c.hand not in ("neutral", "air", desired))
                                       for c in path.cut_conditions]
                conflicts += sum(c.conflict for c in path.cut_conditions)
                message = (f"{operation.name}: local material switches sides along a path; "
                           f"not every non-slot segment can remain {desired}. "
                           f"Segments cutting the other hand are highlighted as Conflict.")
                if message not in warnings:
                    warnings.append(message)
        sampler.remove_path(p, path.closed, radius)
        loop = np.vstack((p, p[0])) if path.closed else p
        previous = loop[-1]
    if log:
        log(f"  {operation.name}: remaining-material direction, {flipped} paths reversed; "
            f"{slots} full-slot/neutral paths (do not choose cutting hand)")
        log("  engagement moves: " + ", ".join(f"{k}={totals[k]}" for k in ("slot", "high", "cut", "hsm", "air"))
            + (f", conflict segments={conflicts}" if conflicts else ""))
        for warning in warnings:
            log("ENGAGEMENT WARNING: " + warning)
    return warnings
