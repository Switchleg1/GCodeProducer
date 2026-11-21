"""Fill thin gaps between perimeters with extra variable-width perimeters."""
from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import Polygon

from gcodeproducer.core.fdm.bridges import exclude_bridges
from gcodeproducer.core.fdm.fdm_constants import GAP_FILL_MAX_LOOPS, GAP_FILL_MIN_AREA, GAP_FILL_MITRE_LIMIT
from gcodeproducer.core.fdm.variable_walls import variable_wall_levels
from gcodeproducer.core.fdm.wall_regions import slice_region
from gcodeproducer.core.geometry.polygon_parts import polygons


def infill_area(contours, wall_width):
    """Material inside the innermost wall bead (``contours`` are its centre lines)."""
    region = slice_region(contours)
    return region.buffer(-wall_width * .5) if not region.is_empty else region


def gap_regions(area, max_gap, width, blocked=None):
    """Parts of ``area`` narrower than ``max_gap``: thin gaps between perimeters.

    The area minus its opening at half the gap width. Mitre regrowth keeps
    ordinary convex corners, so the crumbs there are not counted as gaps.
    """
    if area.is_empty:
        return Polygon()
    minimum = GAP_FILL_MIN_AREA * width**2
    radius = max_gap * .5
    opened = area.buffer(-radius).buffer(radius, join_style="mitre", mitre_limit=GAP_FILL_MITRE_LIMIT)
    pieces = [p for p in polygons(area.difference(opened)) if p.area >= minimum]
    if not pieces:
        return Polygon()
    gaps = shapely.union_all(pieces)
    if blocked is not None and not blocked.is_empty:
        gaps = gaps.difference(blocked)
    return gaps


def small_islands(outline, area, max_area):
    """``(fill area, whole islands)`` for the layer islands (outline pieces) under ``max_area`` mm²."""
    pieces = [p for p in polygons(slice_region(outline)) if p.area < max_area]
    if not pieces:
        return Polygon(), Polygon()
    pieces = shapely.multipolygons(pieces)
    return area.intersection(pieces), pieces


def gap_beads(gaps, area, width, min_width, max_width, overlap):
    """Variable-width beads tiling ``gaps`` grown by ``overlap`` mm into the walls."""
    if gaps.is_empty:
        return []
    grown = gaps.buffer(overlap).intersection(area.buffer(overlap)) if overlap > 0 else gaps
    pieces = [p for p in polygons(grown) if p.area >= GAP_FILL_MIN_AREA * width**2]
    if not pieces:
        return []
    beads = []
    for level in variable_wall_levels(shapely.union_all(pieces), width, GAP_FILL_MAX_LOOPS, min_width,
                                      max_width, keep_loops=False)[0]:
        beads.extend(level)
    return beads


def clip_segments(segs, gaps, min_length):
    """Remove the parts of fill segments that lie inside the gap-filled region."""
    if gaps is None or gaps.is_empty:
        return segs
    return exclude_bridges(segs, gaps, min_length)
