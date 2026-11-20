"""Offline connectivity map for a planar cutter-center domain."""
import math

from shapely.geometry import Point

from gcodeproducer.core.geometry.polygon_parts import polygons


CENTER_BUFFER_SEGMENTS = 64


def center_regions(pocket, radius, *, margin=0.):
    """Return positive-area center components in reproducible spatial order.

    The model deliberately excludes zero-width connections. These components
    describe geometric access only, not a cleared route through live stock.
    """
    if not math.isfinite(radius) or radius <= 0 or not math.isfinite(margin) or margin < 0:
        raise ValueError('expected a positive radius and nonnegative margin')
    if pocket.geom_type not in {'Polygon', 'MultiPolygon'} or not pocket.is_valid:
        raise ValueError('expected valid planar pocket polygons')
    centers = pocket.buffer(-(radius + margin), quad_segs=CENTER_BUFFER_SEGMENTS)
    return tuple(sorted((p for p in polygons(centers) if p.area > 0), key=lambda p: p.bounds))


def region_at(regions, xy):
    """Return the component index for a uniquely assigned seed, else None."""
    point = Point(xy)
    hits = [index for index, region in enumerate(regions) if region.covers(point)]
    return hits[0] if len(hits) == 1 else None
