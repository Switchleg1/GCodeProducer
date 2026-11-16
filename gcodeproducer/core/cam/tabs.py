"""Model-owned holding rails from side-wall anchors to stock XY edges.

Tabs are solid stock to KEEP, not additive geometry. A tab starts at stock
bottom and ends at bottom + height. Its anchor is barycentric on an original
STL triangle, so model placement re-evaluates it instead of leaving it behind.
Planning clips cutter-centre lines by radius-expanded rectangles. These exact
rectangles also guard links/rapids independently of the display height grid.
"""
from __future__ import annotations

from gcodeproducer.core.cam.holding_tab import HoldingTab
from dataclasses import replace
import math, numpy as np
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union


def tab_bounds(mesh, stock, tab, outward_sign=None):
    """Resolved (lo, hi), or raise for unsafe/unallocated/invalid configuration."""
    if not stock.allocated:
        raise ValueError("Holding tabs need allocated material; use Auto or enter stock dimensions")
    if not (0 <= tab.triangle < len(mesh.triangles)):
        raise ValueError("Holding tab anchor no longer exists; reselect the tab")
    bary = np.asarray(tab.barycentric, float)
    if bary.shape != (3,) or not np.isfinite(bary).all() or abs(bary.sum()-1) > 1e-5 or bary.min() < -1e-5:
        raise ValueError("Invalid holding tab anchor")
    if not all(math.isfinite(v) and v > 0 for v in (tab.width, tab.height)):
        raise ValueError("Holding tab width and height must be positive and finite")
    if tab.height > stock.height+1e-6:
        raise ValueError("Holding tab height exceeds material thickness")
    tri = mesh.vertices[mesh.triangles[tab.triangle]]
    point = bary @ tri
    lo, hi = (np.array(v, float).copy() for v in stock.bounds)
    if np.any(point[:2] < lo[:2]-1e-4) or np.any(point[:2] > hi[:2]+1e-4):
        raise ValueError("Holding tab anchor lies outside the material XY bounds")
    direction = tab.direction
    if direction == "auto":
        normal = np.cross(tri[1]-tri[0], tri[2]-tri[0])
        if np.linalg.norm(normal[:2]) < 1e-8:
            raise ValueError("Place holding tabs on a side wall, not a horizontal face")
        if outward_sign is None:
            from gcodeproducer.core.geometry.kernel import signed_volume
            outward_sign = -1 if signed_volume(mesh) < 0 else 1
        normal = normal*outward_sign
        axis = int(np.argmax(np.abs(normal[:2])))
        direction = ("+" if normal[axis] >= 0 else "-") + ("x" if axis == 0 else "y")
    if direction not in ("+x", "-x", "+y", "-y"):
        raise ValueError("Unknown holding tab direction")
    axis = 0 if direction[-1] == "x" else 1
    other = 1-axis
    # Reach slightly into the part at the anchor, so the retained rail bonds to it.
    if direction[0] == "+":
        lo[axis] = max(lo[axis], point[axis]-tab.width/2)
    else:
        hi[axis] = min(hi[axis], point[axis]+tab.width/2)
    lo[other] = max(lo[other], point[other]-tab.width/2)
    hi[other] = min(hi[other], point[other]+tab.width/2)
    hi[2] = lo[2]+tab.height
    if hi[2] <= mesh.bounds[0][2]+1e-5:
        raise ValueError("Holding tab is below the part; increase its height above the stock bottom")
    if np.any(hi-lo <= 1e-8):
        raise ValueError("Holding tab has no volume inside the material")
    return lo, hi


def resolve_bounds(mesh, stock, tabs):
    enabled = [t for t in tabs if t.enabled]
    sign = 1
    if any(t.direction == "auto" for t in enabled):
        from gcodeproducer.core.geometry.kernel import signed_volume
        sign = -1 if signed_volume(mesh) < 0 else 1
    return [tab_bounds(mesh, stock, tab, sign) for tab in enabled]


def resolve_tabs(mesh, setup):
    return resolve_bounds(mesh, setup.stock, setup.tabs)


def mask_at(bounds, z, radius=0.0, padding=.002):
    """Cutter-centre exclusion at a tip Z. Below the tab bottom is excluded too:
    the cylindrical cutter extends above its tip and would still cut the tab.
    Padding covers circular-buffer chords and G-code rounding, not a user allowance.
    """
    r = (radius+padding)/math.cos(math.pi/64) if radius > 0 else 0.0
    polygons = [box(lo[0], lo[1], hi[0], hi[1]).buffer(r, quad_segs=16) if r else
                box(lo[0], lo[1], hi[0], hi[1]) for lo, hi in bounds if z < hi[2]-1e-6]
    return unary_union(polygons)


