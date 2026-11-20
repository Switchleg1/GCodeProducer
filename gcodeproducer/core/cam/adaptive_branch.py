"""Experimental selection of the next peel from nominated branch starts."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from gcodeproducer.core.cam.adaptive_link import AdaptiveLink, choose_link
from gcodeproducer.core.cam.adaptive_peel import PeelChoice, choose_steered_peel
from gcodeproducer.core.cam.cam_constants import ADAPTIVE_BRANCH_LIMIT


@dataclass(frozen=True)
class BranchChoice:
    index: int
    link: AdaptiveLink
    peel: PeelChoice
    minutes: float

    @property
    def removal_rate(self):
        return self.peel.removed_area / self.minutes


def choose_branch(position, starts, region, material, *, pitch, tool_radius, limit,
                  min_loop_radius, max_loop_radius, cut_feed, travel_feed, z_feed,
                  lift, waypoints=(), sense=1, expand=False, half_turns=False, stay_down_only=False):
    """Rank nominated (center, seam, heading) triples by useful area per minute.

    All trials see the same current stock. Return only the winner and its
    resulting stock; failed trials do not consume material. This step cannot
    start in virgin stock or discover candidate branches on its own.
    """
    if not math.isfinite(cut_feed) or cut_feed <= 0:
        raise ValueError('Adaptive branch needs a positive finite cut feed')
    if len(starts) > ADAPTIVE_BRANCH_LIMIT:
        raise ValueError('Too many adaptive branch candidates')
    best = None
    for index, (centre, seam, heading) in enumerate(starts):
        entry = np.asarray(centre, float) + np.asarray(seam, float)
        link = choose_link(position, entry, region, material, tool_radius, travel_feed=travel_feed,
                           z_feed=z_feed, lift=lift, waypoints=waypoints)
        if link is None or (stay_down_only and link.kind != 'stay_down'):
            continue
        peel = choose_steered_peel(centre, seam, heading, pitch, tool_radius, limit, region, material,
                                   min_loop_radius=min_loop_radius, max_loop_radius=max_loop_radius,
                                   sense=sense, expand=expand, half_turns=half_turns)
        if peel is None:
            continue
        choice = BranchChoice(index, link, peel, link.minutes + peel.length/cut_feed)
        if best is None or choice.removal_rate > best.removal_rate:
            best = choice
    return best
