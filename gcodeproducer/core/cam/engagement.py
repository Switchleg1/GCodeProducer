"""2D in-operation removal/engagement estimate, not a 3D machining simulation.

Choose clearing hand from the material remaining on each side, not from the
final wall or a first full-width slot. Tool sweeps are subtracted after each
path/link. The caller supplies depth-aware removal history from earlier
operations; identical planar states may reuse plans. Flute shape, tooth-level
axial engagement, holders and fixtures are not modelled.
"""
from __future__ import annotations

from gcodeproducer.core.cam.cam_constants import (FEED_FIELDS, ADAPTIVE_ENGAGEMENT_BATCH_DIAMETERS,
                                                  SLOT_ADVANCE_REACH, SLOT_ADVANCE_SHARE, SLOT_ADVANCE_SAMPLES)
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
    low = float(machine.get("hsm_engagement_threshold",15)) if machine else 15
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
    """Measure equal-size batches of left and right chords together."""
    result = np.zeros(lines.shape)
    if material.is_empty or not lines.size:
        return result
    # Clip each side independently: enlarging either clip to the combined
    # bounds can change GEOS overlay rounding at the chord intersections.
    local = np.empty((len(lines), 1), dtype=object)
    for i, side in enumerate(lines):
        low_x, low_y, high_x, high_y = total_bounds(side)
        if not np.isfinite((low_x, low_y, high_x, high_y)).all():
            local[i, 0] = None
        else:
            local[i, 0] = material.intersection(box(low_x-1e-6, low_y-1e-6, high_x+1e-6, high_y+1e-6))
    prepare(local)
    inside = covers(local, lines)
    result[inside] = length(lines[inside])
    crossing = ~inside & intersects(local, lines)
    if crossing.any():
        result[crossing] = length(intersection(lines[crossing], local[np.nonzero(crossing)[0], 0]))
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
        chords = np.empty((2, *centres.shape[:-1], 2, 2))
        chords[..., 0, :] = centres
        chords[0, ..., 1, :] = centres+offsets
        chords[1, ..., 1, :] = centres-offsets
        count = len(a[start:end])
        lw, rw = _occupied(linestrings(chords.reshape(2, -1, 2, 2)), material).reshape(2, count, -1)
        best = np.argmax(lw+rw, axis=1)
        left[start:end] = lw[np.arange(count), best]
        right[start:end] = rw[np.arange(count), best]
    engagement = np.clip((left+right)/(2*radius), 0, 1)
    # Sampling must not call a grazing leading-cap contact an air move.
    for i in np.flatnonzero((engagement <= 1e-6) & (lengths > 1e-9)):
        line = LineString((a[i], b[i]))
        # A polygonal buffer is inscribed in the true round end cap. Even
        # an empty overlay cannot certify air: test centreline distance first,
        # allowing for independent 0.001 mm XY rounding of both sweeps.
        if material.is_empty or line.distance(material) > radius + .002:
            continue
        fresh = material.intersection(line.buffer(radius)).area
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


def _side_of(points, closed, others):
    """Which side of a path other points lie on: positive left of its travel, negative right, 0 unclear."""
    q = np.vstack((points, points[0])) if closed else np.asarray(points, float)
    a, b = q[:-1], q[1:]
    d = b-a
    size = np.einsum('ij,ij->i', d, d)
    keep = size > 1e-18
    a, d, size = a[keep], d[keep], size[keep]
    if not len(a) or not len(others):
        return 0.
    sample = others[np.linspace(0, len(others)-1, min(len(others), SLOT_ADVANCE_SAMPLES), dtype=int)]
    votes = 0.
    for point in sample:
        w = point-a
        t = np.clip(np.einsum('ij,ij->i', w, d)/size, 0, 1)
        off = w-t[:, None]*d
        k = int(np.argmin(np.einsum('ij,ij->i', off, off)))
        cross = d[k, 0]*off[k, 1]-d[k, 1]*off[k, 0]
        if abs(cross) > 1e-9:
            votes += 1. if cross > 0 else -1.
    return votes/len(sample) if abs(votes) > SLOT_ADVANCE_SHARE*len(sample) else 0.


def _conditions(measured, operation, tool, neutral=False, machine=None):
    """Compatibility wrapper: the shared EngagementModel classifies every sampler's measurement."""
    from gcodeproducer.core.cam.planner.engagement_model import EngagementModel
    left, right, engagement, _ = measured
    return EngagementModel(operation, tool, machine or {}).classify(left, right, engagement, neutral)


