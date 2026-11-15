"""Process speeds capped by machine limits; temperatures capped; chamber control."""
import math

import pytest

from gcodeproducer.core import workflow as wf
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.session import build_job, load_mesh, slice_job


def _run(libset, cube_stl, machine=None, material=None, nozzle=None, **speeds):
    machine = machine or libset.machines.get("generic-220-fdm")
    pipe = SlicePipeline.default(wf.FDM)
    pipe.step("fdm_emit").params.update(speeds)
    job = build_job(wf.FDM, machine, material=material or libset["material"].get("pla"),
                    nozzle=nozzle or libset["nozzle"].get("0-4-mm"), mesh=load_mesh(cube_stl))
    logs = []
    res = slice_job(job, pipe, log=logs.append)
    return res.program, "\n".join(logs)


def _feeds(prog, feature, layer_min=1):
    return {ln.params["F"] for ln in prog.lines
            if ln.feature == feature and ln.layer >= layer_min and ln.cmd == "G1" and "F" in ln.params
            and ("X" in ln.params or "Y" in ln.params)}


def _machine(**values):
    base = {"bed_x": 220, "bed_y": 220, "height": 250}
    return Profile("machine", "test", workflow="fdm", values={**base, **values})


def test_process_speeds_are_used(libset, cube_stl):
    prog, _ = _run(libset, cube_stl, outer_wall_speed=25, inner_wall_speed=40, infill_speed=70,
                   travel_speed=120, first_layer_speed=15)
    assert _feeds(prog, "outer_perimeter") == {25 * 60}
    assert _feeds(prog, "inner_perimeter") == {40 * 60}
    assert _feeds(prog, "infill") == {70 * 60}
    assert {ln.params["F"] for ln in prog.lines if ln.cmd == "G0" and "F" in ln.params} == {120 * 60}
    first = {ln.params["F"] for ln in prog.lines if ln.layer == 0 and ln.cmd == "G1" and "F" in ln.params
             and "X" in ln.params and ln.feature != "skirt"}
    assert first == {15 * 60}


def test_machine_max_speed_caps(libset, cube_stl):
    prog, log = _run(libset, cube_stl, machine=_machine(max_print_speed=50, max_travel_speed=100),
                     infill_speed=120, outer_wall_speed=30, travel_speed=250)
    assert _feeds(prog, "infill") == {50 * 60}               # capped
    assert _feeds(prog, "outer_perimeter") == {30 * 60}      # under the limit: unchanged
    assert {ln.params["F"] for ln in prog.lines if ln.cmd == "G0" and "F" in ln.params} == {100 * 60}
    assert "infill 120 \u2192 50 mm/s (machine max print speed)" in log
    assert "travel 250 \u2192 100 mm/s" in log


def test_volumetric_flow_caps(libset, cube_stl):
    nozzle = Profile("nozzle", "slow", values={"diameter": 0.4, "line_width": 0.45, "max_flow": 5.0})
    prog, log = _run(libset, cube_stl, nozzle=nozzle, infill_speed=100, outer_wall_speed=20)
    (f,) = _feeds(prog, "infill")
    # 0.45 x 0.2 bead (rounded sides) ~ 0.0814 mm2 -> 5 mm3/s / 0.0814 ~ 61 mm/s
    bead = (0.45 - 0.2) * 0.2 + math.pi * 0.1 ** 2
    assert f / 60 == pytest.approx(5.0 / bead, rel=0.02)
    assert _feeds(prog, "outer_perimeter") == {20 * 60}
    assert "max flow 5 mm\u00b3/s" in log
    # a machine flow limit lower than the nozzle's wins
    prog, _ = _run(libset, cube_stl, machine=_machine(max_flow=3.0), nozzle=nozzle, infill_speed=100)
    (f,) = _feeds(prog, "infill")
    assert f / 60 == pytest.approx(3.0 / bead, rel=0.02)


def test_acceleration_capped(libset, cube_stl):
    prog, _ = _run(libset, cube_stl, machine=_machine(max_acceleration=2000), acceleration=8000)
    assert "M204 S2000" in prog.to_text()
    prog, _ = _run(libset, cube_stl, acceleration=0)
    assert "M204" not in prog.to_text()


def test_temperatures_capped_and_layer_switch(libset, cube_stl):
    hot = Profile("material", "hot", values={"temp_nozzle": 300, "temp_nozzle_first": 310,
                                             "temp_bed": 120, "temp_bed_first": 125})
    prog, log = _run(libset, cube_stl, machine=_machine(max_nozzle_temp=280, max_bed_temp=100), material=hot)
    text = prog.to_text()
    assert "M104 S280" in text and "M109 S280" in text and "M190 S100" in text
    assert "S310" not in text and "S300" not in text and "S125" not in text
    assert "temperature capped: nozzle 300 \u2192 280" in log
    # after layer 1 the normal temperatures are set (here: first-layer temps differ)
    pla = libset["material"].get("pla")                       # 210 first layer -> 205
    prog, _ = _run(libset, cube_stl, material=pla)
    layer1 = [ln.text for ln in prog.lines if ln.layer == 1 and ln.cmd == "M104"]
    assert layer1 and "S205" in layer1[0]


def test_chamber(libset, cube_stl):
    abs_ = libset["material"].get("abs")
    assert abs_.get("temp_chamber") == 45
    # no heated chamber: ignored with a note
    prog, log = _run(libset, cube_stl, material=abs_)
    assert "M141" not in prog.to_text() and "no heated chamber" in log
    # heated chamber: set at the start (capped), off at the end; wait only if asked
    m = _machine(heated_chamber=True, max_chamber_temp=40)
    prog, log = _run(libset, cube_stl, machine=m, material=abs_)
    text = prog.to_text()
    assert text.index("M141 S40") < text.index("M190")       # chamber first
    end = text[text.rindex(";LAYER:"):]
    assert "M191" not in text and "M141 S0" in end                # chamber off in the end G-code
    m = _machine(heated_chamber=True, max_chamber_temp=60, wait_for_chamber=True)
    prog, _ = _run(libset, cube_stl, machine=m, material=abs_)
    assert "M141 S45" in prog.to_text() and "M191 S45" in prog.to_text()


def test_old_machine_profile_with_speeds_still_loads(tmp_path):
    from gcodeproducer.core.profiles import LibrarySet
    import json
    d = tmp_path / "machines"
    d.mkdir()
    (d / "old.json").write_text(json.dumps({"kind": "machine", "id": "old", "name": "Old", "workflow": "fdm",
                                            "values": {"bed_x": 200, "print_speed": 60, "travel_speed": 150,
                                                       "acceleration": 2000, "z_speed": 10}}))
    ls = LibrarySet(tmp_path).load()
    m = ls.machines.get("old")
    r = m.resolved()
    assert r["bed_x"] == 200 and r["max_print_speed"] == 200 and "print_speed" not in r
