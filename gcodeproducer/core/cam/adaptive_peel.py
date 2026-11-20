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
    ADAPTIVE_PEEL_HEADINGS, ADAPTIVE_PEEL_RADIUS_FACTORS,
)
from gcodeproducer.core.cam.engagement import measure_segments


@dataclass(frozen=True)
class PeelChoice:
    points: np.ndarray
    centre: np.ndarray
    seam: np.ndarray
    advance: float
    peak_engagement: float
    removed_area: float
    length: float
    remaining: BaseGeometry


def _turn(centre, seam, advance, sense, tool_radius, end_scale=1.):
    """Translate and resize one turn, with zero translation/resize speed at each seam."""
    radius = float(np.linalg.norm(seam))
    max_radius = radius * max(1., end_scale)
    shift_length = float(np.linalg.norm(advance)) + radius*abs(end_scale-1.)
    bound = max_radius + shift_length
    angle = 2*math.asin(math.sqrt(min(1., ADAPTIVE_PEEL_CHORD_ERROR/(2*bound))))
    n = max(ADAPTIVE_PEEL_MIN_SEGMENTS, math.ceil(math.pi/angle),
            math.ceil((2*math.pi*max_radius + 1.5*shift_length)
                      / (tool_radius*ADAPTIVE_PEEL_SAMPLE_STEP_RADII)))
    if n > ADAPTIVE_PEEL_MAX_SEGMENTS:
        raise ValueError('Adaptive peel exceeds the per-turn sample budget')
    t = np.linspace(0., 1., n+1)
    theta = sense*2*math.pi*t
    normal = np.array([-seam[1], seam[0]])
    shift = t*t*(3.-2.*t)
    orbit = np.cos(theta[:, None])*seam + np.sin(theta[:, None])*normal
    points = centre + orbit*(1.+shift[:, None]*(end_scale-1.)) + shift[:, None]*advance
    points[0], points[-1] = centre+seam, centre+advance+seam*end_scale
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
                factors=ADAPTIVE_PEEL_ADVANCE_FACTORS, headings=(0.,), radii=(1.,),
                min_loop_radius=None, max_loop_radius=None):
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
    radius = float(np.linalg.norm(seam))
    low = radius if min_loop_radius is None else min_loop_radius
    high = radius if max_loop_radius is None else max_loop_radius
    if not (0 < low <= high < math.inf and low-1e-12 <= radius <= high+1e-12):
        raise ValueError('Adaptive peel radius bounds must contain the current radius')
    factors, headings, radii = tuple(factors), tuple(headings), tuple(radii)
    if not all(0 < f <= 1 for f in factors) or not all(math.isfinite(h) and abs(h) < 90 for h in headings):
        raise ValueError('Adaptive peel trial factors or headings are invalid')
    if not all(0 < f < math.inf for f in radii):
        raise ValueError('Adaptive peel radius factors must be positive and finite')
    scales = dict.fromkeys(float(np.clip(radius*f, low, high))/radius for f in radii)
    valid = prep(region.buffer(1e-7))
    axis = axis/norm
    side = np.array([-axis[1], axis[0]])
    best = None
    for heading in headings:
        angle = math.radians(heading)
        direction = math.cos(angle)*axis + math.sin(angle)*side
        for scale in scales:
            for factor in factors:
                step = pitch*factor
                advance = direction*step
                points = _turn(centre, seam, advance, sense, tool_radius, scale)
                if not valid.covers(LineString(points)):
                    continue
                outcome = evaluate_peel(points, material, tool_radius, abort_above=limit)
                if outcome is None:
                    continue
                peak, area, length, remaining = outcome
                if area <= 1e-8 or length <= 0:
                    continue
                if best is None or area/length > best.removed_area/best.length:
                    best = PeelChoice(points, centre+advance, seam*scale, step, peak, area, length, remaining)
    return best


def choose_steered_peel(centre, seam, axis, pitch, tool_radius, limit, region, material, *,
                        min_loop_radius, max_loop_radius, sense=1):
    """Search a small fan around the requested heading, with bounded changes in loop size."""
    return choose_peel(centre, seam, axis, pitch, tool_radius, limit, region, material, sense=sense,
                       headings=ADAPTIVE_PEEL_HEADINGS, radii=ADAPTIVE_PEEL_RADIUS_FACTORS,
                       min_loop_radius=min_loop_radius, max_loop_radius=max_loop_radius)


def trace_peels(centre, seam, axis, pitch, tool_radius, limit, region, material, *,
                min_loop_radius, max_loop_radius, turns, sense=1):
    """Continue from each exact endpoint without inventing a link on failure.

    This traces a supplied local course; it does not discover branches or
    select a new entry after the fan runs out of useful candidates.
    """
    if not isinstance(turns, int) or turns < 1:
        raise ValueError('Adaptive peel trace needs a positive turn budget')
    result = []
    for _ in range(turns):
        choice = choose_steered_peel(centre, seam, axis, pitch, tool_radius, limit, region, material,
                                     min_loop_radius=min_loop_radius, max_loop_radius=max_loop_radius,
                                     sense=sense)
        if choice is None:
            break
        result.append(choice)
        centre, seam, material = choice.centre, choice.seam, choice.remaining
    return result
