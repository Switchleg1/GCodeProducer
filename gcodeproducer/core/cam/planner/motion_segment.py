"""MotionSegment — one planned step of the CAM program.

Motion segments carry the phase, XYZ, engagement and rate; ``comment`` and
``command`` segments carry the non-motion lines (layer/operation markers,
spindle and tool changes) so the planner fully determines the program and the
G-code writer only serializes it.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
from gcodeproducer.core.jobs.cut_condition import CutCondition


@dataclass
class MotionSegment:
    phase: str                          # see planner_constants.PHASES (+ "comment" / "command")
    start: Optional[np.ndarray]         # XYZ before the move (None for non-motion)
    end: Optional[np.ndarray]           # XYZ after the move
    condition: Optional[CutCondition]   # measured / planned engagement (None = unknown)
    rate: Optional[float]               # mm/min; None for Z rapids and non-motion
    feature: str                        # Preview feature
    comment: Optional[str] = None
    layer: int = 0                      # job layer index (Preview layer)
    op: Optional[str] = None            # operation label "group.index name"
    words: Optional[str] = None         # comment text / command words for non-motion segments
    force_feed: bool = False            # always state F (first cut after an entry, links)

    @property
    def motion(self):
        from .planner_constants import NON_MOTION
        return self.phase not in NON_MOTION

    @property
    def note(self):
        c = self.condition
        if c is None:
            return None
        return f"{c.regime} {c.engagement*100:.2f}% engagement; {c.hand}"
