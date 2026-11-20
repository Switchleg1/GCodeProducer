"""Experimental same-depth linking over verified cleared stock."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from gcodeproducer.core.cam.cam_constants import ADAPTIVE_LINK_BUFFER_QUADS, ADAPTIVE_LINK_WAYPOINT_LIMIT
from gcodeproducer.core.cam.planner.planner_constants import CLEARANCE_MARGIN


@dataclass(frozen=True)
class AdaptiveLink:
    kind: str
    points: np.ndarray  # moves on the current plane; retract XY is at the caller's verified safe plane
    minutes: float


def choose_link(start, end, region, material, radius, *, travel_feed, z_feed, lift,
                waypoints=()):
    """Compare straight, one- and two-waypoint travel with an already-qualified safe-Z transfer.

    Caller supplies the cutter-centre region, current material at the cutting
    plane and the rise to a safe plane above stock, part and any fixtures. The
    estimate uses constant feed, with no acceleration model. None means the
    destination needs a real entry cut, which this helper does not plan.
    """
    if not all(math.isfinite(v) and v > 0 for v in (radius, travel_feed, z_feed, lift)):
        raise ValueError('Adaptive link needs positive finite radius, feeds and safe-plane lift')
    start, end = np.asarray(start, float), np.asarray(end, float)
    if any(p.shape != (2,) or not np.isfinite(p).all() for p in (start, end)):
        raise ValueError('Adaptive link needs finite XY endpoints')
    valid = prep(region.buffer(1e-7))
    stock = prep(material)
    # Circumscribe the required radius: a polygonal buffer otherwise falls
    # inside the true circular sweep between vertices.
    quads = ADAPTIVE_LINK_BUFFER_QUADS
    reach = (radius + CLEARANCE_MARGIN) / math.cos(math.pi/(4*quads))

    def clear_endpoint(p):
        point = Point(p)
        return valid.covers(point) and not stock.intersects(point.buffer(reach, quad_segs=quads))

    distance = float(np.linalg.norm(end-start))
    direct = np.vstack((start, end))
    if np.array_equal(start, end) and valid.covers(Point(start)):
        # No transfer at all: the cutter is already at this point. The peel
        # evaluator will measure the next actual motion against live stock.
        return AdaptiveLink('stay_down', direct, 0.)
    if not clear_endpoint(end) or not clear_endpoint(start):
        return None

    def clear(points):
        line = LineString(points)
        return valid.covers(line) and not stock.intersects(line.buffer(reach, quad_segs=quads))

    if clear(direct):
        return AdaptiveLink('stay_down', direct, distance/travel_feed)
    best = AdaptiveLink('retract', direct, distance/travel_feed + 2*lift/z_feed)
    points = np.asarray(waypoints, float)
    if not points.size:
        return best
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Adaptive link waypoints must be finite XY pairs')
    from_start = np.linalg.norm(points-start, axis=1)
    to_end = np.linalg.norm(points-end, axis=1)
    lengths = from_start + to_end
    indices = np.argsort(lengths, kind='stable')[:ADAPTIVE_LINK_WAYPOINT_LIMIT]
    indices = indices[lengths[indices]/travel_feed < best.minutes]
    # A candidate leg with a repeated point is a stationary disk, not an
    # invalid zero-length LineString. All moving legs use swept clearance.
    def visible(a, b):
        return clear_endpoint(a) if np.array_equal(a, b) else clear((a, b))

    starts = [i for i in indices if visible(start, points[i])]
    ends = [i for i in indices if visible(points[i], end)]
    pairs = [(float((from_start[i]+np.linalg.norm(points[j]-points[i])+to_end[j])/travel_feed), i, j)
             for i in starts for j in ends]
    for minutes, i, j in sorted(pairs):
        if minutes >= best.minutes:
            break
        if i == j or visible(points[i], points[j]):
            mids = points[[i]] if i == j else points[[i, j]]
            route = np.vstack((start, mids, end))
            # Drop duplicate endpoints without changing any verified leg.
            keep = np.r_[True, np.any(route[1:] != route[:-1], axis=1)]
            return AdaptiveLink('stay_down', route[keep], minutes)
    return best
