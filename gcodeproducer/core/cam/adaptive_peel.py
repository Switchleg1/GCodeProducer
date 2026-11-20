"""Experimental stock-driven selection of one local peel, not a pocket planner."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import (
    ADAPTIVE_PEEL_ADVANCE_FACTORS, ADAPTIVE_PEEL_CHORD_ERROR, ADAPTIVE_PEEL_MAX_SEGMENTS,
    ADAPTIVE_PEEL_MIN_SEGMENTS, ADAPTIVE_PEEL_SAMPLE_STEP_RADII,
)
from gcodeproducer.core.cam.engagement import measure_segments


@dataclass(frozen=True)
class PeelChoice:
    points: np.ndarray
    centre: np.ndarray
    advance: float
    peak_engagement: float
    removed_area: float
    length: float
    remaining: BaseGeometry


def _turn(centre, seam, advance, sense, tool_radius):
    """One turn with a tangent-matched translation, no jump at the seam."""
    radius = float(np.linalg.norm(seam))
    bound = radius + float(np.linalg.norm(advance))
    angle = 2*math.asin(math.sqrt(min(1., ADAPTIVE_PEEL_CHORD_ERROR/(2*bound))))
    n = max(ADAPTIVE_PEEL_MIN_SEGMENTS, math.ceil(math.pi/angle),
            math.ceil((2*math.pi*radius + 1.5*np.linalg.norm(advance))
                      / (tool_radius*ADAPTIVE_PEEL_SAMPLE_STEP_RADII)))
    if n > ADAPTIVE_PEEL_MAX_SEGMENTS:
        raise ValueError('Adaptive peel exceeds the per-turn sample budget')
    t = np.linspace(0., 1., n+1)
    theta = sense*2*math.pi*t
    normal = np.array([-seam[1], seam[0]])
    shift = t*t*(3.-2.*t)
    points = centre + np.cos(theta[:, None])*seam + np.sin(theta[:, None])*normal + shift[:, None]*advance
    points[0], points[-1] = centre+seam, centre+advance+seam
    return points


def evaluate_peel(points, material, radius, *, abort_above=1.):
    """Replay each chord against current stock; return None on a sampled overload.

    The caller supplies the actual material at cutting depth, including the
    stock state at the start point. No entry footprint is assumed cleared.
    Engagement uses the application's occupied-width proxy, not contact angle.
    """
    # Only nearby stock can affect this turn. Preserve the rest exactly.
    sweep = LineString(points).buffer(radius)
    # The sampler also looks ahead of segment ends. Keep that halo so clipping
    # does not trim material that the engagement estimate would otherwise see.
    local = material.intersection(sweep.envelope.buffer(radius))
    remaining, peak, removed, length = local, 0., 0., 0.
    for a, b in zip(points, points[1:]):
        distance = float(np.linalg.norm(b-a))
        if distance <= 1e-9:
            continue
        chord = np.vstack((a, b))
        engagement = float(measure_segments(chord, False, remaining, radius)[2][0])
        peak = max(peak, engagement)
        if peak > abort_above:
            return None
        area = LineString(chord).buffer(radius)
        removed += remaining.intersection(area).area
        remaining = remaining.difference(area)
        length += distance
    return peak, removed, length, material.difference(local.difference(remaining))


def choose_peel(centre, seam, axis, pitch, tool_radius, limit, region, material, *, sense=1,
                factors=ADAPTIVE_PEEL_ADVANCE_FACTORS):
    """Choose a legal useful turn by sampled engagement and removal per travel.

    ``region`` is already inset for cutter radius and allowance. Returns None
    rather than silently slotting, leaving the caller to try another heading,
    a different entry, or a different strategy. This only evaluates one turn;
    it does not guarantee complete coverage or choose the next pocket branch.
    """
    centre, seam, axis = (np.asarray(v, float) for v in (centre, seam, axis))
    if (any(v.shape != (2,) or not np.all(np.isfinite(v)) for v in (centre, seam, axis))
            or not math.isfinite(pitch) or pitch <= 0 or not math.isfinite(tool_radius) or tool_radius <= 0
            or not 0 < limit <= 1 or sense not in (-1, 1)):
        raise ValueError('Invalid adaptive peel geometry or engagement limit')
    norm = float(np.linalg.norm(axis))
    if norm <= 1e-9 or np.linalg.norm(seam) <= 1e-9:
        raise ValueError('Adaptive peel needs a nonzero heading and loop radius')
    valid = prep(region.buffer(1e-7))
    best = None
    for factor in factors:
        if not 0 < factor <= 1:
            raise ValueError('Adaptive peel trial factors must be in (0, 1]')
        step = pitch*factor
        advance = axis*(step/norm)
        points = _turn(centre, seam, advance, sense, tool_radius)
        if not valid.covers(LineString(points)):
            continue
        outcome = evaluate_peel(points, material, tool_radius, abort_above=limit)
        if outcome is None:
            continue
        peak, area, length, remaining = outcome
        if area <= 1e-8 or length <= 0:
            continue
        if best is None or area/length > best.removed_area/best.length:
            best = PeelChoice(points, centre+advance, step, peak, area, length, remaining)
    return best
