"""FeedSmoother — fewer, longer feed zones along one continuous cutting run.

Feeds are chosen per measured sub-move, so a rough surface or a band edge can
give a string of tiny moves whose feeds jump back and forth. Along a run of
feed moves (no rapid or retract in between) each short move takes the lowest
feed found within half the smoothing length on either side, so a short fast
stretch between slower ones is slowed to match them. Feeds are only ever
lowered, never raised, and long moves keep their own feed. Afterwards,
consecutive collinear moves that now share phase, feature and feed are written
as one move.
"""
from __future__ import annotations
import numpy as np
from .planner_constants import FEED_SMOOTH_PHASES, MERGE_PHASES


class FeedSmoother:
    def __init__(self, length=0.0, merge=True):
        self.length = max(0.0, float(length or 0))
        self.merge = bool(merge)
        self.slowed = 0

    @staticmethod
    def smoothable(segment):
        return (segment.phase in FEED_SMOOTH_PHASES and segment.rate is not None
                and segment.start is not None and segment.end is not None)

    def __call__(self, run):
        if len(run) < 2 or self.length <= 0:
            return run
        lengths = np.array([float(np.linalg.norm(s.end-s.start)) for s in run])
        ends = np.cumsum(lengths)
        starts = ends-lengths
        rates = np.array([float(s.rate) for s in run])
        reach = self.length/2
        smoothed = rates.copy()
        for i in np.flatnonzero(lengths < self.length):
            near = (starts < ends[i]+reach) & (ends > starts[i]-reach)
            smoothed[i] = rates[near].min()
        for segment, old, new in zip(run, rates, smoothed):
            if new < old-1e-9:
                segment.rate = float(new)
                self.slowed += 1
        return self._merged(run) if self.merge else run

    @staticmethod
    def _merged(run):
        out = []
        for segment in run:
            last = out[-1] if out else None
            if (last is not None and segment.phase == last.phase and segment.phase in MERGE_PHASES
                    and segment.feature == last.feature and abs(segment.rate-last.rate) < 1e-9
                    and segment.comment == last.comment and not segment.force_feed
                    and _collinear(last.start, last.end, segment.end)):
                last.end = segment.end
                if segment.condition is not None and (last.condition is None or
                                                      segment.condition.engagement > last.condition.engagement):
                    last.condition = segment.condition
                continue
            out.append(segment)
        return out


def _collinear(a, b, c, tolerance=5e-4):
    """``b`` lies on the straight line from ``a`` to ``c`` (within ``tolerance`` mm: the rounding of emitted Z)."""
    ac = c-a
    span = float(np.linalg.norm(ac))
    if span < 1e-12:
        return False
    t = float(np.dot(b-a, ac))/span**2
    return 0 < t < 1 and float(np.linalg.norm(a+ac*t-b)) <= tolerance
