"""Variable-width FDM beads for walls that narrow below two line widths.

Fixed-width offsetting has two failure modes on tapering features (fan blade
tips, gear teeth, stepped walls):

* where the material is narrower than ``2 * width`` the inset loop folds back
  on itself, so its two sides overlap and over-extrude;
* where it is narrower than ``width`` no loop exists at all and the tip is
  left empty.

With ``D`` the local material width, walls (``keep_loops``) keep exactly the
fixed-width loops and only change their flow:

* ``width <= D < 2 * width``: the folded loop's vertices are thinned to
  ``D / 2`` (at least ``min_width``), so its two sides do not overlap;
* ``D < width``, where no loop reaches: an open centre-line bead of width
  ``D`` follows the medial axis, tapering down to ``min_width``.

Gap fill (``keep_loops=False``) has no original lines to keep, so it may
replace the loop by one centre bead wherever ``D < max_width`` and moves
thinned loop sides out to tile the gap.
"""
from __future__ import annotations

import numpy as np
import shapely

from gcodeproducer.core.fdm.fdm_constants import (VARIABLE_DENSIFY, VARIABLE_MIN_AREA, VARIABLE_MIN_LENGTH,
                                                   VARIABLE_MITRE_LIMIT, VARIABLE_PRUNE, VARIABLE_PRUNE_RADII, VARIABLE_RAY_START,
                                                   VARIABLE_SCRAP_LOOP, VARIABLE_SCRAP_MIN_SPAN,
                                                   VARIABLE_SAMPLE_STEP, VARIABLE_THIN_MIN_AREA, VARIABLE_LOOP_MIN_AREA,
                                                   VARIABLE_THIN_REACH)
from gcodeproducer.core.fdm.wall_regions import region_rings
from gcodeproducer.core.geometry.medial_axis import chain_edges, medial_edges
from gcodeproducer.core.geometry.polygon_parts import polygons


def _narrow_parts(material, width, eroded=None):
    """Parts of ``material`` narrower than ``2 * width`` (plus convex-corner crumbs), or None.

    ``eroded`` is ``material`` already shrunk by ``width`` (the next wall level's material).
    """
    if eroded is None:
        eroded = material.buffer(-width, quad_segs=8)
    opened = eroded.buffer(width, quad_segs=8)
    narrow = [p for p in polygons(material.difference(opened)) if p.area > VARIABLE_MIN_AREA * width**2]
    if not narrow:
        return None
    narrow = shapely.multipolygons(narrow)
    shapely.prepare(narrow)
    return narrow


def _thin_beads(material, covered, width, min_width, max_width, reach=2., narrow=None):
    """Open centre-line beads where no loop reaches; ``reach`` limits them to material below
    ``reach * width`` wide.

    ``narrow`` (the parts of ``material`` under two widths) may be given when
    every uncovered part lies inside it, which keeps the Boolean small.
    """
    thin = (narrow if narrow is not None else material).difference(covered)
    pieces = [p for p in polygons(thin) if p.area > VARIABLE_THIN_MIN_AREA * width**2]
    if not pieces:
        return []
    edges, radii = medial_edges(material, shapely.multipolygons(pieces), width * VARIABLE_SAMPLE_STEP,
                                2 * width, width * VARIABLE_THIN_REACH)
    if not len(edges):
        return []
    # Up to two widths: material a little over the maximum can lose its loop
    # (the opening breaks it up); a capped centre bead is better than nothing.
    keep = (radii.min(axis=1) * 2 >= min_width) & (radii.max(axis=1) * 2 <= width * reach * 1.02)
    if not keep.any():
        return []
    edges, radii = edges[keep], radii[keep]
    beads = []
    for pts, r in chain_edges(edges, radii, VARIABLE_PRUNE * width, VARIABLE_PRUNE_RADII):
        if len(pts) < 2 or np.hypot(*np.diff(pts, axis=0).T).sum() < VARIABLE_MIN_LENGTH * width:
            continue
        beads.append((pts, np.clip(2 * r, min_width, max_width), False))
    return beads


def _ring_normals(pts):
    """Unit vertex normals pointing away from the region a centre ring encloses.

    ``region_rings`` orients exteriors counter-clockwise and holes clockwise,
    so the right-hand normal always points away from the centre region,
    towards the material edge this side of the loop follows.
    """
    edge = np.roll(pts, -1, axis=0) - pts
    length = np.hypot(*edge.T)
    edge /= np.maximum(length, 1e-12)[:, None]
    right = np.stack((edge[:, 1], -edge[:, 0]), axis=1)
    normal = right + np.roll(right, 1, axis=0)
    norm = np.hypot(*normal.T)
    normal[norm > 1e-9] /= norm[norm > 1e-9, None]
    normal[norm <= 1e-9] = right[norm <= 1e-9]
    return normal


