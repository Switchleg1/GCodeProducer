"""Experimental helical entry for a ramp-capable flat cutter."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel

from gcodeproducer.core.cam.cam_constants import (
    ADAPTIVE_ENTRY_LIMIT, ADAPTIVE_ENTRY_RADIUS_FACTOR, ADAPTIVE_PEEL_CHORD_ERROR,
    ADAPTIVE_PEEL_MIN_SEGMENTS, RAMP_TAN,
)
from gcodeproducer.core.cam.planner.planner_constants import CLEARANCE_MARGIN
from gcodeproducer.core.geometry.polygon_parts import polygons


@dataclass(frozen=True)
class AdaptiveEntry:
    points: np.ndarray  # XYZ; first point is at supplied stock top, not safe Z
    remaining: BaseGeometry  # only credits the flat lap at cut depth


def seed_entry(region, material, *, radius, top, depth, sense=1):
    """Find a contained helix and finish a full lap at the requested Z.

    The caller must qualify the tool for ramping, the depth and flute reach,
    and travel to the start. Region is already inset for cutter and allowance;
    material represents stock at the active plane. No machine output is made.
    """
    if (not all(math.isfinite(v) for v in (radius, top, depth)) or radius <= 0
            or top <= depth or sense not in (-1, 1)):
        raise ValueError('Adaptive entry requires a positive tool radius and descending Z range')
    best = None
    for part in polygons(region):
        centre = polylabel(part, tolerance=ADAPTIVE_PEEL_CHORD_ERROR)
        if not part.contains(centre):
            continue
        clearance = centre.distance(part.boundary)
        orbit = min(radius*ADAPTIVE_ENTRY_RADIUS_FACTOR, clearance-CLEARANCE_MARGIN)
        if orbit <= ADAPTIVE_PEEL_CHORD_ERROR:
            continue
        angle = 2*math.asin(math.sqrt(min(1., ADAPTIVE_PEEL_CHORD_ERROR/(2*orbit))))
        n = max(ADAPTIVE_PEEL_MIN_SEGMENTS, math.ceil(math.pi/angle))
        if n >= ADAPTIVE_ENTRY_LIMIT:
            continue
        theta = sense*2*math.pi*np.arange(n+1)/n
        xy = np.asarray(centre.coords[0]) + orbit*np.column_stack((np.cos(theta), np.sin(theta)))
        xy[-1] = xy[0]
        ring = LineString(xy)
        if not part.covers(ring):
            continue
        # Use the actual chord length, not the larger ideal circumference.
        per_lap = RAMP_TAN * np.linalg.norm(np.diff(xy, axis=0), axis=1).min() * n
        if top-depth > per_lap*((ADAPTIVE_ENTRY_LIMIT-2)//n-1):
            continue
        laps = max(1, math.ceil((top-depth)/per_lap))
        if n*(laps+1)+2 > ADAPTIVE_ENTRY_LIMIT:
            continue
        sweep = ring.buffer(radius)
        removed = material.intersection(sweep).area
        if removed <= 1e-8:
            continue
        key = (orbit, removed, -laps)
        if best is None or key > best[0]:
            best = key, xy, n, laps, sweep, centre.coords[0]
    if best is None:
        return None
    _, xy, n, laps, sweep, centre = best
    count = n*laps
    ramp = np.column_stack((xy[np.arange(count+1) % n], np.linspace(top, depth, count+1)))
    flat = np.column_stack((xy[1:], np.full(n, depth)))
    # Finish inside the swept patch so the next transfer has clearance on
    # both sides of the cutter, instead of starting at the fresh wall.
    return AdaptiveEntry(np.vstack((ramp, flat, [*centre, depth])), material.difference(sweep))
