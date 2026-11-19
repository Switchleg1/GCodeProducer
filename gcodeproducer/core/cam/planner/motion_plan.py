"""MotionPlan — ordered segments of one CAM job, with phase / engagement totals."""
from __future__ import annotations
from collections import Counter
from .planner_constants import MOTION_CHUNK_SIZE


class MotionPlan:
    def __init__(self, consume=None, chunk_size=None):
        chunk_size = MOTION_CHUNK_SIZE if chunk_size is None else chunk_size
        if chunk_size < 1:
            raise ValueError('Motion chunk size must be positive')
        self.segments = []  # bounded inspection prefix for streamed jobs
        self.complete = True
        self.total = 0
        self._consume = consume
        self._chunk_size = chunk_size
        self._pending = []

    def add(self, segment):
        self.total += 1
        if self._consume is None or len(self.segments) < self._chunk_size:
            self.segments.append(segment)
        else:
            self.complete = False
        if self._consume is not None:
            self._pending.append(segment)
            if len(self._pending) >= self._chunk_size:
                self._flush()
        return segment

    def _flush(self):
        if self._pending:
            self._consume(self._pending)
            self._pending.clear()

    def finish(self):
        self._flush()
        self._consume = None

    def phases(self) -> Counter:
        """Phase counts for retained inspection segments."""
        return Counter(s.phase for s in self.segments)

    def regimes(self, phases=None) -> Counter:
        """Engagement counts for retained inspection segments."""
        return Counter(s.condition.regime for s in self.segments
                       if s.condition is not None and (phases is None or s.phase in phases))

    def of(self, phase):
        return [s for s in self.segments if s.phase == phase]
