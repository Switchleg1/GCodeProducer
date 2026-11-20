"""Transactional, engagement-checked transition to ordinary clearing moves."""
from dataclasses import dataclass
import math

import numpy as np
from shapely.geometry import LineString
from shapely.prepared import prep
from shapely.geometry.base import BaseGeometry

from .adaptive_link import choose_link
from .adaptive_peel import evaluate_peel
from .adaptive_rounding import rounded_loop
from .cam_constants import (
    ADAPTIVE_BLEND_RADIUS_FACTORS, ADAPTIVE_CAM_POINT_LIMIT, ADAPTIVE_LINK_BUFFER_QUADS,
    ADAPTIVE_PEEL_SAMPLE_STEP_RADII, ADAPTIVE_POCKET_AREA_EPS,
)
from .paths import _nearest_seam


@dataclass(frozen=True)
class AdaptiveFinish:
    points: np.ndarray
    remaining: BaseGeometry
    contours: int


def checked_finish(position, contours, region, material, radius, limit, *, travel_feed, z_feed, lift,
                   target=None):
    """Try rounded finish passes without committing failed trials or sharp corners."""
    for factor in ADAPTIVE_BLEND_RADIUS_FACTORS:
        result = _trial_finish(position, contours, region, material, radius, limit, radius*factor,
                               travel_feed=travel_feed, z_feed=z_feed, lift=lift)
        if result is not None and (target is None or
                                   target.intersection(result.remaining).area <= ADAPTIVE_POCKET_AREA_EPS):
            return result
    return None


def _trial_finish(position, contours, region, material, radius, limit, blend, *, travel_feed, z_feed, lift):
    points, stock, count, samples = [np.asarray(position)[None, :]], material, 0, 0
    quads = ADAPTIVE_LINK_BUFFER_QUADS
    reach = radius/math.cos(math.pi/(2*quads)) + 1e-7
    valid = prep(region.buffer(1e-7))
    for contour in contours:
        line = LineString(np.vstack((contour, contour[0])))
        if not line.buffer(reach, quad_segs=quads).intersects(stock):
            continue
        rounded = rounded_loop(contour, blend)
        if rounded is None or not valid.covers(LineString(np.vstack((rounded, rounded[0])))):
            return None
        _, phased = _nearest_seam(rounded, position)
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
