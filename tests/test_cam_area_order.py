"""Separate machining areas: area-first vs depth-first, persistence and defaults."""
import numpy as np
import pytest

from gcodeproducer.core import app_settings
from gcodeproducer.core.cam import CAMSetup, Depth, generate
from gcodeproducer.core.geometry import Mesh
from gcodeproducer.core.cam_paths import machining_areas
from gcodeproducer.core.job import Path
from gcodeproducer.stages.base import StageContext
from gcodeproducer.stages.cam_emit import CAMEmit
from tests.test_pocket_bounds import stepped_part, floor_ref, job_for


def two_pockets(libset):
    first = stepped_part()
    vertices = np.vstack((first.vertices, first.vertices + [60, 0, 0]))
    triangles = np.vstack((first.triangles, first.triangles + len(first.vertices)))
    mesh = Mesh(vertices, triangles)
    a = floor_ref(first)
    from gcodeproducer.core.cam import Reference
    b = Reference("face", [a.indices[0] + len(first.triangles)])
    return job_for(mesh, [a, b], libset)


@pytest.mark.parametrize("strategy", ["contour", "raster"])
@pytest.mark.parametrize("order", ["area", "depth"])
def test_two_pockets_schedule_and_stock_checks(libset, strategy, order):
    job, op = two_pockets(libset)
    op.strategy, op.area_order = strategy, order
    generate(job, StageContext())
    expected = [(a, z) for a in (0, 1) for z in (-1., -2., -3., -4.)]
    if order == "depth":
        expected.sort(key=lambda p: (-p[1], p[0]))
    assert [(l.cam_area, l.z) for l in job.layers] == expected
    # Annular pocket + its island and all offset fronts stay together, not one area per loop.
    for layer in job.layers:
        assert len(layer.paths) > 1
        x = np.concatenate([p.points[:, 0] for p in layer.paths])
        assert x.max() < 30 if layer.cam_area == 0 else x.min() > 30
        assert not layer.paths[0].stay_down
        assert layer.cam_operation_key == (0, 0)
    CAMEmit().run(job, CAMEmit.resolve({}), StageContext())
    assert not [w for w in job.warnings if "rapid motion" in w or "spindle stopped" in w]
    assert len(job.material_results) == 2   # still one operation, not a snapshot per area
    assert job.material_results[-1]["last_layer"] == len(job.layers)-1
    assert job.program.layer_z == [z for _, z in expected]  # non-monotonic Z remains execution order


@pytest.mark.parametrize("kind", ["profile", "slot", "engrave", "drill"])
@pytest.mark.parametrize("order", ["area", "depth"])
def test_non_pocket_area_scheduling(libset, kind, order):
    from gcodeproducer.core.cam import Reference
    job, op = two_pockets(libset)
    n = len(stepped_part().vertices)
    op.kind, op.area_order = kind, order
    op.geometry = [Reference("edge", [96, 97]), Reference("edge", [n+96, n+97])]
    op.end = Depth("absolute", -2)
    generate(job, StageContext())
    expected = [(0, -1), (0, -2), (1, -1), (1, -2)]
    if order == "depth":
        expected.sort(key=lambda p: (-p[1], p[0]))
    assert [(l.cam_area, l.z) for l in job.layers] == expected


def test_area_order_serialization_and_validation(libset, tmp_path):
    job, op = two_pockets(libset)
    assert op.area_order == "area"
    op.area_order = "depth"
    assert CAMSetup.from_dict(job.cam_setup.to_dict()).groups[0].operations[0].area_order == "depth"
    old = job.cam_setup.to_dict()
    del old["groups"][0]["operations"][0]["area_order"]
    assert CAMSetup.from_dict(old).groups[0].operations[0].area_order == "area"
    app_settings.save({"default_area_order": "depth"}, tmp_path)
    assert app_settings.load(tmp_path)["default_area_order"] == "depth"
    assert app_settings.validated({"default_area_order": "bad"})["default_area_order"] == "area"
    op.area_order = "bad"
    with pytest.raises(ValueError, match="area order"):
        generate(job, StageContext())


def test_profile_drill_and_open_paths_are_independent_areas():
    paths = [Path("cut", np.array([[0., 0.], [1., 0.]])), Path("cut", np.array([[10., 0.], [11., 0.]]))]
    for kind in ("profile", "drill", "engrave", "slot"):
        assert machining_areas(paths, kind) == [[paths[0]], [paths[1]]]


def test_area_order_respects_air_removal_from_prior_operation(libset):
    import copy
    job, first = two_pockets(libset)
    first.geometry = first.geometry[:1]     # clear only left pocket to -2
    first.end = Depth("absolute", -2)
    second = copy.deepcopy(first)
    second.geometry = two_pockets(libset)[1].geometry
    second.name, second.end = "finish both", Depth("absolute", -4)
    job.cam_setup.groups[0].operations.append(second)
    generate(job, StageContext())
    later = [l for l in job.layers if l.cam_operation == second.name]
    assert [(l.cam_area, l.z) for l in later] == [(0, -3), (0, -4), (1, -1), (1, -2), (1, -3), (1, -4)]
