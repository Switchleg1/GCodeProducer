"""Offline proposals for tangent returns through already cleared planar stock."""
import math

from shapely.geometry import LineString


def tangent_chords(start, end, outgoing, incoming, handle, subdivisions=128):
    """Sample a cubic whose endpoint tangents follow the two headings."""
    if not math.isfinite(handle) or handle <= 0 or start == end or subdivisions < 2:
        raise ValueError('tangent link requires distinct endpoints, a positive handle and subdivisions')

    def scaled(heading):
        length = math.hypot(*heading)
        if length <= 0 or not math.isfinite(length):
            raise ValueError('tangent link requires finite nonzero headings')
        return tuple(value / length * handle for value in heading)

    a, b = scaled(outgoing), scaled(incoming)
    controls = (start, tuple(x+d for x, d in zip(start, a)), tuple(x-d for x, d in zip(end, b)), end)
    points = []
    for i in range(subdivisions+1):
        t = i/subdivisions
        u = 1-t
        weights = (u**3, 3*u*u*t, 3*u*t*t, t**3)
        points.append(tuple(sum(weight * xy[axis] for weight, xy in zip(weights, controls))
                            for axis in range(2)))
    return points


def cleared_tangent_link(pocket, stock, radius, start, end, outgoing, incoming, handle, *, margin=0.):
    """Return a chord-chain proposal, or None if any swept disk would penetrate.

    Distances are from the complete chord chain, not just sampled endpoints.
    Boundary tangency is allowed at zero margin. No holder or Z model here.
    """
    if not math.isfinite(radius) or not math.isfinite(margin) or radius <= 0 or margin < 0:
        raise ValueError('expected a positive cutter radius and nonnegative clearance margin')
    points = tangent_chords(start, end, outgoing, incoming, handle)
    axis = LineString(points)
    required = radius + margin
    if not pocket.covers(axis) or axis.distance(pocket.boundary) < required:
        return None
    if not stock.is_empty and axis.distance(stock) < required:
        return None
    return points
