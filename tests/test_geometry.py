import numpy as np

from gcodeproducer.core import geometry


def test_load_and_bounds(cube_stl):
    m = geometry.load_stl(cube_stl)
    lo, hi = m.bounds
    assert np.allclose(lo, [0, 0, 0])
    assert np.allclose(hi, [20, 20, 20])
    assert len(m.vertices) == 8          # welded


def test_slice_square(cube_stl):
    m = geometry.load_stl(cube_stl)
    contours = geometry.slice_z(m, 10.0)
    assert len(contours) == 1
    assert abs(abs(geometry.area(contours[0])) - 400.0) < 1e-3


def test_offset_inward(cube_stl):
    m = geometry.load_stl(cube_stl)
    c = geometry.slice_z(m, 10.0)[0]
    inner = geometry.offset(c, -1.0)
    assert inner
    # inset by 1mm on all sides -> 18x18 = 324
    assert abs(abs(geometry.area(inner[0])) - 324.0) < 2.0


def test_perimeter_loops(cube_stl):
    m = geometry.load_stl(cube_stl)
    c = geometry.slice_z(m, 10.0)
    loops = geometry.perimeter_loops(c, 0.45, 3)
    assert len(loops) == 1
    assert len(loops[0]) == 3            # three nested walls
