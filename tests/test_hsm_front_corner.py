import pytest
from shapely.geometry import box

from tools.hsm_corner_fixtures import corner_slot_fixtures
from tools.hsm_front_corner import filleted_corner, frontier_corner_poses, roll_off, try_corner_advance


@pytest.mark.parametrize('direction', [1., -1.])
def test_fillet_trims_each_leg_and_turns_to_either_side(direction):
    points = filleted_corner((0., 0.), (6., 0.), (6., direction*6.), 2., .001)
    assert points[0] == (0., 0.) and points[-1] == (6., direction*6.)
    assert points[1] == pytest.approx((4., 0.))
    assert points[-2] == pytest.approx((6., direction*2.))
    assert all(4. <= x <= 6. and 0. <= direction*y <= 2. for x, y in points[1:-1])


def test_adjacent_live_edges_supply_a_checked_corner_without_manual_waypoints():
    pocket = box(0, 0, 24, 18)
    stock = box(5, 5, 15, 12)
    candidates = list(frontier_corner_poses(pocket, stock, 1., .25, lead=1.))
    assert len(candidates) == 4
    poses = next(poses for poses in candidates if poses[0] == (4., 4.25))
    assert poses == ((4., 4.25), (15.75, 4.25), (15.75, 12.))
    _, remaining, peak = try_corner_advance(pocket, stock, *poses, 1., turn_radius=1.5,
                                            chord_error=.00025, contact_limit=60., sample_step=.05)
    assert stock.area - remaining.area == pytest.approx(4.241, abs=.001)
    assert peak == pytest.approx(45.14, abs=.1)


def test_frontier_corners_do_not_join_through_a_pocket_wall():
    pocket = box(0, 0, 24, 18)
    assert list(frontier_corner_poses(pocket, box(4, 5, 24, 18), 1., .25)) == [
        ((3.25, 18.), (3.25, 4.25), (24., 4.25))]


def test_roll_off_preserves_straight_cut_and_turns_away_from_stock():
    straight = [(1., 3.), (6., 3.)]
    path = roll_off(straight, 1., .001)
    assert path[:2] == straight
    assert path[-1] == pytest.approx((7., 2.))
    assert all(6. < x <= 7. and 2. <= y < 3. for x, y in path[2:])


def test_fillet_rejects_a_reversal_or_insufficient_room():
    assert filleted_corner((0, 0), (1, 0), (0, 0), .2, .001) is None
    assert filleted_corner((0, 0), (1, 0), (1, 1), 2., .001) is None


@pytest.mark.parametrize('step', [.05, .025])
def test_corner_and_straights_commit_together_or_not_at_all(step):
    pocket, stock, _, _ = corner_slot_fixtures()['round_corner']
    initial_area = stock.area
    # Keep the chord chain off the discretized pocket boundary.
    start, vertex, end = (7., 1.002), (22.998, 1.002), (22.998, 10.)
    args = pocket, stock, start, vertex, end, 1.
    settings = dict(chord_error=.00025, sample_step=step)
    assert try_corner_advance(*args, turn_radius=3., contact_limit=60., **settings) is None
    assert try_corner_advance(*args, turn_radius=.2, contact_limit=95., **settings) is None
    points, remaining, peak = try_corner_advance(*args, turn_radius=3., contact_limit=95., **settings)
    assert points[0] == start and points[-1] == end
    assert stock.area == initial_area
    assert initial_area - remaining.area > 11.8
    assert 60. < peak < 75.
