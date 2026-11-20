import pytest

from tools.hsm_corner_fixtures import corner_slot_fixtures
from tools.hsm_front_corner import filleted_corner, try_corner_advance


@pytest.mark.parametrize('direction', [1., -1.])
def test_fillet_trims_each_leg_and_turns_to_either_side(direction):
    points = filleted_corner((0., 0.), (6., 0.), (6., direction*6.), 2., .001)
    assert points[0] == (0., 0.) and points[-1] == (6., direction*6.)
    assert points[1] == pytest.approx((4., 0.))
    assert points[-2] == pytest.approx((6., direction*2.))
    assert all(4. <= x <= 6. and 0. <= direction*y <= 2. for x, y in points[1:-1])


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
