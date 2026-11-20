import numpy as np
from shapely.geometry import box

from gcodeproducer.core.cam.adaptive_finish import checked_finish


def test_finish_accepts_light_stock_but_rejects_same_move_in_heavy_stock():
    contour = np.array([[2., 2.], [8., 2.], [8., 8.], [2., 8.]])
    region = box(1, 1, 9, 9)
    light = box(3, 1.85, 7, 1.95)
    heavy = box(3, 1, 7, 3)
    opts = dict(travel_feed=800, z_feed=150, lift=3)
    result = checked_finish(contour[0], [contour], region, light, 1., .18, **opts)
    assert result is not None and result.contours == 1 and result.remaining.is_empty
    assert checked_finish(contour[0], [contour], region, light, 1., .02, **opts) is None
    assert checked_finish(contour[0], [contour], region, heavy, 1., .18, **opts) is None
    np.testing.assert_array_equal(result.points[0], result.points[-1])


def test_finish_rejects_an_unverified_transfer():
    contour = np.array([[5., 2.], [8., 2.], [8., 8.], [5., 8.]])
    region = box(1, 1, 9, 9)
    material = box(2.5, 1.5, 3.5, 2.5).union(box(6, 1.85, 7, 1.95))
    result = checked_finish((1.1, 2.), [contour], region, material, 1., .18,
                            travel_feed=800, z_feed=150, lift=3)
    assert result is None
