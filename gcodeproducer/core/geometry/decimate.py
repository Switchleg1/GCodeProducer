"""Remove needlessly short segments from slice contours and FDM paths.

Mesh-resolution slices produce thousands of 0.01-0.05 mm segments per layer.
They add nothing a 0.4 mm bead can reproduce, but they multiply G-code size,
planner work and firmware load. Two limits (Cura/Prusa style) apply:

* ``max_deviation``: Douglas-Peucker tolerance; any vertex that lies within it
  of the simplified line is dropped, whatever its segment length.
* ``min_length``: a vertex that leaves a segment shorter than this is merged
  away, but only while every removed vertex stays within ``max_deviation`` of
  the replacement segment. Real corners are therefore preserved.
"""
from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LinearRing, LineString

from gcodeproducer.core.geometry.geometry_constants import DECIMATE_WIDTH_TOLERANCE


def _merge_short(points, closed, min_length, max_deviation, widths=None):
    """Indices of the vertices kept by the short-segment pass (plain floats: tiny inner loops)."""
    n = len(points)
    xs, ys = points[:, 0].tolist(), points[:, 1].tolist()
    ws = None if widths is None else np.asarray(widths, float).tolist()
    dev2 = max_deviation * max_deviation
    min2 = min_length * min_length
    keep = [0]
    last = 0
    end = n if closed else n - 1          # the final open vertex always stays
    for i in range(1, end):
        nxt = i + 1 if i + 1 < n else 0
        ax, ay = xs[last], ys[last]
        bx, by = xs[nxt], ys[nxt]
        if ((xs[i]-ax)**2 + (ys[i]-ay)**2 >= min2) and ((bx-xs[i])**2 + (by-ys[i])**2 >= min2):
            keep.append(i)
            last = i
            continue
        # every vertex removed since ``last`` must stay close to the replacement segment
        dx, dy = bx - ax, by - ay
        length2 = dx*dx + dy*dy
        ok = True
        for k in range(last + 1, i + 1):
            px, py = xs[k] - ax, ys[k] - ay
            t = 0. if length2 <= 1e-24 else min(1., max(0., (px*dx + py*dy) / length2))
            if (px - t*dx)**2 + (py - t*dy)**2 > dev2:
                ok = False
                break
            if ws is not None and abs(ws[k] - (ws[last] + t*(ws[nxt] - ws[last]))) > DECIMATE_WIDTH_TOLERANCE:
                ok = False
                break
        if not ok:
            keep.append(i)
            last = i
    if not closed:
        keep.append(n - 1)
    return np.asarray(keep)


def _douglas_peucker(points, widths, tolerance):
    """Douglas-Peucker keep mask on an open polyline, treating width as a third coordinate."""
    n = len(points)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = points[i], points[j]
        inner = points[i+1:j]
        ab = b - a
        denom = float(ab @ ab)
        t = np.clip(((inner - a) @ ab) / denom, 0., 1.) if denom > 1e-24 else np.zeros(len(inner))
        score = np.hypot(*(inner - (a + t[:, None]*ab)).T) / tolerance
        if widths is not None:
            interp = widths[i] + t*(widths[j] - widths[i])
            score = np.maximum(score, np.abs(widths[i+1:j] - interp) / DECIMATE_WIDTH_TOLERANCE)
        k = int(score.argmax())
        if score[k] > 1.:
            k += i + 1
            keep[k] = True
            stack.append((i, k))
            stack.append((k, j))
    return keep


def decimate(points, closed, min_length, max_deviation, widths=None):
    """Simplified copy of ``points`` (and ``widths``); returns ``(points, widths)``.

    Closed paths keep at least three vertices, open paths their end points.
    """
    pts = np.asarray(points, float)
    if len(pts) < 3 or (min_length <= 0 and max_deviation <= 0):
        return pts, widths
    if widths is None and max_deviation > 0:
        geom = LinearRing(pts) if closed else LineString(pts)
        out = np.asarray(shapely.simplify(geom, max_deviation, preserve_topology=False).coords)
        if closed:
            out = out[:-1]
        if len(out) >= (3 if closed else 2):
            pts = out
    elif max_deviation > 0:
        w = np.asarray(widths, float)
        if closed:
            far = int(np.hypot(*(pts - pts[0]).T).argmax())
            loop = np.vstack((pts, pts[:1]))
            wl = np.append(w, w[0])
            keep = np.zeros(len(loop), dtype=bool)
            if far > 0:
                keep[:far+1] |= _douglas_peucker(loop[:far+1], wl[:far+1], max_deviation)
                keep[far:] |= _douglas_peucker(loop[far:], wl[far:], max_deviation)
            else:
                keep[:] = True
            keep = keep[:-1]
        else:
            keep = _douglas_peucker(pts, w, max_deviation)
        if keep.sum() >= (3 if closed else 2):
            pts, widths = pts[keep], w[keep]
    if min_length > 0 and len(pts) >= 3:
        w = None if widths is None else np.asarray(widths, float)
        idx = _merge_short(pts, closed, min_length, max(max_deviation, 0.), w)
        if not closed or len(idx) >= 3:
            pts = pts[idx]
            if w is not None:
                widths = w[idx]
    return pts, widths


def decimate_rings(rings, min_length, max_deviation):
    """Decimate closed slice contours; rings that collapse keep their original points."""
    if min_length <= 0 and max_deviation <= 0:
        return list(rings)
    return [decimate(ring, True, min_length, max_deviation)[0] if len(ring) >= 3 else ring
            for ring in rings]
