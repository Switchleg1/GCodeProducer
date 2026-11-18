"""FDM inward offsets must preserve material topology on thin slices."""
import numpy as np
from shapely.geometry import LinearRing

from gcodeproducer.core.fdm.wall_regions import slice_region, wall_levels


def test_inner_wall_splits_at_thin_web():
    contour = [(0, 0), (4, 0), (4, 1.6), (6, 1.6), (6, 0), (10, 0), (10, 4),
               (6, 4), (6, 2.4), (4, 2.4), (4, 4), (0, 4)]
    levels, fill = wall_levels([contour], .45, 2)
    assert [len(loops) for loops in levels] == [1, 2]
    assert fill is levels[-1]
    region = slice_region([contour])
    for loop in levels[0] + levels[1]:
        ring = LinearRing(loop)
        assert ring.is_simple and region.covers(ring)


def test_guard_thin_rim_and_keep_hole_out_of_fill():
    outer = [(0, 0), (8, 0), (8, 8), (0, 8)]
    hole = [(1, 2), (5, 2), (5, 6), (1, 6)]
    levels, fill = wall_levels([outer, hole], .45, 2)
    assert len(levels[0]) == 2
    assert len(fill) == 1  # the deep inset opens the hole to the outside
    region = slice_region([outer, hole])
    assert all(region.covers(LinearRing(loop)) for level in levels for loop in level)
    assert slice_region(fill).intersection(slice_region([hole])).area == 0


def test_no_infill_when_requested_inner_wall_does_not_fit():
    contour = np.array([(0, 0), (8, 0), (8, .8), (0, .8)])
    levels, fill = wall_levels([contour], .45, 2)
    assert len(levels[0]) == 1 and not levels[1] and not fill
