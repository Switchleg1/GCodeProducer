import numpy as np
from shapely.geometry import LineString, Polygon, box

from gcodeproducer.core.cam.adaptive_rounding import rounded_loop

from gcodeproducer.core.cam.adaptive_finish import checked_finish


def test_finish_accepts_light_stock_but_rejects_same_move_in_heavy_stock():
    contour = np.array([[2., 2.], [8., 2.], [8., 8.], [2., 8.]])
    region = box(1, 1, 9, 9)
    light = box(3, 1.85, 7, 1.95)
    heavy = box(3, 1, 7, 3)
    opts = dict(travel_feed=800, z_feed=150, lift=3)
    start = (4., 8.)
    result = checked_finish(start, [contour], region, light, 1., .18, **opts)
    assert result is not None and result.contours == 1 and result.remaining.is_empty
    assert checked_finish(start, [contour], region, light, 1., .02, **opts) is None
    assert checked_finish(start, [contour], region, heavy, 1., .18, **opts) is None
    np.testing.assert_array_equal(result.points[0], result.points[-1])


def test_rounding_keeps_long_lines_and_blends_each_right_angle():
    loop = np.array([[0., 0.], [20., 0.], [20., 8.], [0., 8.]])
    rounded = rounded_loop(loop, 1.)
    assert box(0, 0, 20, 8).covers(LineString(np.vstack((rounded, rounded[0]))))
    assert any(np.allclose(p, [1., 0.]) for p in rounded)
    assert any(np.allclose(p, [19., 0.]) for p in rounded)
    assert not any(np.array_equal(p, [0., 0.]) for p in rounded)
    edges = np.roll(rounded, -1, axis=0) - rounded
    unit = edges / np.linalg.norm(edges, axis=1)[:, None]
    angles = np.arccos(np.clip((unit*np.roll(unit, 1, axis=0)).sum(axis=1), -1., 1.))
    assert np.rad2deg(angles.max()) <= 10.0001
    assert np.linalg.norm(edges, axis=1).max() == 18.


def test_finish_rejects_blend_across_a_protected_reentrant_corner():
    contour = np.array([[0., 0.], [10., 0.], [10., 4.], [4., 4.], [4., 10.], [0., 10.]])
    region = Polygon(contour)
    stock = box(5, .01, 6, .07)
    assert checked_finish((2., 0.), [contour], region, stock, 1., .18,
                          travel_feed=800, z_feed=150, lift=3) is None


def test_finish_rejects_an_unverified_transfer():
    contour = np.array([[5., 2.], [8., 2.], [8., 8.], [5., 8.]])
    region = box(1, 1, 9, 9)
    material = box(2.5, 1.5, 3.5, 2.5).union(box(6, 1.85, 7, 1.95))
    result = checked_finish((1.1, 2.), [contour], region, material, 1., .18,
                            travel_feed=800, z_feed=150, lift=3)
    assert result is None
