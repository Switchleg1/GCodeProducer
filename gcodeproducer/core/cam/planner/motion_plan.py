"""MotionPlan — ordered segments of one CAM job, with phase / engagement totals."""
from __future__ import annotations
from collections import Counter


class MotionPlan:
    def __init__(self):
        self.segments = []

    def add(self, segment):
        self.segments.append(segment)
        return segment

    def phases(self) -> Counter:
        return Counter(s.phase for s in self.segments)

    def regimes(self, phases=None) -> Counter:
        return Counter(s.condition.regime for s in self.segments
                       if s.condition is not None and (phases is None or s.phase in phases))

    def of(self, phase):
        return [s for s in self.segments if s.phase == phase]
