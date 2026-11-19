import numpy as np
import pytest
from shapely.geometry import Point

from gcodeproducer.core.fdm.support import slice_layers
from gcodeproducer.core.fdm.wall_regions import slice_region
from gcodeproducer.core.geometry.kernel import load_stl
from gcodeproducer.core.jobs.job import Job
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.fdm.fdm_slice import FDMSlice
from tests.conftest import box_tris, write_boxes, write_tris


def region(layer):
    return slice_region(layer.contours)


def test_nested_outward_shell_does_not_punch_a_hole_in_base(tmp_path):
    mesh = load_stl(write_boxes(tmp_path / 'base.stl', [(0, 0, 0, 10, 10, 3), (1, 1, .5, 9, 9, 2)]))
    original = mesh.triangles.copy()
    job = Job('fdm', None, mesh=mesh)
    stage = FDMSlice()
    params = {'layer_height': .5}
    stage.run(job, stage.resolve(params), StageContext())
    assert region(job.layers[1]).area == pytest.approx(36)
    assert len(job.warnings) == 1 and 'Merge overlapping shells' in job.warnings[0]
    job.warnings.clear()
    stage.run(job, stage.resolve({**params, 'merge_shells': True}), StageContext())
    assert all(region(layer).area == pytest.approx(100) for layer in job.layers)
    assert not job.warnings
    assert np.array_equal(mesh.triangles, original)


def test_merge_partial_overlap_and_keep_inward_cavity(tmp_path):
    a = box_tris(0, 0, 0, 10, 10, 3)
    b = box_tris(8, 2, .25, 12, 9, 2)
    cavity = [(n, a, c, b) for n, a, b, c in box_tris(2, 2, .4, 6, 6, 2.1)]
    island = box_tris(3, 3, .6, 4, 4, 1.8)
    mesh = load_stl(write_tris(tmp_path / 'cavity.stl', a + b + cavity + island))
    hits = []
    layers = slice_layers(mesh, .5, merge_shells=True, overlap_layers=hits)
    assert 1 in hits
    r = region(layers[1])
    assert r.area == pytest.approx(100 + 14 - 16 + 1)
    assert r.covers(Point(9, 5))                              # intersecting outward shells
    assert not r.covers(Point(5, 5))                          # intentional cavity
    assert r.covers(Point(3.5, 3.5))                          # outward island inside the cavity


@pytest.mark.parametrize('open_shell', [False, True])
def test_shell_merge_does_not_change_disjoint_or_open_mesh(tmp_path, open_shell):
    a = box_tris(0, 0, 0, 10, 10, 3)
    b = (box_tris(1, 1, .5, 9, 9, 2)[:-1] if open_shell else box_tris(11, 0, 0, 15, 10, 3))
    mesh = load_stl(write_tris(tmp_path / 'unchanged.stl', a + b))
    hits = []
    checked = slice_layers(mesh, .5, merge_shells=True, overlap_layers=hits)
    original = slice_layers(mesh, .5)
    assert not hits
    for a, b in zip(checked, original):
        assert len(a.contours) == len(b.contours)
        assert all(np.array_equal(x, y) for x, y in zip(a.contours, b.contours))
