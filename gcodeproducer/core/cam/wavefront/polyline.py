"""Fast pieces of polylines, as lists of points (shapely.ops.substring builds geometry point by point)."""
import numpy as np
from shapely import get_coordinates


def stretch(line, start, end):
    """Points of ``line`` from distance ``start`` to ``end`` along it, ends interpolated; like substring.

    ``line`` is a LineString or a sequence of points. Distances are clipped to
    the line; ``end`` before ``start`` gives the piece reversed.
    """
    xy = get_coordinates(line) if hasattr(line, 'geom_type') else np.asarray(line, float)[:, :2]
    if len(xy) < 2:
        return [tuple(q) for q in xy.tolist()]
    along = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    reverse = end < start
    lo, hi = sorted((float(np.clip(start, 0., along[-1])), float(np.clip(end, 0., along[-1]))))

    def at(d):
        return np.array([np.interp(d, along, xy[:, 0]), np.interp(d, along, xy[:, 1])])

    inside = xy[(along > lo) & (along < hi)]
    piece = np.vstack((at(lo), inside, at(hi)))  # an empty stretch is one point twice
    out = [tuple(q) for q in piece.tolist()]
    return out[::-1] if reverse else out
