import math

import pytest
from shapely.geometry import Point, box

from tools.check_cambam_pocket import replay_strokes
from tools.hsm_straight_front import eased_front_bite, frontier_edges, straight_advance, try_front_cut


def test_eased_bite_removes_stock_and_ends_on_the_clearance_side():
    pocket, stock = box(0, 0, 24, 14), box(5, 5, 15, 12)
    path = eased_front_bite(((5., 5.), (15., 5.)), 1., .25, .25, .0025)
    assert path[0] == (5., 3.75) and path[-1] == (15., 3.75)
    assert all(a[0] < b[0] for a, b in zip(path, path[1:]))
    remaining, peak = try_front_cut(pocket, stock, path, 1., contact_limit=60., sample_step=.05)
    assert stock.area - remaining.area == pytest.approx(.821, abs=.002)
    assert peak < 60. and Point(path[-1]).distance(remaining) >= 1.


def test_wide_bite_holds_immersion_between_tangent_ramps():
    pocket, stock = box(0, 0, 24, 14), box(5, 5, 15, 12)
    path = eased_front_bite(((5., 5.), (15., 5.)), 1., .25, .25, .0025, ramp_fraction=.25)
    assert [(x, y) for x, y in path if y == 4.25] == [(7.5, 4.25), (12.5, 4.25)]
    remaining, peak = try_front_cut(pocket, stock, path, 1., contact_limit=60., sample_step=.05)
    assert stock.area - remaining.area > 1.25
    assert peak < 60. and Point(path[-1]).distance(remaining) >= 1.


def test_straight_front_advances_at_low_contact():
    pocket = box(0, 0, 24, 12)
    stock = box(4, 5, 24, 12)
    edges = list(frontier_edges(pocket, stock))
    assert len(edges) == 2  # right and top are pocket walls
    front = next((a, b) for a, b in edges if a[1] == b[1] == 5.)
    assert front == ((4., 5.), (24., 5.))
    assert straight_advance(pocket, front, 1., .25, lead=1.) is None
    # Reserve the wall end for a corner strategy instead of extending into it.
    front = (front[0], (22., 5.))
    path = straight_advance(pocket, front, 1., .25, lead=1.)
    assert path == [(3., 4.25), (22., 4.25)]
    report, _, rows = replay_strokes(pocket, stock, 1., -.5,
                                     [(1, 'G1', path, math.dist(*path), True)], .0025, .025)
    assert report['outside_pocket_sweep_mm2'] == 0.
    assert 4.5 < rows[0]['removed_stock_mm2'] < 5.
    assert 40. < report['sampled_peak_contact_deg'] < 60.


def test_committed_cut_exposes_a_new_front_and_rejects_overload():
    pocket = box(0, 0, 24, 12)
    stock = box(4, 5, 24, 12)
    first = straight_advance(pocket, ((4., 5.), (22., 5.)), 1., .25, lead=1.)
    assert try_front_cut(pocket, stock, first, 1., contact_limit=30., sample_step=.025) is None
    after, peak = try_front_cut(pocket, stock, first, 1., contact_limit=60., sample_step=.025)
    assert peak < 60. and stock.area == 140.
    assert ((4., 5.25), (22., 5.25)) in list(frontier_edges(pocket, after))
    assert try_front_cut(pocket, after, first, 1., contact_limit=60., sample_step=.025) is None
    second = straight_advance(pocket, ((4., 5.25), (21.5, 5.25)), 1., .25, lead=1.)
    final, second_peak = try_front_cut(pocket, after, second, 1., contact_limit=60., sample_step=.025)
    assert after.area - final.area > 4.
    assert second_peak < 60.
    assert ((4., 5.5), (21.5, 5.5)) in list(frontier_edges(pocket, final))


def test_stock_hole_is_an_interior_frontier_not_a_pocket_wall():
    pocket = box(0, 0, 20, 20)
    stock = pocket.difference(box(5, 5, 15, 15))
    edges = list(frontier_edges(pocket, stock))
    assert len(edges) == 4
    assert ((15., 5.), (5., 5.)) in edges  # material below, clearance above


@pytest.mark.parametrize('immersion', [0., 1., float('nan')])
def test_invalid_immersion_is_not_a_proposal(immersion):
    with pytest.raises(ValueError):
        straight_advance(box(0, 0, 20, 20), ((4., 5.), (12., 5.)), 1., immersion)