def _material_widths(pts, normal, boundary, width):
    """Distances along each normal to the near edge (outward) and the far edge (inward).

    Rays are intersected with the boundary's individual segments found through
    an STRtree, so a long, detailed boundary costs no more than the segments
    each ray actually passes.
    """
    reach = 2 * width
    near = np.full(len(pts), np.inf)
    far = np.full(len(pts), np.inf)
    lines = [np.asarray(g.coords) for g in shapely.get_parts(boundary) if not g.is_empty]
    if not lines:
        return near, far
    seg_a = np.concatenate([c[:-1, :2] for c in lines])
    seg_b = np.concatenate([c[1:, :2] for c in lines])
    tree = shapely.STRtree(shapely.linestrings(np.stack((seg_a, seg_b), axis=1)))
    start = pts - normal * reach
    rays = shapely.linestrings(np.stack((start, pts + normal * reach), axis=1))
    ray, seg = tree.query(rays, predicate="intersects")
    if not len(ray):
        return near, far
    # ray: start + s * (2 reach) * normal ; segment: a + u * (b - a)
    d = normal[ray] * (2 * reach)
    e = seg_b[seg] - seg_a[seg]
    w = seg_a[seg] - start[ray]
    denom = d[:, 0] * e[:, 1] - d[:, 1] * e[:, 0]
    ok = np.abs(denom) > 1e-12
    s_par = np.where(ok, (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / np.where(ok, denom, 1.), np.nan)
    t = s_par * 2 * reach - reach                       # signed distance from the point along the normal
    out = ok & (t > VARIABLE_RAY_START)
    np.minimum.at(near, ray[out], t[out])
    back = ok & (t < -VARIABLE_RAY_START)
    np.minimum.at(far, ray[back], -t[back])
    return near, far


def _densify(ring, step):
    """Closed ring with extra vertices every ``step``; also flags the original vertices."""
    nxt = np.roll(ring, -1, axis=0)
    count = np.maximum(1, np.ceil(np.hypot(*(nxt - ring).T) / step).astype(int))
    t = np.concatenate([np.arange(c) / c for c in count])
    start = np.repeat(np.arange(len(ring)), count)
    pts = ring[start] + (nxt[start] - ring[start]) * t[:, None]
    return pts, t == 0


def _thinned_loop(ring, narrow, material, width, min_width, max_width, move=True):
    """Loop points and widths; folded stretches get half the local material width.

    A loop folds where the material across it (``D``, measured along the loop
    normal) is narrower than two widths, so its two sides overlap. Each folded
    vertex gets width ``D / 2`` and moves along its normal to ``D / 4`` from its
    edge, so the two sides tile the material. Measuring along the loop's own
    normal keeps neighbouring vertices consistent at corners and stroke ends.
    """
    pts, original = _densify(np.asarray(ring, float)[:, :2], width * VARIABLE_DENSIFY)
    candidate = np.flatnonzero(shapely.contains_xy(narrow, pts[:, 0], pts[:, 1]))
    if not len(candidate):
        return ring, None
    normal = _ring_normals(pts)[candidate]
    x0, y0 = pts[candidate].min(axis=0) - 2 * width
    x1, y1 = pts[candidate].max(axis=0) + 2 * width
    boundary = shapely.clip_by_rect(material.boundary, x0, y0, x1, y1)
    near, far = _material_widths(pts[candidate], normal, boundary, width)
    across = near + far
    folded = across < 2 * width
    if not folded.any():
        return ring, None
    idx = candidate[folded]
    if not move:                         # walls: same path, flow follows the material
        widths = np.full(len(pts), float(width))
        widths[idx] = np.clip(across[folded] * .5, min_width, width)
        # extra vertices only matter where the width changes
        keep = original.copy()
        changed = np.flatnonzero(widths != width)
        for shift in (-1, 0, 1):
            keep[(changed + shift) % len(pts)] = True
        return pts[keep], widths[keep]
    half = np.clip(across[folded] * .5, max(max_width * .5, min_width), width)
    widths = np.full(len(pts), float(width))
    widths[idx] = half
    pts = pts.copy()
    pts[idx] += normal[folded] * (near[folded] - half * .5)[:, None]
    return pts, widths


def _loop_centres(material, width, max_width):
    """Centre-line region of a level's loop, kept out of material narrower than ``max_width``."""
    if max_width <= width * (1 + 1e-6):
        return material.buffer(-width * .5, quad_segs=8)
    shrunk = material.buffer(-max_width * .5, quad_segs=8)
    if shrunk.is_empty:
        return shrunk
    centres = shrunk.buffer((max_width - width) * .5, join_style="mitre", mitre_limit=VARIABLE_MITRE_LIMIT)
    # Where the width hovers around the maximum the opening leaves scraps of
    # loop; a tiny loop between centre beads only breaks the line up.
    parts = list(polygons(centres))
    kept = [p for p in parts if p.area >= VARIABLE_LOOP_MIN_AREA * width**2]
    if len(kept) == len(parts):
        return centres
    return shapely.multipolygons(kept) if kept else shapely.Polygon()


def variable_wall_levels(region, width, count, min_width, max_width=None, keep_loops=True):
    """Outer-first lists of ``(points, widths or None, closed)`` beads plus the innermost centre rings.

    With ``keep_loops`` the loops are exactly those of :func:`wall_levels`; only
    their flow changes, and tips no loop reaches get extra centre beads.
    """
    max_width = width if max_width is None else max(width, min(max_width, 2 * width))
    levels = []
    last_rings = []
    material = region
    for k in range(count):
        if material.is_empty:
            break
        eroded = region.buffer(-width * (k + 1), quad_segs=8)       # also the next level's material
        narrow = _narrow_parts(material, width, eroded)
        if narrow is None or keep_loops:
            inset = region.buffer(-width * (k + .5), quad_segs=8)
        else:
            inset = _loop_centres(material, width, max_width)
        rings = list(region_rings(inset))
        if narrow is None:
            beads = [(ring, None, True) for ring in rings]
        else:
            beads = []
            # loop vertices within half a width of the narrow parts
            near_narrow = narrow.buffer(width * .5, quad_segs=4)
            shapely.prepare(near_narrow)
            for ring in rings:
                if shapely.intersects(near_narrow, shapely.linearrings(ring)):
                    pts, widths = _thinned_loop(ring, near_narrow, material, width, min_width, max_width,
                                                move=not keep_loops)
                else:
                    pts, widths = ring, None
                beads.append((pts, widths, True))
            covered = inset.buffer(width * .5, quad_segs=8)
            # with the fixed loops nothing wider than one width is left uncovered,
            # and all of that lies in the narrow parts
            beads.extend(_thin_beads(material, covered, width, min_width, max_width,
                                     reach=1. if keep_loops else 2., narrow=narrow if keep_loops else None))
        if keep_loops:
            beads = [_scrap_to_bead(b, width, min_width, max_width) for b in beads]
        levels.append(beads)
        last_rings = rings
        if inset.is_empty:
            break
        material = eroded
    return levels, last_rings


def _scrap_to_bead(bead, width, min_width, max_width):
    """A wall loop around a tiny scrap of centre region becomes one straight bead.

    Where the material is only a little over two line widths across, the
    inset leaves slivers whose loop is shorter than a few line widths: two
    half-width passes over the same spot, each needing its own travel. One
    bead along the sliver, as wide as the loop's coverage, prints the same
    material in one stroke.
    """
    pts, widths, closed = bead
    if not closed:
        return bead
    pts = np.asarray(pts, float)[:, :2]
    ring = np.vstack((pts, pts[:1]))
    length = float(np.hypot(*np.diff(ring, axis=0).T).sum())
    if length >= VARIABLE_SCRAP_LOOP * width or len(pts) < 2:
        return bead
    d = ((pts[:, None, :] - pts[None, :, :])**2).sum(-1)
    i, j = np.unravel_index(int(d.argmax()), d.shape)
    span = float(np.sqrt(d[i, j]))
    x, y = pts[:, 0], pts[:, 1]
    area = .5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
    thickness = area / span if span > 1e-9 else 0.
    w = float(np.clip(width + thickness, min_width, max_width))
    a, b = pts[i], pts[j]
    if span < VARIABLE_SCRAP_MIN_SPAN:
        centre = pts.mean(axis=0)
        a, b = centre - [VARIABLE_SCRAP_MIN_SPAN / 2, 0.], centre + [VARIABLE_SCRAP_MIN_SPAN / 2, 0.]
    return np.array([a, b]), np.array([w, w]), False
