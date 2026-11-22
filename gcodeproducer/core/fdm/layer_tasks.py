"""Per-layer work of the FDM stages as module-level functions.

They run in worker processes (see :mod:`layer_threads`), so they take all
their settings as arguments and return plain data instead of changing the
job: the stage applies the results in layer order.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import shapely
from shapely.geometry import Polygon

import gcodeproducer.core.geometry.infill as infill_gen
from gcodeproducer.core.fdm.bridges import bridge_fill, exclude_bridges
from gcodeproducer.core.fdm.fdm_constants import GAP_CLIPPED_FEATURES
from gcodeproducer.core.fdm.gap_fill import clip_segments, gap_beads, gap_regions, infill_area, small_islands
from gcodeproducer.core.fdm.variable_walls import variable_wall_levels
from gcodeproducer.core.fdm.wall_regions import region_rings, slice_region, wall_levels


def wall_task(cfg, contours):
    """Wall beads of one layer: ``(levels of (points, widths, closed), innermost centre rings)``."""
    if cfg["variable"]:
        return variable_wall_levels(slice_region(contours), cfg["width"], cfg["count"], cfg["min_width"],
                                    cfg["max_width"])
    levels, inner = wall_levels(contours, cfg["width"], cfg["count"])
    return [[(loop, None, True) for loop in level] for level in levels], inner


def infill_task(cfg, layer):
    """Sparse lines, trimmed solid lines and gap-fill / small-island beads of one layer.

    Returns None for an empty layer, else ``(segments, solid paths or None, [(feature, bead)])``;
    the solid paths replace the layer's two-point solid lines when not None.
    """
    regions = [np.asarray(c, float) for c in layer.contours if len(c) >= 3]
    if not regions:
        return None
    min_length = cfg["min_length"]
    segs_all = []
    if cfg["density"] > 0:
        block = layer.solid_mask            # RegionMask of solid cells, or None
        # scan the inset region itself: no line can then run along a wall
        inner = list(region_rings(slice_region(layer.contours).buffer(-cfg["inset"])))
        for phi, period, off in infill_gen.pattern_families(cfg["pattern"], layer.index, layer.z,
                                                            cfg["spacing"], cfg["angle"]):
            s = infill_gen.scan_fill(inner, phi, period, off, 0., min_length)
            if block is not None and len(s):
                s = infill_gen.split_by_raster(s, block, min_length)
            s = exclude_bridges(s, layer.bridge_region, min_length)
            if len(s):
                segs_all.append(s)
    segs = np.concatenate(segs_all) if segs_all else np.zeros((0, 2, 2))
    solid, beads = None, []
    if cfg["gap_width"] > 0 or cfg["island_area"] > 0:
        segs, solid, beads = gap_fill_layer(layer, segs, cfg["wall_width"], cfg["width"], cfg["gap_width"],
                                            (cfg["min_width"], cfg["max_width"]), cfg["gap_overlap"],
                                            min_length, cfg["island_area"])
    if len(segs) and cfg["connect"]:
        segs = infill_gen.order_segments(segs, start=(0.0, 0.0))
    return segs, solid, beads


def gap_fill_layer(layer, segs, wall_lw, lw, gap_width, bead_range, overlap, min_length, island_area=0.):
    """Gap-fill / small-island beads, the fill segments outside them and the trimmed solid lines.

    Returns ``(segs, solid paths or None, [(feature, bead), ...])``; reads the layer but does
    not change it. ``gap_width`` 0 skips thin gaps; ``island_area`` > 0 fills every layer
    island (outline piece) smaller than that many mm² completely with concentric perimeters.
    """
    area = infill_area(layer.contours, wall_lw)
    if area.is_empty:
        return segs, None, []
    gaps = gap_regions(area, gap_width, lw, blocked=layer.bridge_region) if gap_width > 0 else Polygon()
    if island_area > 0:
        islands, pieces = small_islands(layer.outline, area, island_area)
    else:
        islands, pieces = Polygon(), Polygon()
    if not islands.is_empty:
        gaps = gaps.difference(islands)
    # fill lines must stay off the beads, which grow by the overlap into the walls,
    # and off the whole small island (its walls included)
    clip = shapely.union_all([gaps.buffer(overlap) if overlap > 0 else gaps, pieces])
    if clip.is_empty:
        return segs, None, []
    trimmed = None
    solid = [p for p in layer.paths if p.feature in GAP_CLIPPED_FEATURES and len(p.points) == 2]
    if solid:
        trimmed = [replace(path, points=part) for path in solid
                   for part in clip_segments(np.asarray([path.points], float), clip, min_length)]
    beads = [("gap_fill", b) for b in gap_beads(gaps, area, lw, *bead_range, overlap)]
    beads += [("solid_infill", b) for b in gap_beads(islands, area, lw, *bead_range, overlap)]
    return clip_segments(segs, clip, min_length), trimmed, beads


def top_bottom_task(cfg, task):
    """Bridges and top / bottom solid lines of one layer.

    Returns ``(bridge segments, bridge region or None, top segments, bottom segments)``;
    ``task`` carries the layer contours, the layer below's outline (None = no bridging),
    support material below and the top / bottom cell grids on ``cfg["base"]``.
    """
    lw = cfg["width"]
    bridges, region = [], None
    if task.supported is not None:
        segments, region = bridge_fill(slice_region(task.contours), slice_region(task.supported), lw,
                                       cfg["growth"], cfg["bridge_min"], task.support_material)
        bridges = list(infill_gen.order_segments(np.asarray(segments)))
    top = _solid_lines(task, task.top, region, cfg)
    bottom = _solid_lines(task, task.bottom, region, cfg)
    return bridges, region, top, bottom


def _solid_lines(task, cell_grid, bridge_region, cfg):
    if not cell_grid.any():
        return []
    if not any(len(c) >= 3 for c in task.contours):
        return []
    min_length = cfg["min_length"]
    # keep solid lines only where this surface mask is set: block the rest
    block = cfg["base"].like(~cell_grid)
    # scan the inset region itself: no line can then run along a wall
    inner = list(region_rings(slice_region(task.contours).buffer(-cfg["inset"])))
    out = []
    for phi, period, off in infill_gen.pattern_families(cfg["pattern"], task.index, task.z, cfg["width"],
                                                        cfg["angle"]):
        segs = infill_gen.scan_fill(inner, phi, period, off, 0., min_length)
        if not len(segs):
            continue
        segs = infill_gen.split_by_raster(segs, block, min_length)
        segs = exclude_bridges(segs, bridge_region, min_length)
        if not len(segs):
            continue
        out.extend(infill_gen.order_segments(segs, start=(0.0, 0.0)))
    return out
