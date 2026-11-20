import numpy as np
import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from gcodeproducer.core.cam.adaptive_branch import choose_branch
from gcodeproducer.core.cam.adaptive_link import choose_link


def test_clear_detour_beats_slow_retract_but_not_fast_retract():
    blank = box(0, 0, 30, 30)
    start, via, end = (5, 5), (5, 20), (20, 20)
    region = blank.buffer(-1)
    material = blank.difference(LineString([start, via, end]).buffer(1.5))
    args = (start, end, region, material, 1.)
    slow = choose_link(*args, travel_feed=1200, z_feed=150, lift=3, waypoints=[(12, 12), via])
    assert slow.kind == 'stay_down'
    np.testing.assert_array_equal(slow.points, [start, via, end])
    assert slow.minutes == pytest.approx(30/1200)
    fast = choose_link(*args, travel_feed=1200, z_feed=1200, lift=3, waypoints=[via])
    assert fast.kind == 'retract'
    assert fast.minutes == pytest.approx(np.hypot(15, 15)/1200 + 6/1200)


def test_two_bend_return_uses_cleared_corridor_only_when_faster():
    blank = box(0, 0, 40, 30)
    start, a, b, end = (5, 5), (5, 20), (27, 20), (27, 5)
    corridor = LineString([start, a, b, end]).buffer(1.5)
    stock = blank.difference(corridor)
    args = (start, end, blank.buffer(-1), stock, 1.)
    assert choose_link(*args, travel_feed=1200, z_feed=150, lift=3, waypoints=[a]).kind == 'retract'
    link = choose_link(*args, travel_feed=1200, z_feed=150, lift=3, waypoints=[a, b, (16, 5)])
    assert link.kind == 'stay_down' and link.minutes == pytest.approx(52/1200)
    np.testing.assert_array_equal(link.points, [start, a, b, end])
    assert choose_link(*args, travel_feed=1200, z_feed=1200, lift=3, waypoints=[a, b]).kind == 'retract'
    blocked = stock.union(box(15, 19, 17, 21))
    assert choose_link(start, end, args[2], blocked, 1., travel_feed=1200, z_feed=150, lift=3,
                       waypoints=[a, b]).kind == 'retract'


def test_link_needs_a_verified_clear_landing_and_rejects_protected_island():
    region = box(1, 1, 29, 29).difference(box(12, 12, 17, 17))
    blank = box(0, 0, 30, 30)
    start, end = (5, 15), (25, 15)
    params = dict(travel_feed=1200, z_feed=150, lift=3)
    material = blank.difference(Point(start).buffer(2))
    assert choose_link(start, end, region, material, 1., **params) is None
    result = choose_link(start, end, region, blank.difference(blank), 1., **params)
    assert result.kind == 'retract'  # even if the stock model thinks the protected island is empty
    assert choose_link(start, (15, 15), region, blank.difference(blank), 1., **params) is None


def test_branch_prefers_equal_cut_without_repositioning_and_preserves_trial_stock():
    blank = box(0, 0, 45, 25)
    region = blank.buffer(-1)
    near, far = (10., 10.), (30., 10.)
    material = blank.difference(unary_union([Point(p).buffer(3.02, quad_segs=32) for p in (near, far)]))
    starts = [(c, (0., 2.), (1., 0.)) for c in (far, (20., 10.), near)]
    choice = choose_branch((10., 12.), starts, region, material, pitch=1., tool_radius=1., limit=.18,
                           min_loop_radius=2., max_loop_radius=2., cut_feed=800,
                           travel_feed=1200, z_feed=150, lift=3)
    assert choice.index == 2 and choice.link.minutes == 0
    np.testing.assert_array_equal(choice.link.points[-1], choice.peel.points[0])
    assert choice.minutes == pytest.approx(choice.peel.length/800)
    assert choice.removal_rate > 0 and choice.peel.peak_engagement <= .18
    assert material.area - choice.peel.remaining.area == pytest.approx(choice.peel.removed_area)
    remote = box(25, 4, 36, 16)
    assert choice.peel.remaining.intersection(remote).equals(material.intersection(remote))
