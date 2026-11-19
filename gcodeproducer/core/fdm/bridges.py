"""Rectilinear fill for unsupported patches of an FDM layer."""
import numpy as np
from shapely import box, covers, length, intersection, linestrings, points, prepare, union_all

from gcodeproducer.core.fdm.fdm_constants import BRIDGE_ANGLES
from gcodeproducer.core.fdm.wall_regions import _rings
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.geometry.infill import scan_fill


def support_footprint(base, mask):
    """Convert runs of nominal support cells to a continuous XY footprint."""
    edges = np.diff(mask.astype(np.int8), axis=1, prepend=0, append=0)
    rows, start = np.where(edges == 1)
    _, end = np.where(edges == -1)
    x, y = base.lo
    res = base.res
    return union_all(box(x+start*res, y+rows*res, x+end*res, y+(rows+1)*res))


def bridge_fill(fill, supported, width, growth, min_area, support_material=None):
    """Generate bridge lines for unsupported fill, preferring backed endpoints."""
    if support_material is not None:
        # Growth can extend into model material, but not over generated support.
        fill = fill.difference(support_material)
    if fill.is_empty:
        return [], None
    anchors = supported.buffer(1e-7)
    prepare(anchors)
    paths, sweeps = [], []
    for patch in polygons(fill.difference(supported)):
        if patch.area < min_area:
            continue
        region = patch.buffer(growth).intersection(fill) if growth else patch
        if sweeps:
            region = region.difference(union_all(sweeps))
        rings = list(_rings(region))
        best, score = None, (0, 0., 0.)
        for phi in BRIDGE_ANGLES:
            segs = scan_fill(rings, phi, width, width/2, 0.)
            if not len(segs):
                continue
            spans = length(intersection(linestrings(segs), patch))
            keep = spans > 1e-7
            if not keep.any():
                continue
            spans, segs = spans[keep], segs[keep]
            ends = covers(anchors, points(segs.reshape(-1, 2))).reshape(-1, 2)
            # Prefer good coverage, then backed endpoints and shorter spans.
            # Quantize coverage to avoid choosing a diagonal due to scan phase.
            rank = (max(1, round(20*width*float(spans.sum())/patch.area)),
                    float(ends.mean()), -float(spans.max()))
            if rank > score:
                best, score = segs, rank
        if best is not None:
            paths.extend(best)
            sweeps.append(union_all([line.buffer(width/2, cap_style=1) for line in linestrings(best)]))
    return paths, union_all(sweeps) if sweeps else None


def exclude_bridges(segs, region, minimum):
    if region is None or not len(segs):
        return segs
    out = []
    for original, line in zip(segs, linestrings(segs)):
        if not region.intersects(line):
            out.append(original)
            continue
        remainder = line.difference(region)
        for part in getattr(remainder, 'geoms', (remainder,)):
            if part.geom_type == 'LineString' and part.length > minimum:
                out.append(np.array([part.coords[0], part.coords[-1]]))
    return np.asarray(out, float).reshape(-1, 2, 2)
