import math

import pytest
from shapely.geometry import box

from tools.check_cambam_pocket import replay_strokes
from tools.hsm_straight_front import frontier_edges, straight_advance


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
