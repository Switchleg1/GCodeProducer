"""Offline selection of a useful frontier cut from a cleared pose."""
import math
from collections import Counter
from typing import NamedTuple

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from tools.hsm_straight_front import try_front_cut
from tools.hsm_tangent_link import cleared_tangent_detour, cleared_tangent_link, cleared_three_leg_link, forward_clearance


class FrontChoice(NamedTuple):
    link: list
    cut: list
    remaining: BaseGeometry
    peak_deg: float
    removed_mm2: float
    travel_mm: float


def choose_front_cut(pocket, stock, pose, candidates, radius, *, contact_limit, sample_step,
                     link_handle, link_margin=0., diagnostics=None, waypoints=(), on_overload=None, require_clear_exit=False,
                     with_three_leg_links=False, min_departure=0., priority_region=None, priority_score=None, on_eligible=None):
    """Rank by removed stock per mm of checked link plus cut; no implied retract."""
    if not math.isfinite(min_departure) or min_departure < 0:
        raise ValueError('minimum departure must be nonnegative and finite')
    counts = diagnostics if diagnostics is not None else Counter()

    def reject(reason):
        counts[reason] += 1

    xy, heading = pose
    if (not all(map(math.isfinite, (radius, link_margin, link_handle)))
            or radius <= 0 or link_margin < 0 or link_handle <= 0):
        raise ValueError('invalid cutter radius, link margin or handle')
    clearance = radius + link_margin
    walls = pocket.boundary

    def clear_at(position, material):
        point = Point(position)
        return (pocket.covers(point) and point.distance(walls) >= clearance
                and (material.is_empty or point.distance(material) >= clearance))

    if not clear_at(xy, stock):
        reject('origin_clearance')
        return None
    waypoints = tuple(waypoints)
    priority_stock = stock.intersection(priority_region) if priority_region is not None else None
    best = None
    best_key = None
    for cut in candidates:
        if cut is None or len(cut) < 2:
            reject('invalid_candidate')
            continue
        incoming = tuple(b-a for a, b in zip(cut[0], cut[1]))
        if not math.hypot(*incoming):
            reject('invalid_candidate')
            continue
        if xy == cut[0]:
            dot = sum(a*b for a, b in zip(heading, incoming))
            cross = heading[0]*incoming[1] - heading[1]*incoming[0]
            if dot <= 0 or abs(cross) > 1e-9*dot:
                reject('heading')
                continue
            link = [xy]
        else:
            if not clear_at(cut[0], stock):
                reject('start_clearance')
                continue
            link = cleared_tangent_link(pocket, stock, radius, xy, cut[0], heading, incoming,
                                        link_handle, margin=link_margin)
            if link is None and waypoints:
                routes = (cleared_tangent_detour(pocket, stock, radius, pose, via, (cut[0], incoming),
                                                 link_handle, margin=link_margin)
                          for via in waypoints if via[0] not in (xy, cut[0]))
                link = min((route for route in routes if route is not None), key=_length, default=None)
            if link is None and waypoints and with_three_leg_links:
                link = cleared_three_leg_link(pocket, stock, radius, pose, (cut[0], incoming), waypoints,
                                              link_handle, margin=link_margin)
            if link is None:
                reject('link_clearance')
                continue
        result = try_front_cut(pocket, stock, cut, radius, contact_limit=contact_limit,
                               sample_step=sample_step, reject=reject, on_overload=on_overload)
        if result is None:
            continue
        remaining, peak = result
        if require_clear_exit and not clear_at(cut[-1], remaining):
            reject('exit_clearance')
            continue
        if min_departure:
            tail = cut[-1]
            previous = next(point for point in reversed(cut[:-1]) if point != tail)
            departure = tuple(b-a for a, b in zip(previous, tail))
            if forward_clearance(pocket, remaining, clearance, tail, departure, min_departure) < min_departure:
                reject('departure_clearance')
                continue
        counts['eligible'] += 1
        removed = stock.area - remaining.area
        travel = _length(link) + _length(cut)
        key = (removed/travel, removed, -travel)
        if priority_stock is not None:
            priority_gain = priority_stock.difference(remaining).area
            key = (priority_gain/travel, *key)
        if priority_score is not None:
            key = (priority_score(remaining), *key)
        candidate = FrontChoice(link, cut, remaining, peak, removed, travel)
        if on_eligible is not None:
            on_eligible(key, candidate)
        if best_key is None or key > best_key:
            best = candidate
            best_key = key
    return best


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))
