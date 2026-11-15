import pytest

from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.session import build_job, load_mesh, slice_job
from gcodeproducer.stages.base import IncompatibleWorkflowError


def _fdm_job(libset, cube_stl):
    return build_job(wf.FDM, libset.machines.get("generic-220-fdm"),
                     material=libset["material"].get("pla"),
                     nozzle=libset["nozzle"].get("0-4-mm"),
                     mesh=load_mesh(cube_stl), model_path=cube_stl,
                     settings={"layer_height": 0.4})


def test_fdm_slice_produces_gcode(libset, cube_stl):
    res = slice_job(_fdm_job(libset, cube_stl))
    prog = res.program
    assert prog is not None
    assert prog.num_layers == 50
    text = prog.to_text()
    assert "M104" in text and "G1" in text and "E" in text
    # some extrusion happened
    assert any(ln.cmd == "G1" and "E" in ln.params for ln in prog.lines)


def test_fdm_simulates(libset, cube_stl):
    from gcodeproducer.core import sim
    prog = slice_job(_fdm_job(libset, cube_stl)).program
    s = sim.simulate(prog)
    assert int(s.extruding.sum()) > 100
    # highest extruding move is near the top of the 20 mm cube (end-gcode lift excluded)
    assert s.z[s.extruding].max() == pytest.approx(20.0, abs=0.5)


def test_cam_slice_produces_gcode(libset, cube_stl):
    job = build_job(wf.CAM, libset.machines.get("generic-300-router"),
                    tools=[libset["tool"].get("6-mm-flat-endmill")],
                    mesh=load_mesh(cube_stl), model_path=cube_stl)
    prog = slice_job(job).program
    assert prog is not None
    text = prog.to_text()
    assert "M3" in text and "M5" in text and "G0 Z" in text


def test_wrong_workflow_machine_rejected(libset, cube_stl):
    with pytest.raises(ValueError):
        build_job(wf.FDM, libset.machines.get("generic-300-router"), mesh=load_mesh(cube_stl))


def test_stage_workflow_isolation(libset, cube_stl):
    from gcodeproducer.stages.fdm_infill import FDMInfill
    from gcodeproducer.stages.base import StageContext
    job = build_job(wf.CAM, libset.machines.get("generic-300-router"),
                    tools=[libset["tool"].get("6-mm-flat-endmill")], mesh=load_mesh(cube_stl))
    with pytest.raises(IncompatibleWorkflowError):
        FDMInfill().execute(job, FDMInfill.resolve({}), StageContext())


def test_pipeline_roundtrip(tmp_path):
    p = SlicePipeline.default(wf.FDM)
    f = tmp_path / "pipe.json"
    p.save(str(f))
    q = SlicePipeline.load(str(f))
    assert [s.stage for s in q.steps] == [s.stage for s in p.steps]
