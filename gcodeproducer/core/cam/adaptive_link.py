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
    """Compare straight/one-waypoint travel with an already-qualified safe-Z transfer.

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

    if not clear_endpoint(end) or not clear_endpoint(start):
        return None
    distance = float(np.linalg.norm(end-start))
    direct = np.vstack((start, end))
    if distance <= 1e-9:
        return AdaptiveLink('stay_down', direct, 0.)

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
    lengths = np.linalg.norm(points-start, axis=1) + np.linalg.norm(points-end, axis=1)
    for i in np.argsort(lengths, kind='stable')[:ADAPTIVE_LINK_WAYPOINT_LIMIT]:
        minutes = float(lengths[i]/travel_feed)
        if minutes >= best.minutes:
            break
        route = np.vstack((start, points[i], end))
        if clear(route):
            return AdaptiveLink('stay_down', route, minutes)
    return best
