"""EngagementSampler — the measurement plug-in interface of the material model.

A sampler measures how much *current* material a cutter meets along a move,
as occupied left/right chord widths and a radial engagement fraction, and
removes the swept material afterwards. Classification into Slot / High / Cut /
HSM / Air is not the sampler's job: that is :class:`EngagementModel`, shared by
every sampler and every operation.
"""
from __future__ import annotations
import numpy as np


class EngagementSampler:
    """Measure and remove material; subclasses implement one representation."""

    def measure_move(self, a, b, radius):
        """(left, right, engagement, lengths) arrays of length 1 for one move a -> b."""
        raise NotImplementedError

    def remove_move(self, a, b, radius):
        raise NotImplementedError

    def measure_path(self, points, closed, radius):
        """(left, right, engagement, lengths) arrays, one entry per path segment."""
        p = np.asarray(points, float)
        q = np.vstack((p, p[0])) if closed else p
        parts = [self.measure_move(a, b, radius) for a, b in zip(q, q[1:])]
        if not parts:
            empty = np.zeros(0)
            return empty, empty, empty, empty
        return tuple(np.concatenate([part[i] for part in parts]) for i in range(4))

    def remove_path(self, points, closed, radius):
        p = np.asarray(points, float)
        q = np.vstack((p, p[0])) if closed else p
        for a, b in zip(q, q[1:]):
            self.remove_move(a, b, radius)
