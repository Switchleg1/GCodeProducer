"""Offline selection of a useful frontier cut from a cleared pose."""
import math
from typing import NamedTuple

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from tools.hsm_straight_front import try_front_cut
from tools.hsm_tangent_link import cleared_tangent_link


class FrontChoice(NamedTuple):
    link: list
    cut: list
    remaining: BaseGeometry
    peak_deg: float
    removed_mm2: float
    travel_mm: float


def choose_front_cut(pocket, stock, pose, candidates, radius, *, contact_limit, sample_step,
                     link_handle, link_margin=0.):
    """Rank by removed stock per mm of checked link plus cut; no implied retract."""
    xy, heading = pose
    if (not all(map(math.isfinite, (radius, link_margin, link_handle)))
            or radius <= 0 or link_margin < 0 or link_handle <= 0):
        raise ValueError('invalid cutter radius, link margin or handle')
    origin = Point(xy)
    clearance = radius + link_margin
    if (not pocket.covers(origin) or origin.distance(pocket.boundary) < clearance
            or (not stock.is_empty and origin.distance(stock) < clearance)):
        return None
    best = None
    best_key = None
    for cut in candidates:
        if cut is None or len(cut) < 2:
            continue
        incoming = tuple(b-a for a, b in zip(cut[0], cut[1]))
        if not math.hypot(*incoming):
            continue
        if xy == cut[0]:
            dot = sum(a*b for a, b in zip(heading, incoming))
            cross = heading[0]*incoming[1] - heading[1]*incoming[0]
            if dot <= 0 or abs(cross) > 1e-9*dot:
                continue
            link = [xy]
        else:
            link = cleared_tangent_link(pocket, stock, radius, xy, cut[0], heading, incoming,
                                        link_handle, margin=link_margin)
            if link is None:
                continue
        result = try_front_cut(pocket, stock, cut, radius, contact_limit=contact_limit, sample_step=sample_step)
        if result is None:
            continue
        remaining, peak = result
        removed = stock.area - remaining.area
        travel = sum(math.dist(a, b) for chain in (link, cut) for a, b in zip(chain, chain[1:]))
        key = (removed/travel, removed, -travel)
        if best_key is None or key > best_key:
            best = FrontChoice(link, cut, remaining, peak, removed, travel)
            best_key = key
    return best
