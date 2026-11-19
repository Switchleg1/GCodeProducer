"""3D Douglas–Peucker with exact reuse between successive surface bands."""
import numpy as np

from .cam_constants import SURFACE_SIMPLIFY, SURFACE_REUSE_MIN_POINTS


def simplify3d(points, tolerance=SURFACE_SIMPLIFY):
    """Keep endpoints and the original 3D point-to-segment tolerance."""
    points = np.asarray(points, float)
    if len(points) < 3:
        return points
    keep, _ = _simplify_mask(points, tolerance)
    return points[keep]


def _simplify_mask(points, tolerance, previous=None):
    keep = np.zeros(len(points), bool)
    keep[[0, -1]] = True
    intervals = set() if previous is not None else None
    prior_mask, prior_intervals, changed = previous if previous is not None else (None, (), None)
    stack = [(0, len(points)-1)]
    while stack:
        first, last = stack.pop()
        if intervals is not None and last-first >= SURFACE_REUSE_MIN_POINTS-1:
            key = first, last
            intervals.add(key)
            if key in prior_intervals and changed[last+1] == changed[first]:
                keep[first:last+1] = prior_mask[first:last+1]
                continue
        a, d = points[first], points[last]-points[first]
        rel = points[first+1:last]-a
        length = float(d @ d)
        if length >= 1e-24:
            t = (rel @ d/length).clip(0, 1)
            rel -= t[:, None]*d
        distances = np.linalg.norm(rel, axis=1)
        worst = int(distances.argmax())
        if distances[worst] > tolerance:
            middle = first+1+worst
            keep[middle] = True
            if middle-first >= 2:
                stack.append((first, middle))
            if last-middle >= 2:
                stack.append((middle, last))
    return keep, intervals


class SurfaceSimplifier:
    """Reuse decisions from just the previous band, for this operation only."""

    def __init__(self, tolerance=SURFACE_SIMPLIFY):
        self.tolerance = tolerance
        self._previous = []

    def __call__(self, paths):
        current, result = [], []
        for i, points in enumerate(paths):
            if len(points) < SURFACE_REUSE_MIN_POINTS:
                current.append(None)
                result.append(simplify3d(points, self.tolerance))
                continue
            prior = self._previous[i] if i < len(self._previous) else None
            if prior is not None and prior[0].shape == points.shape:
                old, mask, intervals, reduced = prior
                differs = np.any(old != points, axis=1)
                if not differs.any():
                    current.append(prior)
                    result.append(reduced)
                    continue
                changed = np.empty(len(points)+1, dtype=np.int32)
                changed[0] = 0
                np.cumsum(differs, dtype=np.int32, out=changed[1:])
                context = mask, intervals, changed
            else:
                context = None, (), None
            mask, intervals = _simplify_mask(points, self.tolerance, context)
            reduced = points[mask]
            current.append((points, mask, intervals, reduced))
            result.append(reduced)
        self._previous = current
        return result
