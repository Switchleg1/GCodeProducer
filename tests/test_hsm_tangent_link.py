import pytest
from shapely.geometry import LineString, Polygon, box

from tools.hsm_tangent_link import cleared_tangent_detour, cleared_tangent_link


def _link(pocket, stock, margin=0.):
    return cleared_tangent_link(pocket, stock, 1., (2., 3.), (8., 3.),
                                (1., 0.), (1., 0.), .5, margin=margin)


def test_link_preserves_endpoints_and_accepts_a_clear_corridor():
    points = _link(box(0, 0, 10, 6), box(4, 4.5, 6, 5))
    assert points[0] == (2., 3.) and points[-1] == (8., 3.)
    assert all(y == pytest.approx(3.) for _, y in points)


def test_rejects_stock_beside_centerline_even_between_chord_vertices():
    rib = box(4.009, 3.99, 4.010, 4.1)
    assert _link(box(0, 0, 10, 6), rib) is None


def test_rejects_an_island_not_crossed_by_the_centerline():
    envelope = box(0, 0, 10, 6)
    island = box(4, 3.5, 6, 4)
    pocket = Polygon(envelope.exterior, [island.exterior])
    assert _link(pocket, Polygon()) is None


def test_margin_rejects_boundary_tangency():
    pocket = box(0, 2, 10, 6)
    assert _link(pocket, Polygon()) is not None
    assert _link(pocket, Polygon(), margin=.002) is None


@pytest.fixture
def off_center_island():
    island = box(10, 3, 14, 9)
    pocket = box(0, 0, 24, 16).difference(island)
    poses = tuple((xy, (1., 0.)) for xy in ((3., 6.), (12., 12.), (21., 6.)))
    return pocket, poses


def test_off_center_island_needs_both_legs_of_the_wider_detour(off_center_island):
    pocket, (start, via, end) = off_center_island
    stock = box(4, 0, 8, 2)
    assert cleared_tangent_link(pocket, stock, 1., start[0], end[0], start[1], end[1], 2., margin=.1) is None
    lower = ((12., 1.5), via[1])
    assert cleared_tangent_detour(pocket, stock, 1., start, lower, end, 2., margin=.1) is None
    points = cleared_tangent_detour(pocket, stock, 1., start, via, end, 2., margin=.1)
    assert points.count(via[0]) == 1
    assert points[0] == start[0] and points[-1] == end[0]
    axis = LineString(points)
    assert axis.length == pytest.approx(21.902, abs=.001)
    assert axis.distance(pocket.boundary) > 1.6
    assert axis.distance(stock) >= 1.1


@pytest.mark.parametrize('x', [7, 17])
def test_stock_can_block_either_leg_without_returning_a_partial_link(off_center_island, x):
    pocket, poses = off_center_island
    stock = box(x, 6, x+.5, 12)
    assert cleared_tangent_detour(pocket, stock, 1., *poses, 2., margin=.1) is None
