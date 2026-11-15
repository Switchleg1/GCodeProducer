import struct

import numpy as np
import pytest

from conftest import write_boxes
from gcodeproducer.core import geometry
from gcodeproducer.core.placement import (Placement, bed_rect, euler_matrix, fits, matrix_to_euler,
                                          overhang_faces)


@pytest.fixture
def cube(cube_stl):
    return geometry.load_stl(cube_stl)


@pytest.mark.parametrize("a", [(10, 20, 30), (90, 0, 0), (0, 90, 45), (-30, -60, 170), (180, 0, 0)])
def test_euler_roundtrip(a):
    assert np.allclose(euler_matrix(*matrix_to_euler(euler_matrix(*a))), euler_matrix(*a))


def test_position_and_drop(cube):
    lo, hi = Placement(x=50, y=60).apply(cube).bounds
    assert np.allclose((lo + hi)[:2] / 2, [50, 60]) and lo[2] == pytest.approx(0)


def test_auto_xy_and_keep(cube):
    lo, hi = Placement().apply(cube, auto_xy=(110, 110)).bounds
    assert np.allclose((lo + hi)[:2] / 2, [110, 110])
    lo, hi = Placement().apply(cube).bounds                 # no auto: keep original XY
    assert np.allclose((lo + hi)[:2] / 2, [10, 10])


def test_rotation_and_scale(cube):
    lo, hi = Placement(rz=45).apply(cube).bounds
    assert hi[0] - lo[0] == pytest.approx(20 * 2 ** 0.5, abs=1e-6)
    lo, hi = Placement(scale=50).apply(cube).bounds
    assert np.allclose(hi - lo, 10)


def test_lay_flat(cube):
    p = Placement(rx=37, ry=12)
    assert (np.ptp(p.apply(cube).vertices[:, 2])) > 21
    p.lay_flat(cube)
    assert np.ptp(p.apply(cube).vertices[:, 2]) == pytest.approx(20, abs=1e-6)


def test_place_on_face_and_rotate_by(cube):
    p = Placement()
    p.place_on_face([1, 0, 0])          # the +X face goes down onto the bed
    assert np.allclose(p.rotation() @ [1, 0, 0], [0, 0, -1])
    p2 = Placement()
    p2.rotate_by("x", 90)
    p2.rotate_by("x", 90)
    assert (p2.rx, p2.ry, p2.rz) == pytest.approx((180, 0, 0))


def test_overhangs(tmp_path, cube):
    t = geometry.load_stl(write_boxes(tmp_path / "t.stl", [(10, 10, 0, 20, 20, 15), (0, 0, 15, 30, 30, 18)]))
    assert overhang_faces(t.vertices, t.triangles, 50).sum() == 2    # plate underside; the foot is on the bed
    assert overhang_faces(cube.vertices, cube.triangles, 50).sum() == 0
    # a cube tilted 20 deg rests on an edge: its old bottom (20 deg from down) needs support...
    m = Placement(rx=20).apply(cube)
    assert overhang_faces(m.vertices, m.triangles, 50).sum() == 2
    # ...tilted 45 deg every face is within a 50 deg overhang limit
    m = Placement(rx=45).apply(cube)
    assert overhang_faces(m.vertices, m.triangles, 50).sum() == 0


def test_fits(cube):
    rect = (0, 0, 220, 220, 250)
    assert fits(Placement(x=110, y=110).apply(cube), rect)
    assert not fits(Placement(x=5, y=110).apply(cube), rect)
    assert not fits(Placement(x=110, y=110, scale=2000).apply(cube), rect)


def test_bed_rect_origin_center(libset):
    from gcodeproducer.core.profiles import Profile
    m = Profile("machine", "delta", workflow="fdm", values={"bed_x": 200, "bed_y": 200, "origin_center": True})
    assert bed_rect(m, "fdm")[:4] == (-100, -100, 100, 100)


def test_inside_out_stl_is_fixed(tmp_path, cube_stl):
    # rewrite the cube with every triangle reversed
    data = open(cube_stl, "rb").read()
    n = struct.unpack_from("<I", data, 80)[0]
    out = bytearray(data[:84])
    for i in range(n):
        v = struct.unpack_from("<12fH", data, 84 + i * 50)
        out += struct.pack("<12fH", *v[0:3], *v[9:12], *v[6:9], *v[3:6], v[12])
    f = tmp_path / "inv.stl"
    f.write_bytes(bytes(out))
    m = geometry.load_stl(str(f))
    assert geometry.signed_volume(m) == pytest.approx(8000, rel=1e-6)
