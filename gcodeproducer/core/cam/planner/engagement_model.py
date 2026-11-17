"""EngagementModel — the one classifier from a measurement to a CutCondition.

Bands (machine thresholds), cutting hand and feed factor (operation / tool /
machine overrides) are identical for every sampler and every operation.
"""
from __future__ import annotations
from gcodeproducer.core.jobs.cut_condition import CutCondition


class EngagementModel:
    def __init__(self, operation, tool, machine):
        from gcodeproducer.core.cam.engagement import engagement_band
        self.operation = operation
        self.tool = tool.resolved() if hasattr(tool, "resolved") else (tool or {})
        self.machine = machine.resolved() if hasattr(machine, "resolved") else (machine or {})
        engagement_band(.5, self.machine)            # validate thresholds even for all-air work

    def classify(self, left, right, engagement, neutral=False):
        from gcodeproducer.core.cam.engagement import engagement_band, feed_factor, _hand
        result = []
        for l, r, e in zip(left, right, engagement):
            band = engagement_band(e, self.machine)
            hand = "neutral" if neutral and e > 1e-6 else _hand(l, r, e, self.machine)
            result.append(CutCondition(float(e), band, hand, feed_factor(band, self.operation, self.tool, self.machine)))
        return result

    def condition(self, sampler, a, b, radius):
        left, right, engagement, _ = sampler.measure_move(a, b, radius)
        return self.classify(left, right, engagement)[0]
