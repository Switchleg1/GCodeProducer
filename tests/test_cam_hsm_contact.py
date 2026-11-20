import math

import pytest
from shapely import union_all
from shapely.geometry import Polygon, box

from gcodeproducer.core.cam.hsm_contact import contact_angle, occupied_arcs


@pytest.mark.parametrize('radial_width, expected', [(0., 0.), (.25, 2*math.degrees(math.acos(.75))),
                                                  (1., 180.), (2., 360.)])
def test_straight_stock_face_contact_matches_analytic_circle(radial_width, expected):
    stock = box(1.-radial_width, -3., 3., 3.)
    assert contact_angle((0., 0.), 1., stock) == pytest.approx(expected, abs=1e-9)


def test_opposite_stock_faces_form_separate_contact_arcs():
    stock = union_all([box(.5, -3., 3., 3.), box(-3., -3., -.5, 3.)])
    arcs = occupied_arcs((0., 0.), 1., stock)
    assert len(arcs) == 3  # the positive-X patch is split by the angular seam
    assert contact_angle((0., 0.), 1., stock) == pytest.approx(240.)


def test_inside_corner_and_cleared_hole():
    corner = box(0, 0, 3, 3)
    outline = box(-3, -3, 3, 3)
    cleared = Polygon(outline.exterior.coords, [box(-2, -2, 2, 2).exterior.coords])
    assert contact_angle((0., 0.), 1., corner) == pytest.approx(90.)
    assert contact_angle((0., 0.), 1., cleared) == 0.
    assert contact_angle((0., 0.), 1., outline) == 360.


def test_translation_and_scale_do_not_change_contact():
    assert contact_angle((100., -50.), 4., box(102., -65., 120., -30.)) == pytest.approx(120.)
