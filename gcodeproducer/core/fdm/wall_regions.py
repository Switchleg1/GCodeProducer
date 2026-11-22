"""Inset the complete slice, including holes, for FDM wall centre lines."""
import numpy as np
import shapely
from shapely import make_valid
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from gcodeproducer.core.geometry.polygon_parts import polygons


def slice_region(contours):
    """Apply the same even-odd rule as the slicer's infill mask."""
    rings = [np.asarray(ring, float)[:, :2] for ring in contours if len(ring) >= 3]
    fast = _nested_region(rings)
    if fast is not None:
        return fast
    return _symmetric_region(rings)


def _nested_region(rings):
    """Even-odd region built directly from ring nesting, or None when rings touch or self-intersect.

    Slices of a sound mesh are disjoint simple rings, so each ring nested an even
    number of times is a shell and each odd one a hole of its innermost container.
    This avoids one Boolean operation per ring.
    """
    if not rings:
        return Polygon()
    polys = [Polygon(r) for r in rings]
    polys = np.asarray(polys, dtype=object)
    if not shapely.is_valid(polys).all():
        return None
    boundaries = shapely.boundary(polys)
    tree = shapely.STRtree(boundaries)
    a, b = tree.query(boundaries, predicate="intersects")
    if (a != b).any():
        return None
    area = shapely.area(polys)
    inside = shapely.STRtree(polys)
    point_of = shapely.points([r[0] for r in rings])
    pt, container = inside.query(point_of, predicate="within")
    keep = pt != container
    pt, container = pt[keep], container[keep]
    depth = np.bincount(pt, minlength=len(rings))
    parent = np.full(len(rings), -1)
    # innermost container = the smallest one
    order = np.argsort(-area[container], kind="stable")
    parent[pt[order]] = container[order]
    holes = {}
    for i in np.flatnonzero(depth % 2 == 1):
        holes.setdefault(int(parent[i]), []).append(rings[i])
    shells = [Polygon(rings[i], holes.get(int(i), [])) for i in np.flatnonzero(depth % 2 == 0)]
    if len(shells) == 1:
        return shells[0]
    return shapely.multipolygons(shells)


def _symmetric_region(rings):
    region = Polygon()
    for ring in rings:
        if len(ring) >= 3:
            part = Polygon(ring)
            for piece in polygons(part if part.is_valid else make_valid(part)):
                region = region.symmetric_difference(piece)
    return region


def region_rings(region):
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
        levels.append(list(region_rings(inset)))
        if inset.is_empty:
            break
    return levels, levels[-1]
