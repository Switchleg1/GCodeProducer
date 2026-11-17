"""PlanarSampler — engagement on a planar material region at one depth (Shapely chords)."""
from __future__ import annotations
import numpy as np
from shapely.geometry import LineString, Point
from .engagement_sampler import EngagementSampler


class PlanarSampler(EngagementSampler):
    def __init__(self, material):
        self.material = material          # remaining XY material at the cutting depth

    def measure_path(self, points, closed, radius):
        from gcodeproducer.core.cam.engagement import measure_segments
        return measure_segments(np.asarray(points, float)[:, :2], closed, self.material, radius)

    def measure_move(self, a, b, radius):
        return self.measure_path(np.array([np.asarray(a)[:2], np.asarray(b)[:2]]), False, radius)

    def remove_path(self, points, closed, radius):
        p = np.asarray(points, float)[:, :2]
        if len(p) == 1:
            sweep = Point(p[0]).buffer(radius)
        else:
            sweep = LineString(np.vstack((p, p[0])) if closed else p).buffer(radius)
        self.material = self.material.difference(sweep)

    def remove_move(self, a, b, radius):
        self.remove_path(np.array([np.asarray(a)[:2], np.asarray(b)[:2]]), False, radius)
