"""Inset the complete slice, including holes, for FDM wall centre lines."""
import numpy as np
from shapely import make_valid
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


def polygons(shape):
    if shape.geom_type == 'Polygon':
        if not shape.is_empty:
            yield shape
    elif hasattr(shape, 'geoms'):
        for child in shape.geoms:
            yield from polygons(child)


def slice_region(contours):
    """Apply the same even-odd rule as the slicer's infill mask."""
    region = Polygon()
    for ring in contours:
        if len(ring) >= 3:
            part = Polygon(ring)
            for piece in polygons(part if part.is_valid else make_valid(part)):
                region = region.symmetric_difference(piece)
    return region


def _rings(region):
    for poly in polygons(region):
        poly = orient(poly, sign=1.)
        for ring in (poly.exterior, *poly.interiors):
            yield np.asarray(ring.coords)[:-1].copy()


def wall_levels(contours, width, count):
    """Outer-first wall levels plus the remaining region for infill.

    Buffering the filled region together lets an inset split at a thin neck,
    merge holes, or vanish instead of extruding a self-crossing loop. The
    last inset is also the existing infill reference (measured to its centre
    line); never fall back to a shallower inset where the deepest one vanished.
    """
    if not count:
        return [], contours
    region = slice_region(contours)
    levels = []
    for k in range(count):
        inset = region.buffer(-width*(k+.5), quad_segs=8)
        levels.append(list(_rings(inset)))
        if inset.is_empty:
            break
    return levels, levels[-1]
