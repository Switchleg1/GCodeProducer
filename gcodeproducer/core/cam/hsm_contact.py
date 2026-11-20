"""Independent planar cutter-periphery contact measurement for HSM trials.

This is a pose query, not a stock simulator. Callers supply the material
remaining immediately before the pose, excluding prior cutter sweeps.
"""
from __future__ import annotations

import math

import numpy as np
from shapely.geometry import Point
from shapely.prepared import prep

from gcodeproducer.core.geometry.polygon_parts import polygons


def occupied_arcs(centre, radius, stock):
    """Return occupied intervals in radians on [0, 2π], split at the seam.

    Intersect the analytic cutter circle with the polygon edges, then test
    one midpoint in each interval. A tangent touch has zero angular width.
    Stock is planar Polygon/MultiPolygon material, possibly with holes.
    """
    centre = np.asarray(centre, dtype=float)
    if (centre.shape != (2,) or not np.isfinite(centre).all()
            or not math.isfinite(radius) or radius <= 0):
        raise ValueError('HSM contact requires finite XY and a positive cutter radius')
    if stock.is_empty:
        return []
    tau = math.tau
    events = [0., tau]
    # Work in cutter radii to keep intersection tolerances scale-independent.
    for part in polygons(stock):
        x0, y0, x1, y1 = part.bounds
        x, y = centre
        if x+radius < x0 or x-radius > x1 or y+radius < y0 or y-radius > y1:
            continue
        for ring in (part.exterior, *part.interiors):
            coords = (np.asarray(ring.coords)[:, :2]-centre)/radius
            a, b = coords[:-1], coords[1:]
            # Edges wholly on one side of the cutter box cannot meet the circle.
            local = np.all(np.minimum(a, b) <= 1., axis=1) & np.all(np.maximum(a, b) >= -1., axis=1)
            a, b = a[local], b[local]
            delta = b-a
            norm2 = (delta*delta).sum(axis=1)
            nonzero = norm2 > 0
            a, delta, norm2 = a[nonzero], delta[nonzero], norm2[nonzero]
            t = -(a*delta).sum(axis=1)/norm2
            closest = a+t[:, None]*delta
            h2 = 1.-(closest*closest).sum(axis=1)
            hits = h2 >= -1e-12
            for sense in (-1, 1):
                where = t[hits] + sense*np.sqrt(np.maximum(0., h2[hits])/norm2[hits])
                on_segment = (where >= -1e-12) & (where <= 1.+1e-12)
                p = a[hits][on_segment] + np.clip(where[on_segment], 0., 1.)[:, None]*delta[hits][on_segment]
                events.extend(np.mod(np.arctan2(p[:, 1], p[:, 0]), tau))
    region = prep(stock)
    arcs = []
    ordered = sorted(events)
    for a, b in zip(ordered, ordered[1:]):
        if b-a <= 1e-12:
            continue
        t = (a+b)/2
        if not region.covers(Point(centre + radius*np.array([math.cos(t), math.sin(t)]))):
            continue
        if arcs and abs(arcs[-1][1]-a) <= 1e-12:
            arcs[-1] = (arcs[-1][0], b)
        else:
            arcs.append((a, b))
    return arcs


def contact_angle(centre, radius, stock):
    """Total occupied periphery in degrees; disjoint contact patches add."""
    return math.degrees(sum(b-a for a, b in occupied_arcs(centre, radius, stock)))
