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


def test_blocked_access_and_overload_both_return_no_choice():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    pose = ((3., 4.25), (1., 0.))
    cut = [(4., 4.25), (12., 4.25)]
    rib = box(3.4, 5.1, 3.6, 5.2)
    assert _choose(pocket, stock.union(rib), pose, [cut]) is None
    assert _choose(pocket, stock, pose, [cut], limit=20.) is None


def test_same_pose_is_not_a_bypass_for_clearance_or_heading():
    pocket, stock = box(0, 0, 24, 18), box(5, 5, 15, 12)
    cut = [(4., 4.25), (12., 4.25)]
    assert _choose(pocket, stock, (cut[0], (1., 0.)), [cut]).link == [cut[0]]
    assert _choose(pocket, stock, (cut[0], (-1., 0.)), [cut]) is None
    blocked = [(6., 4.25), (12., 4.25)]
    assert _choose(pocket, stock, (blocked[0], (1., 0.)), [blocked]) is None
