import pytest
from shapely.geometry import Polygon, box

from tools.hsm_tangent_link import cleared_tangent_link


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
