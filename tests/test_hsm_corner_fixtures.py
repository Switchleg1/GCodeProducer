import pytest
from shapely.geometry import Point

from tools.hsm_corner_fixtures import corner_slot_fixtures


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
