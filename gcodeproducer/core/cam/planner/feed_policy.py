"""FeedPolicy — the one rule for CAM feed rates and Preview features.

rate = base(phase) x factor(engagement band) -> capped by machine max_feed.
"""
from __future__ import annotations
import math
from gcodeproducer.core.cam.cam_constants import RAMP_ANGLE
from .planner_constants import (LEAD_BASE_PHASES, FACTOR_PHASES, PHASE_FEATURES,
                                ENGAGEMENT_FEATURES, MIN_FEED, ENGAGED, DESCENT_FEED_STEPS)


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

    def rate(self, phase, cut_base, lead_base, condition=None, steep=False, plunge_base=None,
             angle=None, ramp=RAMP_ANGLE):
        """Feed for a move of ``phase``.

        A move down into material is fed by its descent ``angle`` (degrees below
        horizontal; without one, ``steep`` means straight down): from the rate
        it would have level (cut, link, lead-in ... with its engagement factor)
        at 0 to the lead-in rate at the lead-in angle ``ramp``, then down to the
        plunge rate straight down. Never faster than the level rate on the way
        to the lead-in angle, nor than the cut base beyond it. An explicit
        plunge is straight down; air and approach moves are not descents into
        material.
        """
        plunge_base = lead_base if plunge_base is None else plunge_base
        if phase == "plunge":
            return self.limit(float(plunge_base))
        base = lead_base if phase in LEAD_BASE_PHASES else cut_base
        factor = condition.feed_factor if condition is not None and phase in FACTOR_PHASES else 1.0
        level = float(base)*factor
        engaged = condition is not None and condition.engagement > ENGAGED
        angle = (90. if steep else 0.) if angle is None else min(90., float(angle))
        if not engaged or phase == "approach" or angle <= 0:
            return self.limit(level)
        ramp = min(max(float(ramp), 1e-6), 90.)
        lead = min(float(lead_base)*factor, level)
        plunge = min(float(plunge_base), float(cut_base))
        if angle <= ramp:
            start, end, share = level, lead, angle/ramp
        else:
            start, end, share = lead, plunge, (angle-ramp)/max(90.-ramp, 1e-6)
        share = round(share*DESCENT_FEED_STEPS)/DESCENT_FEED_STEPS
        return self.limit(start + (end-start)*share)

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
