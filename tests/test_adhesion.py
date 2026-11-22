import json

import numpy as np
import pytest

from gcodeproducer.core import geometry
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.process import ProcessPreset
from gcodeproducer.core.session import build_job, load_mesh, slice_job


def _slice(libset, cube_stl, **skirt):
    pipe = SlicePipeline.default(wf.FDM)
    pipe.step("fdm_skirt_brim").params.update(skirt)
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"),
                    material=libset["material"].get("pla"), nozzle=libset["nozzle"].get("0-4-mm"),
                    mesh=load_mesh(cube_stl))
    return slice_job(job, pipe)


def _skirt_xy(prog, layer=0):
    from gcodeproducer.core import sim
    s = sim.simulate(prog)
    m = np.array([ln.layer == layer and ln.feature == "skirt" for ln in prog.lines]) & s.extruding
    return np.stack([s.x[m], s.y[m]], axis=1)


def test_convex_hull_and_outer():
    sq = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    hole = np.array([[3, 3], [7, 3], [7, 7], [3, 7]], float)
    assert len(geometry.outer_contours([sq, hole])) == 1
    h = geometry.convex_hull(np.concatenate([sq, hole]))
    assert abs(geometry.area(h) - 100) < 1e-6


def test_brim_hugs_part(libset, cube_stl):
    res = _slice(libset, cube_stl, type="brim", brim_width=4.0)
    pts = _skirt_xy(res.program)
    assert len(pts)
    # cube is 20 mm centred on 110,110 -> brim lies within 4 mm (+ half line) of the part
    ext = np.abs(pts - 110).max()
    assert 10 < ext <= 10 + 4.0 + 0.5


def test_skirt_distance_and_height(libset, cube_stl):
    res = _slice(libset, cube_stl, type="skirt", skirt_distance=5.0, skirt_height=3)
    pts = _skirt_xy(res.program)
    assert np.abs(pts - 110).max() == pytest.approx(10 + 5.0 + 0.225, abs=0.05)
    assert len(_skirt_xy(res.program, 2)) and not len(_skirt_xy(res.program, 3))


def test_none_adds_nothing(libset, cube_stl):
    res = _slice(libset, cube_stl, type="none")
    assert not any(ln.feature == "skirt" for ln in res.program.lines)


def test_old_pipeline_upgraded_with_disabled_stage():
    old = {"workflow": "fdm", "steps": [{"stage": s} for s in
                                        ("fdm_slice", "fdm_perimeters", "fdm_infill", "fdm_emit")]}
    p = SlicePipeline.from_dict(old).ensure_defaults()
    ids = [s.stage for s in p.steps]
    assert ids == ["fdm_slice", "fdm_skirt_brim", "fdm_support", "fdm_perimeters", "fdm_top_bottom",
                   "fdm_infill", "fdm_emit"]
    assert p.step("fdm_support").enabled          # always runs; Model > Support decides
    skirt = p.step("fdm_skirt_brim")                 # always on; added as type "none" (no new skirt)
    assert skirt.enabled and skirt.params["type"] == "none"
    assert p.step("fdm_slice").enabled


def test_process_import_export(tmp_path):
    pre = ProcessPreset("Mine", wf.FDM)
    pre.pipeline["steps"][0]["params"] = {"layer_height": 0.28}
    f = tmp_path / "mine.json"
    pre.export_file(str(f))
    back = ProcessPreset.import_file(str(f))
    assert back.name == "Mine" and back.slice_pipeline().step("fdm_slice").params["layer_height"] == 0.28
    # a bare pipeline file is accepted too
    g = tmp_path / "bare.json"
    g.write_text(json.dumps(SlicePipeline.default(wf.CAM).to_dict()))
    assert ProcessPreset.import_file(str(g)).workflow == wf.CAM


def test_disabled_skirt_stage_becomes_type_none():
    from gcodeproducer.stages.fdm.fdm_skirt_brim import FDMSkirtBrim
    assert not FDMSkirtBrim.optional                  # no 'Enabled' switch: Type = None turns it off
    old = {"workflow": "fdm", "steps": [{"stage": "fdm_skirt_brim", "enabled": False,
                                         "params": {"type": "brim", "brim_width": 7}}]}
    step = SlicePipeline.from_dict(old).step("fdm_skirt_brim")
    assert step.enabled and step.params["type"] == "none" and step.params["brim_width"] == 7
