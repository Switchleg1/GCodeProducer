"""FeedPolicy — the one rule for CAM feed rates and Preview features.

rate = base(phase) x factor(engagement band) -> capped by machine max_feed.
"""
from __future__ import annotations
import math
from .planner_constants import (LEAD_BASE_PHASES, FACTOR_PHASES, PHASE_FEATURES,
                                ENGAGEMENT_FEATURES, MIN_FEED, ENGAGED)


class FeedPolicy:
    def __init__(self, max_feed=0.0, highlight_conflicts=True):
        max_feed = float(max_feed or 0)
        if not math.isfinite(max_feed) or max_feed < 0:
            raise ValueError("Machine max feed must be nonnegative and finite")
        self.max_feed = max_feed
        self.highlight_conflicts = bool(highlight_conflicts)
        self.capped = set()

    def limit(self, value):
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("CAM cutting/plunge feeds must be positive and finite")
        if self.max_feed > 0 and value > self.max_feed:
            self.capped.add((value, self.max_feed))
            value = self.max_feed
        if value < MIN_FEED:
            raise ValueError("Effective CAM feed is too small to represent safely (below 0.0001 mm/min)")
        return value

    @staticmethod
    def plunging(phase, condition=None, steep=False):
        """A move down into material: a plunge, or an engaged descent steeper than the lead-in ramp."""
        engaged = condition is not None and condition.engagement > ENGAGED
        return phase == "plunge" or (steep and engaged and phase != "approach")

    def rate(self, phase, cut_base, lead_base, condition=None, steep=False, plunge_base=None):
        """Feed for a move of ``phase``; ``steep`` marks an XYZ descent steeper than the lead-in ramp.

        Every move down into material is fed at the plunge rate (never above the
        cut rate), unscaled by engagement; lead-ins, lead-outs and air approaches
        use the lead-in rate.
        """
        plunge_base = lead_base if plunge_base is None else plunge_base
        if self.plunging(phase, condition, steep):
            base = plunge_base if phase == "plunge" else min(float(cut_base), float(plunge_base))
            return self.limit(float(base))
        base = lead_base if phase in LEAD_BASE_PHASES else cut_base
        factor = condition.feed_factor if condition is not None and phase in FACTOR_PHASES else 1.0
        return self.limit(float(base)*factor)

    def feature(self, phase, condition=None, steep=False):
        if self.plunging(phase, condition, steep):
            return "plunge"
        if phase in PHASE_FEATURES:
            return PHASE_FEATURES[phase]
        if condition is None:
            return "cut"
        if condition.conflict and self.highlight_conflicts:
            return "conflict"
        return ENGAGEMENT_FEATURES.get(condition.regime, "cut")
