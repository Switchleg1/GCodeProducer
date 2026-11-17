"""MotionSegment — one planned move with its phase, engagement and rate."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
from gcodeproducer.core.jobs.cut_condition import CutCondition


@dataclass
class MotionSegment:
    phase: str                          # see planner_constants.PHASES
    start: np.ndarray                   # XYZ before the move
    end: np.ndarray                     # XYZ after the move
    condition: Optional[CutCondition]   # measured engagement (None = unknown / not measured)
    rate: Optional[float]               # mm/min; None for rapids
    feature: str                        # Preview feature
    comment: Optional[str] = None

    @property
    def note(self):
        c = self.condition
        if c is None:
            return None
        return f"{c.regime} {c.engagement*100:.2f}% engagement; {c.hand}"
