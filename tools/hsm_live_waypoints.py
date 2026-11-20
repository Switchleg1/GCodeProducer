"""Bounded waypoint sampling from the current planar clearance."""
import math

from shapely.geometry import Point


def live_waypoints(pocket, stock, xy, radius, *, spacing, rings, limit, margin=0.):
    """Return cardinal poses at the nearest cleared grid points around XY."""
    if (not all(map(math.isfinite, (radius, spacing, margin))) or min(radius, spacing) <= 0
            or margin < 0 or rings < 1 or limit < 1):
        raise ValueError('expected positive radius, spacing, rings and limit, and nonnegative margin')
    offsets = sorted(((i, j) for i in range(-rings, rings+1) for j in range(-rings, rings+1) if i or j),
                     key=lambda ij: (ij[0]**2 + ij[1]**2, *ij))
    clearance = radius + margin
    walls = pocket.boundary
    accepted = []
    for i, j in offsets:
        candidate = (xy[0]+i*spacing, xy[1]+j*spacing)
        point = Point(candidate)
        if (pocket.covers(point) and point.distance(walls) >= clearance
                and (stock.is_empty or point.distance(stock) >= clearance)):
            accepted.append(candidate)
            if len(accepted) == limit:
                break
    return tuple((point, heading) for point in accepted
                 for heading in ((1., 0.), (0., 1.), (-1., 0.), (0., -1.)))
