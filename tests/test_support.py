import numpy as np
import pytest

from conftest import write_boxes
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.placement import Placement
from gcodeproducer.core.session import build_job, load_mesh, slice_job

T_SHAPE = [(10, 10, 0, 20, 20, 15), (0, 0, 15, 30, 30, 18)]                       # plate on a pillar
SHELF = [(0, 0, 0, 30, 30, 4), (0, 0, 4, 10, 10, 20), (0, 0, 20, 30, 30, 22)]       # overhang above a base


def _support_lines(libset, path, enabled=True, placement="buildplate", pl=None):
    pipe = SlicePipeline.default(wf.FDM)
    st = pipe.step("fdm_support")
    st.enabled = enabled
    st.params["placement"] = placement
    job = build_job(wf.FDM, libset.machines.get("generic-220-fdm"), material=libset["material"].get("pla"),
                    nozzle=libset["nozzle"].get("0-4-mm"), mesh=load_mesh(path), placement=pl)
    res = slice_job(job, pipe)
    lines = [ln for ln in res.program.lines
             if ln.feature in ("support", "support_interface") and ln.cmd == "G1" and "E" in ln.params]
    return lines, res


def test_support_off_by_default():
    assert not SlicePipeline.default(wf.FDM).step("fdm_support").enabled


def test_t_shape_gets_support_from_bed(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    lines, res = _support_lines(libset, path)
    assert lines
    assert any(ln.feature == "support_interface" for ln in lines)
    top = max(ln.layer for ln in lines)
    z = res.program.layer_z
    assert z[top] < 15.0                                   # stays under the plate (z gap)
    assert min(ln.layer for ln in lines) == 0              # reaches the bed


def test_disabled_and_flipped_have_no_support(libset, tmp_path):
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    assert not _support_lines(libset, path, enabled=False)[0]
    assert not _support_lines(libset, path, pl=Placement(rx=180))[0]


def test_buildplate_vs_everywhere(libset, tmp_path):
    path = write_boxes(tmp_path / "shelf.stl", SHELF)
    lines, res = _support_lines(libset, path, placement="buildplate")
    assert not lines
    assert "build plate" in [s.summary for s in res.steps if s.stage == "fdm_support"][0]
    lines, res = _support_lines(libset, path, placement="everywhere")
    assert lines
    z = res.program.layer_z
    assert z[min(ln.layer for ln in lines)] > 4.0          # stands on the base, not on the bed


def test_support_keeps_clear_of_model(libset, tmp_path):
    from gcodeproducer.core import sim
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    lines, res = _support_lines(libset, path)
    s = sim.simulate(res.program)
    sup = np.array([ln.feature.startswith("support") for ln in res.program.lines]) & s.extruding
    xy = np.concatenate([np.stack([s.x[sup], s.y[sup]], axis=1), np.stack([s.px[sup], s.py[sup]], axis=1)])
    # pillar is 10x10 centred on the bed (105..115): support stays >= xy_distance away
    inside = (np.abs(xy[:, 0] - 110) < 5 + 0.5) & (np.abs(xy[:, 1] - 110) < 5 + 0.5)
    assert not inside.any()


def test_cli_stage_param_enables_support(tmp_path, monkeypatch, capsys):
    from gcodeproducer.cli import main
    monkeypatch.setenv("GCODEPRODUCER_LIBRARY", str(tmp_path / "lib"))
    path = write_boxes(tmp_path / "t.stl", T_SHAPE)
    out = tmp_path / "t.gcode"
    assert main(["slice", path, "-o", str(out), "-q", "-m", "fdm_support:placement=buildplate"]) == 0
    assert ";TYPE:support" in out.read_text()
    assert main(["slice", path, "-o", str(out), "-q", "-m", "fdm_support:typo=1"]) == 2   # typo reported
