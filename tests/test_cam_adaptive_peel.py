import numpy as np
import pytest
from shapely.geometry import LineString, Point, box

from gcodeproducer.core.cam.adaptive_peel import _turn, choose_peel, evaluate_peel, trace_peels


@pytest.fixture
def peel_case():
    centre = np.array([10., 10.])
    seam = np.array([0., 2.])
    region = box(2, 2, 38, 18)
    stock = box(0, 0, 40, 20)
    material = stock.difference(Point(centre).buffer(3.01, quad_segs=32))
    return centre, seam, region, stock, material


def test_peel_reduces_advance_when_requested_turn_overloads(peel_case):
    centre, seam, region, _, material = peel_case
    wide = _turn(centre, seam, np.array([1., 0.]), 1, 1.)
    assert evaluate_peel(wide, material, 1.)[0] > .14
    assert evaluate_peel(wide, material, 1., abort_above=.14) is None
    choice = choose_peel(centre, seam, (1, 0), 1., 1., .14, region, material)
    assert choice is not None and 0 < choice.advance < 1.
    assert 0 < choice.peak_engagement <= .14
    assert choice.removed_area == pytest.approx(material.area - choice.remaining.area)
    assert region.covers(LineString(choice.points))
    np.testing.assert_allclose(choice.points[0], centre+seam)
    np.testing.assert_allclose(choice.points[-1], choice.centre+seam)
    assert choice.length > 2*np.pi*np.linalg.norm(seam)


def test_expanding_peel_opens_more_stock_in_wide_area(peel_case):
    centre, seam, region, _, material = peel_case
    args = (centre, seam, (1, 0), 1., 1., .18, region, material)
    translated = choose_peel(*args, min_loop_radius=2., max_loop_radius=3.)
    expanded = choose_peel(*args, min_loop_radius=2., max_loop_radius=3., expand=True)
    assert expanded.advance == 0. and expanded.peak_engagement <= .18
    np.testing.assert_array_equal(expanded.centre, centre)
    np.testing.assert_array_equal(expanded.points[0], centre+seam)
    np.testing.assert_array_equal(expanded.points[-1], centre+expanded.seam)
    assert np.linalg.norm(expanded.seam) == pytest.approx(3.)
    assert expanded.removed_area/expanded.length > translated.removed_area/translated.length
    assert region.covers(LineString(expanded.points))
    narrowed = box(2., 2., 12.4, 18.)
    restricted = choose_peel(centre, seam, (1, 0), 1., 1., .18, narrowed, material,
                             min_loop_radius=2., max_loop_radius=3., expand=True)
    if restricted is not None:
        assert narrowed.buffer(1e-7).covers(LineString(restricted.points))
        assert np.linalg.norm(restricted.seam) < 3.


def test_peel_uses_updated_stock_and_restarts_at_same_seam(peel_case):
    centre, seam, region, _, material = peel_case
    first = choose_peel(centre, seam, (1, 0), 1., 1., .14, region, material)
    second = choose_peel(first.centre, seam, (1, 0), 1., 1., .14, region, first.remaining)
    assert first.advance != second.advance
    np.testing.assert_array_equal(first.points[-1], second.points[0])
    assert second.remaining.difference(first.remaining).area < 1e-8
    assert second.peak_engagement <= .14


def test_peel_fails_closed_at_island_and_does_not_assume_entry_cleared(peel_case):
    centre, seam, region, stock, material = peel_case
    blocked = region.difference(box(11.8, 9, 14, 11))
    assert choose_peel(centre, seam, (1, 0), 1., 1., .14, blocked, material) is None
    assert choose_peel(centre, seam, (1, 0), 1., 1., .14, region, stock) is None
    assert choose_peel(centre, seam, (1, 0), 1., 1., .14, region, stock.difference(stock)) is None


def test_trace_turns_and_shrinks_at_wall_without_repositioning(peel_case):
    centre, seam, _, _, material = peel_case
    region = box(2, 2, 12.04, 18)
    assert choose_peel(centre, seam, (1, 0), 1., 1., .14, region, material) is None
    turns = trace_peels(centre, seam, (1, 0), 1., 1., .14, region, material,
                        min_loop_radius=1.4, max_loop_radius=2.5, turns=8)
    assert len(turns) == 2  # stops when no legal, useful next turn is found
    assert abs(turns[0].centre[1] - centre[1]) > .1
    assert np.linalg.norm(turns[0].seam) < np.linalg.norm(seam)
    np.testing.assert_array_equal(turns[0].points[-1], turns[1].points[0])
    a = turns[0].points[-1] - turns[0].points[-2]
    b = turns[1].points[1] - turns[1].points[0]
    assert np.dot(a, b) / (np.linalg.norm(a)*np.linalg.norm(b)) > .98
    for choice in turns:
        assert region.buffer(1e-7).covers(LineString(choice.points))
        assert 0 < choice.peak_engagement <= .14
        assert 1.4 <= np.linalg.norm(choice.seam) <= 2.5
    assert material.area - turns[-1].remaining.area == pytest.approx(sum(p.removed_area for p in turns))
