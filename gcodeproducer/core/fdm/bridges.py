"""Anchored rectilinear fill for unsupported patches of an FDM layer."""
import numpy as np
from shapely import covers, length, intersection, linestrings, points, prepare, union_all
from shapely.geometry import LineString

from gcodeproducer.core.fdm.fdm_constants import BRIDGE_ANGLES
from gcodeproducer.core.fdm.wall_regions import _rings, slice_region
from gcodeproducer.core.geometry.polygon_parts import polygons
from gcodeproducer.core.geometry.infill import scan_fill


def backing_region(layer, width):
    """Previous-layer model footprint plus nominal printed support beads."""
    outline = slice_region(layer.outline)
    support = [LineString(path.points).buffer((path.width or width)/2)
               for path in layer.paths if path.feature in ('support', 'support_interface') and len(path.points) >= 2]
    return union_all([outline, *support]) if support else outline


def bridge_fill(fill, supported, width, growth, min_area):
    """Return anchored segments and their coverage, within the current fill region."""
    if fill.is_empty or supported.is_empty:
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
        best, score = None, (0, 0.)
        for phi in BRIDGE_ANGLES:
            segs = scan_fill(rings, phi, width, width/2, 0.)
            if not len(segs):
                continue
            anchored = covers(anchors, points(segs[:, 0])) & covers(anchors, points(segs[:, 1]))
            segs = segs[anchored]
            if not len(segs):
                continue
            spans = length(intersection(linestrings(segs), patch))
            keep = spans > 1e-7
            if not keep.any():
                continue
            spans = spans[keep]
            # Prefer good coverage, then shorter unsupported spans. Quantize
            # coverage to avoid picking a diagonal just due to scan phase.
            rank = (max(1, round(20*width*float(spans.sum())/patch.area)), -float(spans.max()))
            if rank > score:
                best, score = segs[keep], rank
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