def contact(bounds, a, b, radius):
    """Conservative full-cylinder tab contact, including diagonal XYZ travel."""
    mask = mask_at(bounds, min(a[2], b[2]), radius, padding=0.0)
    if mask.is_empty:
        return False
    segment = Point(a[:2]) if np.linalg.norm(np.asarray(a[:2])-b[:2]) < 1e-10 else LineString((a[:2], b[:2]))
    return mask.intersects(segment)


def top_along(bounds, a, b, radius, default):
    if not bounds:
        return default
    segment = Point(a[:2]) if np.linalg.norm(np.asarray(a[:2])-b[:2]) < 1e-10 else LineString((a[:2], b[:2]))
    return max([default] + [hi[2] for lo, hi in bounds
                           if box(lo[0], lo[1], hi[0], hi[1]).buffer(radius+.002).intersects(segment)])


def clip_paths(paths, mask):
    """Split cut contours at tab exclusion boundaries, preserving traversal order.

    Seam fragments of a closed contour are rejoined; only real tab interruptions
    create open paths. Every new path owns fresh engagement/link metadata.
    """
    result = []
    for path in paths:
        p = np.asarray(path.points)[:, :2]
        if len(p) == 1:
            if not mask.covers(Point(p[0])):
                result.append(replace(path, stay_down=False, stay_down_from=None,
                                      cut_conditions=[], link_condition=None))
            continue
        line = LineString(np.vstack((p, p[0])) if path.closed else p)
        if not line.intersects(mask):
            linked = path.stay_down and path.stay_down_from is not None
            if linked:
                link = LineString((path.stay_down_from, p[0]))
                linked = not link.intersects(mask)
            result.append(replace(path, stay_down=bool(linked),
                                  stay_down_from=path.stay_down_from if linked else None,
                                  cut_conditions=[], link_condition=None))
            continue
        clipped = line.difference(mask)
        parts = [clipped] if clipped.geom_type == "LineString" else list(getattr(clipped, "geoms", ()))
        chunks = [np.asarray(part.coords) for part in parts if part.geom_type == "LineString" and part.length > .002]
        chunks.sort(key=lambda q: line.project(Point(q[0])))
        if path.closed and len(chunks) > 1 and np.allclose(chunks[-1][-1], chunks[0][0], atol=1e-7, rtol=0):
            chunks = [np.vstack((chunks[-1][:-1], chunks[0]))] + chunks[1:-1]
        for q in chunks:
            closed = bool(path.closed and np.allclose(q[0], q[-1], atol=1e-8, rtol=0))
            result.append(replace(path, points=q[:-1] if closed else q, closed=closed,
                                  stay_down=False, stay_down_from=None, cut_conditions=[], link_condition=None))
    return result


def tab_pick(mesh, setup, mode, origin, direction, *unused):
    """Worker-side side-wall placement or ray-box removal (no GUI geometry work)."""
    from gcodeproducer.core.geometry.kernel import ray_triangles
    origin, direction = np.asarray(origin), np.asarray(direction)
    if mode == "tab_remove":
        candidates = []
        indices = [i for i, t in enumerate(setup.tabs) if t.enabled]
        for i, (lo, hi) in zip(indices, resolve_tabs(mesh, setup)):
            t0, t1 = 0., float("inf")
            for axis in range(3):
                if abs(direction[axis]) < 1e-12:
                    if not lo[axis] <= origin[axis] <= hi[axis]:
                        t1 = -1
                        break
                else:
                    a, b = sorted(((lo[axis]-origin[axis])/direction[axis], (hi[axis]-origin[axis])/direction[axis]))
                    t0, t1 = max(t0, a), min(t1, b)
            if t1 >= t0:
                candidates.append((t0, i))
        return {"remove": min(candidates)[1]} if candidates else None
    if not setup.stock.allocated:
        return {"error": "Allocate material before placing holding tabs"}
    tris = mesh.vertices[mesh.triangles]
    distance, index = ray_triangles(origin, direction, tris)
    if index < 0:
        return None
    tri = tris[index]
    normal = np.cross(tri[1]-tri[0], tri[2]-tri[0])
    if abs(normal[2]) > .7*np.linalg.norm(normal):
        return {"error": "Click a side wall, not a top or bottom face"}
    point = origin+distance*direction
    u, v = np.linalg.lstsq(np.column_stack((tri[1]-tri[0], tri[2]-tri[0])), point-tri[0], rcond=None)[0]
    return {"triangle": int(index), "barycentric": [float(1-u-v), float(u), float(v)]}
