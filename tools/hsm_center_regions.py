"""Offline connectivity map for a planar cutter-center domain."""
import math
from typing import NamedTuple

from shapely import get_parts
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

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


def cleared_start_intervals(pocket, stock, start, end, radius, *, margin=0.):
    """Clip a straight guide to live clearance and return verified intervals in guide order.

    Rounded buffer approximations propose intervals; a full-segment distance
    check rejects any that cannot carry the complete cutter disk. These are
    candidate start zones, not a route to them from the current pose.
    """
    regions = center_regions(pocket, radius, margin=margin)
    guide = LineString((start, end))
    if not guide.length:
        return ()
    required = radius + margin
    # Pad the exclusion radius for the inscribed chords of round buffers.
    padded = required / math.cos(math.pi / (4 * CENTER_BUFFER_SEGMENTS))
    excluded = stock.buffer(padded, quad_segs=CENTER_BUFFER_SEGMENTS)
    walls = pocket.boundary
    intervals = []
    for region in regions:
        for part in get_parts(guide.intersection(region.difference(excluded))):
            if (part.geom_type != 'LineString' or not part.length or not pocket.covers(part)
                    or part.distance(walls) < required
                    or (not stock.is_empty and part.distance(stock) < required)):
                continue
            a, b = sorted((guide.project(Point(part.coords[i])) for i in (0, -1)))
            if b > a:
                intervals.append((a, b))
    return tuple(sorted(intervals))


def nearby_frontier(pocket, stock, xy, radius, *, extra_reach):
    """Map stock edges near the pose's connected planar clearance component.

    This is a geometric neighborhood, not a verified link or cutting plan.
    """
    if not math.isfinite(extra_reach) or extra_reach < 0:
        raise ValueError('expected nonnegative extra reach')
    point = Point(xy)
    regions = center_regions(pocket, radius)
    if (not pocket.covers(point) or point.distance(pocket.boundary) < radius
            or (not stock.is_empty and point.distance(stock) < radius)):
        return LineString()
    excluded = stock.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS)
    components = [part for region in regions for part in polygons(region.difference(excluded))
                  if part.covers(point)]
    if len(components) != 1:
        return LineString()
    exposed = stock.intersection(pocket).boundary.difference(pocket.boundary)
    neighborhood = components[0].buffer(radius + extra_reach, quad_segs=CENTER_BUFFER_SEGMENTS)
    return exposed.intersection(neighborhood)


def region_at(regions, xy):
    """Return the component index for a uniquely assigned seed, else None."""
    point = Point(xy)
    hits = [index for index, region in enumerate(regions) if region.covers(point)]
    return hits[0] if len(hits) == 1 else None


class RegionWork(NamedTuple):
    centers: Polygon
    stock: BaseGeometry
    seeds: tuple

    @property
    def needs_entry(self):
        return self.stock.area > 0 and not self.seeds


def map_region_work(pocket, stock, radius, seeds=(), *, margin=0.):
    """Report live stock accessible from each center region and verified seed poses.

    Stock at the edge of a region may also be accessible from another; union
    the reported targets for totals, and recompute after cuts. A seed only
    establishes its own clearance, not a stay-down route to the stock. An
    unseeded region with work needs an entry or a newly verified cleared seed.
    """
    regions = center_regions(pocket, radius, margin=margin)
    assigned = [[] for _ in regions]
    for xy in seeds:
        xy = tuple(xy)
        index = region_at(regions, xy)
        if index is None:
            continue
        point = Point(xy)
        clearance = radius + margin
        if (point.distance(pocket.boundary) >= clearance
                and (stock.is_empty or point.distance(stock) >= clearance)):
            assigned[index].append(xy)
    return tuple(RegionWork(region, stock.intersection(region.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS)),
                            tuple(assigned[index])) for index, region in enumerate(regions))
