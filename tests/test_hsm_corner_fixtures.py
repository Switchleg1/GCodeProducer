import math

import pytest
from shapely.geometry import Point

from tools.check_cambam_pocket import level_moves, replay_strokes
from tools.hsm_corner_fixtures import corner_slot_fixtures
from tools.hsm_corner_trial import compare_local_cleanup, compare_staged_cleanup


@pytest.mark.parametrize('name, stock_area, unreachable', [
    ('sharp_corner', 12.75, .2147),
    ('round_corner', 11.9452, .0001),
    ('wide_slot', 162., .4294),
    ('narrow_slot', 64.8, .4294),
])
def test_fixture_starts_in_clearance_and_pins_reachable_stock(name, stock_area, unreachable):
    pocket, stock, xy, heading = corner_slot_fixtures()[name]
    assert pocket.is_valid and stock.is_valid and pocket.covers(stock)
    radius = 1.
    assert pocket.buffer(-radius, quad_segs=64).covers(Point(xy))
    assert stock.distance(Point(xy)) >= radius
    assert heading == (1., 0.)
    reachable = pocket.buffer(-radius, quad_segs=64).buffer(radius, quad_segs=64)
    assert stock.area == pytest.approx(stock_area, abs=.001)
    assert stock.difference(reachable).area == pytest.approx(unreachable, abs=.001)


def _replay_reference(name, tail, step):
    pocket, stock, (x, y), _ = corner_slot_fixtures()[name]
    depth, chord_error = -.5, .00025
    text = f'G21\nG90\nG0 X{x} Y{y} Z1\nG1 Z{depth}\n{tail}'
    moves = ((*move, True) for move in level_moves(text, depth, chord_error))
    return replay_strokes(pocket, stock, 1., depth, moves, chord_error, step)


def test_slot_reference_separates_cleared_approach_and_slotting():
    report, _, rows = _replay_reference('narrow_slot', 'G1 X3.5\nG1 X12\n', .05)
    assert report['air_distance_mm'] == .5
    assert rows[0]['sampled_peak_contact_deg'] == 0.
    assert rows[0]['new_sweep_mm2'] > 0.  # new to the replay, but initially clear
    assert rows[1]['sampled_peak_contact_deg'] == pytest.approx(2*math.degrees(math.acos(-.025)), abs=.05)
    assert rows[1]['removed_stock_mm2'] > 0.


def test_rounded_reference_leaves_more_reachable_stock_in_sharp_corner():
    tail = 'G1 X7 Y1\nG1 X20\nG3 X23 Y4 I0 J3\nG1 Y10\n'
    rounded, _, _ = _replay_reference('round_corner', tail, .05)
    sharp, _, _ = _replay_reference('sharp_corner', tail, .05)
    assert rounded['outside_pocket_sweep_mm2'] < .001  # polygon approximation
    assert rounded['reachable_residual_mm2'] < .001
    assert sharp['reachable_residual_mm2'] > .5
    assert rounded['sampled_peak_contact_deg'] < 100.


@pytest.mark.parametrize('step', [.05, .025])
def test_local_cleanup_reduces_residual_but_fails_trial_contact_limit(step):
    (rough, _, _), (finished, _, rows) = compare_local_cleanup(contact_step=step)
    assert rough['reachable_residual_mm2'] > 2.
    assert finished['reachable_residual_mm2'] < .1
    assert finished['outside_pocket_sweep_mm2'] < 1e-8
    assert all(row['removed_stock_mm2'] < 1e-8 for row in rows[4:6])
    assert rough['sampled_peak_contact_deg'] < 95.
    assert finished['sampled_peak_contact_deg'] > 130.  # reject at the 95° trial limit


@pytest.mark.parametrize('step', [.05, .025, .0125])
def test_staged_cleanup_limits_contact_without_trading_away_coverage(step):
    _, (trial, _, rows) = compare_staged_cleanup((1.8, .8, .2), step)
    assert trial['reachable_residual_mm2'] == pytest.approx(.0946, abs=.0001)
    assert trial['outside_pocket_sweep_mm2'] < 1e-8
    assert trial['sampled_peak_contact_deg'] < 95.
    for index in range(4, len(rows), 5):
        connectors = rows[index:index+2]
        assert all(row['removed_stock_mm2'] < 1e-8 for row in connectors)
        assert sum(row['removed_stock_mm2'] for row in rows[index+2:index+5]) > 0.


@pytest.mark.parametrize('step', [.05, .0125])
def test_tangent_returns_shorten_travel_without_more_engagement_or_residual(step):
    _, (baseline, _, _) = compare_staged_cleanup((1.8, .8, .2), step)
    _, (blended, _, rows) = compare_staged_cleanup((1.8, .8, .2), step, blended_returns=True)
    assert baseline['air_distance_mm'] - blended['air_distance_mm'] > 8.7
    assert baseline['feed_distance_mm'] - blended['feed_distance_mm'] > 8.7
    assert blended['reachable_residual_mm2'] == pytest.approx(baseline['reachable_residual_mm2'], abs=1e-8)
    assert blended['outside_pocket_sweep_mm2'] < 1e-8
    assert blended['sampled_peak_contact_deg'] == pytest.approx(baseline['sampled_peak_contact_deg'])
    transfers = [row for row in rows if row['motion'] == 'blend']
    assert len(transfers) == 3
    assert all(row['removed_stock_mm2'] < 1e-8 for row in transfers)


@pytest.mark.parametrize('fillets', [(), (.8, 1.8), (1.2, 1.2), (3.,), (0.,)])
def test_staged_cleanup_requires_strictly_decreasing_positive_radii(fillets):
    with pytest.raises(ValueError, match='decrease strictly'):
        compare_staged_cleanup(fillets)
