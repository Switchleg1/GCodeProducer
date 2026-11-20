"""Transactional, engagement-checked transition to ordinary clearing moves."""
from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry import LineString
from shapely.prepared import prep
from shapely.geometry.base import BaseGeometry

from .adaptive_link import choose_link
from .adaptive_peel import evaluate_peel
from .cam_constants import ADAPTIVE_CAM_POINT_LIMIT, ADAPTIVE_LINK_BUFFER_QUADS, ADAPTIVE_PEEL_SAMPLE_STEP_RADII
from .paths import _nearest_seam


@dataclass(frozen=True)
class AdaptiveFinish:
    points: np.ndarray
    remaining: BaseGeometry
    contours: int


def checked_finish(position, contours, region, material, radius, limit, *, travel_feed, z_feed, lift):
    """Accept a complete finish only if its cuts meet the same limit as peels.

    Never add an engaged shortcut to a seam or a retract. A rejected trial
    leaves the input stock untouched. Not a guarantee of actual cutter load.
    """
    points, stock, count, samples = [np.asarray(position)[None, :]], material, 0, 0
    quads = ADAPTIVE_LINK_BUFFER_QUADS
    reach = radius/math.cos(math.pi/(2*quads)) + 1e-7
    valid = prep(region.buffer(1e-7))
    for contour in contours:
        line = LineString(np.vstack((contour, contour[0])))
        if not line.buffer(reach, quad_segs=quads).intersects(stock):
            continue
        if not valid.covers(line):
            return None
        _, phased = _nearest_seam(contour, position)
        link = choose_link(position, phased[0], region, stock, radius, travel_feed=travel_feed,
                           z_feed=z_feed, lift=lift)
        if link is None or link.kind != 'stay_down':
            return None
        loop = np.vstack((phased, phased[0]))
        delta = np.diff(loop, axis=0)
        spacing = radius * ADAPTIVE_PEEL_SAMPLE_STEP_RADII
        ratio = np.linalg.norm(delta, axis=1)/spacing
        if np.any(ratio > ADAPTIVE_CAM_POINT_LIMIT):
            return None
        divisions = np.maximum(1, np.ceil(ratio).astype(int))
        samples += int(divisions.sum()) + len(link.points)
        if samples > ADAPTIVE_CAM_POINT_LIMIT:
            return None
        cut = np.vstack([a + np.arange(n)[:, None]*d/n for a, d, n in zip(loop, delta, divisions)] + [loop[-1:]])
        outcome = evaluate_peel(cut, stock, radius, abort_above=limit)
        if outcome is None:
            return None
        stock = outcome[-1]
        position = cut[-1]
        points.extend((link.points[1:], cut[1:]))
        count += 1
    return AdaptiveFinish(np.vstack(points), stock, count) if count else None