def plan_engagement(paths, job, operation, tool, log=None, initial_material=None, floor=None):
    """Orient/annotate operation paths using incremental planar material removal.

    Measurement is the material model's planar sampler; classification is the
    shared :class:`EngagementModel` used by every operation and the XYZ sampler.

    floor: the depth of this pass. A path that follows the surface clears the
    plane only along its stretches at that depth; given it, those stretches are
    taken out of the material the later paths are measured against (without it
    such a path clears nothing there, and a flat pass beside it reads as a slot).
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
    mode = direction_for(job, operation) if operation.kind in ("pocket", "profile", "slot", "pocket3d") else None
    totals = Counter()
    flipped = slots = handed = conflicts = 0
    previous = None
    warnings = []
    # Material for choosing the cutting hand of paths that follow the surface. They are kept out of
    # the main sampler (it must not certify later air moves through what they did not clear at the
    # floor), but each one has cut its own band beside the next: measured against the main sampler,
    # every following ring read as a full slot and kept whatever hand it was planned with.
    hand = None

    def measure_link(link):
        left, right, engagement, _ = sampler.measure_path(link, False, radius)
        condition = model.classify(left, right, engagement)[0]
        if condition.hand == 'mixed':
            # A balanced frontal entry has no unique climb/conventional hand.
            condition = CutCondition(condition.engagement, condition.regime, 'neutral', condition.feed_factor)
        return condition

    def allowed(condition):
        return mode not in ('climb', 'conventional') or condition.hand in (mode, 'air', 'neutral')

    for index, path in enumerate(paths):
        full = np.asarray(path.points, float)
        p = full[:, :2]  # measured in plan; a path that follows the surface keeps its own Z
        path.link_condition = None
        if path.stay_down and (previous is None or path.stay_down_from is None or
                               not np.allclose(previous, path.stay_down_from, atol=1e-7, rtol=0)):
            path.stay_down = False
            path.stay_down_from = None
        condition = None
        if previous is not None and path.stay_down:
            condition = measure_link(np.array([previous, p[0]]))
            if not allowed(condition):
                condition = None
        path.stay_down = condition is not None
        path.stay_down_from = tuple(previous) if path.stay_down else None
        if condition is not None:
            path.link_condition = condition
            sampler.remove_path(np.array([previous, p[0]]), False, radius)
            totals[condition.regime] += 1
        spiral = operation.strategy == 'adaptive' and not path.closed
        # A lifted pass does not clear its XY projection at the nominal floor.
        # Without depth-resolved history, never use it to certify a later air move.
        lifted = full.shape[1] == 3
        if lifted and hand is None:
            from gcodeproducer.core.cam.planner.planar_sampler import PlanarSampler
            hand = PlanarSampler(sampler.material)
        measurer = hand if lifted else sampler
        if spiral and len(p) > 1 and not lifted:
            # Measure successive short stretches against stock left by the earlier
            # turns, rather than classifying the whole uncut pocket as a slot.
            distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
            bands = np.floor(distance/(2*radius*ADAPTIVE_ENGAGEMENT_BATCH_DIAMETERS))
            limits = np.r_[0, np.flatnonzero(np.diff(bands[:-1]) > 0)+1, len(p)-1]
            measured = [[], [], [], []]
            for a, b in zip(limits, limits[1:]):
                stretch = p[a:b+1]
                for values, part in zip(measured, sampler.measure_path(stretch, False, radius)):
                    values.append(part)
                sampler.remove_path(stretch, False, radius)
            measured = [np.concatenate(parts) for parts in measured]
        else:
            measured = measurer.measure_path(p, path.closed, radius)
        left, right, engagement, lengths = measured
        slot_limit = float(machine_data.get("slot_engagement_threshold",95))/100-1e-9
        neutral = float(lengths[engagement >= slot_limit].sum()) >= .75*max(float(lengths.sum()), 1e-12)
        active = (engagement > 1e-6) & (engagement < slot_limit)
        vote = float(((right-left)*lengths*active).sum())
        desired = mode
        both_ways = spiral or (mode == "meander" and not path.closed
                               and operation.strategy in ("raster_x", "raster_y"))
        if mode == "meander" and not neutral and abs(vote) > 1e-9 and not both_ways:
            # (An adaptive chain, or Meander raster lines, are cut both ways by design: nothing to alternate.)
            desired = "climb" if handed % 2 == 0 else "conventional"
        if neutral and mode in ("climb", "conventional") and not spiral and len(p) > 1:
            # A full-width cut has stock on both flanks, so its own engagement names no hand. It is
            # the first move of an advance, though: cut it as the passes that follow will be cut,
            # with the stock still to be taken (the side it advances into) on the climb side.
            wide = measurer.measure_path(p, path.closed, SLOT_ADVANCE_REACH*radius)
            beside = float(((wide[1]-wide[0])*wide[3]).sum())
            total = float(((wide[1]+wide[0])*wide[3]).sum())
            if abs(beside) <= SLOT_ADVANCE_SHARE*max(total, 1e-12):
                # Stock on both sides alike (a wall of the part on one): go by where the next path lies.
                following = paths[index+1] if index+1 < len(paths) else None
                beside = -_side_of(p, path.closed, np.asarray(following.points, float)[:, :2])                     if following is not None else 0.
            vote = beside
        if mode and (not neutral or mode in ("climb", "conventional")) and abs(vote) > 1e-9:
            reverse = (desired == "climb" and vote < 0) or (desired == "conventional" and vote > 0)
            # A spiral must enter at its already chosen inner start, not run wall-in.
            if reverse and not spiral:
                full = np.vstack((full[0], full[:0:-1])) if path.closed else full[::-1].copy()
                path.points = full
                p = full[:, :2]
                if not path.closed:
                    path.stay_down = False
                    path.stay_down_from = None
                    path.link_condition = None
                measured = measurer.measure_path(p, path.closed, radius)
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
        if not spiral or len(p) < 2:
            if not lifted:
                sampler.remove_path(p, path.closed, radius)
            elif floor is not None:
                low = full[:, 2] <= floor+1e-6
                both = low[:-1] & low[1:]
                edges = np.flatnonzero(np.diff(np.r_[False, both, False].astype(int)))
                for first, last in zip(edges[::2], edges[1::2]):
                    sampler.remove_path(p[first:last+1], False, radius)
            if hand is not None:
                hand.remove_path(p, path.closed, radius)
        elif hand is not None:
            hand.remove_path(p, path.closed, radius)
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
