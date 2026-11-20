from collections import Counter

import pytest
from shapely.geometry import box

from tools.hsm_front_choice import choose_front_cut
from tools.hsm_front_corner import filleted_corner, frontier_corner_poses


def _choose(pocket, stock, pose, cuts, limit=60.):
    return choose_front_cut(pocket, stock, pose, cuts, 1., contact_limit=limit,
                            sample_step=.05, link_handle=.5)


def test_selects_efficient_front_from_either_candidate_order():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    pose = ((3., 4.25), (1., 0.))
    poses = next(p for p in frontier_corner_poses(pocket, stock, 1., .25, lead=1.)
                 if p[0] == (4., 4.25))
    corner = filleted_corner(*poses, 1.5, .00025)
    short = [(4., 4.25), (7., 4.25)]
    for cuts in ([short, corner], [corner, short]):
        choice = _choose(pocket, stock, pose, cuts)
        assert choice.cut == corner
        assert choice.link[0] == pose[0] and choice.link[-1] == corner[0]
        assert choice.removed_mm2 == pytest.approx(4.241, abs=.001)
        assert choice.peak_deg < 60 and stock.area == 70.


def test_priority_region_changes_ranking_without_bypassing_contact_limit():
    pocket = box(0, 0, 24, 18)
    stock = box(5, 5, 9, 7).union(box(14, 3, 18, 5))
    pose = ((3., 4.25), (1., 0.))
    near = [(4., 4.25), (10., 4.25)]
    far = [(13., 2.25), (19., 2.25)]
    assert _choose(pocket, stock, pose, [far, near]).cut == near
    options = dict(sample_step=.05, link_handle=.5, priority_region=box(12, 0, 24, 18))
    assert choose_front_cut(pocket, stock, pose, [far, near], 1., contact_limit=60., **options).cut == far
    assert choose_front_cut(pocket, stock, pose, [far, near], 1., contact_limit=20., **options) is None


def test_blocked_access_and_overload_both_return_no_choice():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    pose = ((3., 4.25), (1., 0.))
    cut = [(4., 4.25), (12., 4.25)]
    rib = box(3.4, 5.1, 3.6, 5.2)
    assert _choose(pocket, stock.union(rib), pose, [cut]) is None
    assert _choose(pocket, stock, pose, [cut], limit=20.) is None


def test_counts_first_failed_gate_without_changing_selection():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    xy = (3., 4.25)
    counts = Counter()
    choice = choose_front_cut(pocket, stock, (xy, (1., 0.)),
                              [[xy, (28., 4.25)], [xy, (3.5, 4.25)], [xy, (12., 4.25)]],
                              1., contact_limit=20., sample_step=.05, link_handle=.5, diagnostics=counts)
    assert choice is None
    assert counts == {'cut_boundary': 1, 'no_removal': 1, 'contact_limit': 1}


def test_distinguishes_blocked_start_from_blocked_link_interior():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    xy = (2., 4.25)
    stock = stock.union(box(2.95, 5.1, 3.05, 5.2))
    counts = Counter()
    choice = choose_front_cut(pocket, stock, (xy, (1., 0.)),
                              [[(4., 4.25), (12., 4.25)], [(6., 4.25), (12., 4.25)]],
                              1., contact_limit=60., sample_step=.05, link_handle=.5, diagnostics=counts)
    assert choice is None
    assert counts == {'link_clearance': 1, 'start_clearance': 1}


def test_same_pose_is_not_a_bypass_for_clearance_or_heading():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    cut = [(4., 4.25), (12., 4.25)]
    assert _choose(pocket, stock, (cut[0], (1., 0.)), [cut]).link == [cut[0]]
    assert _choose(pocket, stock, (cut[0], (-1., 0.)), [cut]) is None
    blocked = [(6., 4.25), (12., 4.25)]
    assert _choose(pocket, stock, (blocked[0], (1., 0.)), [blocked]) is None
