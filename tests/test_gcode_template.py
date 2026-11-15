"""G-code templates (start / end G-code boxes) and their variable dictionary."""
import os

import pytest

from gcodeproducer.core import gcode_vars as gv
from gcodeproducer.core import workflow as wf
from gcodeproducer.core.gcode_template import check, evaluate, render, TemplateError
from gcodeproducer.core.pipeline import SlicePipeline
from gcodeproducer.core.profiles import Profile
from gcodeproducer.core.session import build_job, load_mesh, slice_job


# ------------------------------------------------------------------ engine
def test_substitution_and_formats():
    out, p = render("M104 S{t} ; {name} {t:.1f} {z} {flag} {t + 5} {round(z * 10, 1)}",
                    {"t": 205.0, "name": "PLA", "z": 0.2, "flag": True})
    assert p == [] and out == "M104 S205 ; PLA 205.0 0.2 1 210 2"     # whole numbers print without .0


def test_conditionals_nested_and_multiline():
    t = "A\n{if x > 1}X\n{if y}Y\n{else}noY\n{endif}{elif x == 1}one\n{else}none\n{endif}B"
    assert render(t, {"x": 2, "y": 1})[0] == "A\nX\nY\nB"
    assert render(t, {"x": 2, "y": 0})[0] == "A\nX\nnoY\nB"
    assert render(t, {"x": 1, "y": 1})[0] == "A\none\nB"
    assert render(t, {"x": 0, "y": 1})[0] == "A\nnone\nB"


def test_literal_braces_and_comments():
    assert render("{{x}} ; {a}", {"a": 1})[0] == "{x} ; 1"


def test_problems_are_reported_not_raised():
    out, p = render("M104 S{tempp}\n{if a}\nX", {"a": 1})
    assert "{tempp}" in out
    assert any("unknown variable 'tempp'" in m for m in p) and any("without '{endif}'" in m for m in p)
    assert render("{endif}", {})[1] == ["line 1: '{endif}' without '{if}'"]


def test_expressions_are_safe():
    for bad in ("__import__('os').system('x')", "open('f')", "(1).__class__", "[x for x in y]"):
        with pytest.raises(TemplateError):
            evaluate(bad, {"x": 1, "y": [1]})


def test_check_covers_untaken_branches():
    assert check("{if 0}{nope}{endif}", ["a"]) == ["line 1: unknown variable 'nope'"]
    assert check(gv.DEFAULT_START[wf.FDM], gv.names_for(wf.FDM)) == []
    assert check(gv.DEFAULT_END[wf.CAM], gv.names_for(wf.CAM)) == []


# ------------------------------------------------------------------ variables
def _fdm_job(libset, cube_stl, machine=None, material=None):
    return build_job(wf.FDM, machine or libset.machines.get("generic-220-fdm"),
                     material=material or libset["material"].get("pla"), nozzle=libset["nozzle"].get("0-4-mm"),
                     mesh=load_mesh(cube_stl), model_path=cube_stl)


@pytest.mark.parametrize("workflow", [wf.FDM, wf.CAM])
def test_every_registered_variable_has_a_value(libset, cube_stl, workflow):
    if workflow == wf.FDM:
        job = _fdm_job(libset, cube_stl)
    else:
        job = build_job(wf.CAM, libset.machines.get("generic-300-router"), mesh=load_mesh(cube_stl),
                        tools=[libset["tool"].get("6-mm-flat-endmill")])
    values = gv.job_variables(job)
    missing = [n for n in gv.names_for(workflow) if n not in values]
    assert missing == []
    assert render(gv.DEFAULT_START[workflow], values)[1] == []
    assert render(gv.DEFAULT_END[workflow], values)[1] == []


def test_variable_values(libset, cube_stl):
    job = _fdm_job(libset, cube_stl)
    job.settings.update(layer_height=0.28, first_layer_height=0.3)
    v = gv.job_variables(job, temps={"nozzle": 205, "nozzle_first": 210, "bed": 60, "bed_first": 65,
                                     "chamber": 0})
    assert (v["nozzle_temp"], v["nozzle_temp_first"], v["bed_temp"], v["bed_temp_first"]) == (205, 210, 60, 65)
    assert (v["layer_height"], v["first_layer_height"], v["current_layer_height"]) == (0.28, 0.3, 0.3)
    assert v["tool"] == 0 and v["material"] == "PLA" and v["model"] == os.path.basename(cube_stl)
    assert v["fan_speed_pwm"] == 255 and v["nozzle_diameter"] == 0.4


# ------------------------------------------------------------------ emitters
def _slice(job):
    logs = []
    prog = slice_job(job, SlicePipeline.default(job.workflow), log=logs.append).program
    return prog.to_text(), "\n".join(logs)


def test_default_start_end_used_when_empty(libset, cube_stl):
    text, log = _slice(_fdm_job(libset, cube_stl))
    assert "M190 S60 ; wait for bed" in text and "M109 S210 T0 ; wait for nozzle" in text
    assert "M84 ; motors off" in text and "M141" not in text and "start gcode" not in log


def test_custom_template_with_variables(libset, cube_stl):
    m = Profile("machine", "custom", workflow="fdm", values={
        "start_gcode": "; {material} {layer_height} mm\nM190 S{bed_temp_first}\n"
                       "M109 S{nozzle_temp_first + 0}\n{if heated_chamber}M141 S{chamber_temp}\n{endif}G28 W",
        "end_gcode": "; done {layer_count} layers, last Z{layer_z}\nM84 X Y",
        "max_nozzle_temp": 200})
    text, log = _slice(_fdm_job(libset, cube_stl, machine=m))
    assert "; PLA 0.2 mm\nM190 S60\nM109 S200\nG28 W" in text            # capped nozzle temp in the variable
    assert "; done 100 layers, last Z20\nM84 X Y" in text
    assert "M141" not in text and "M190 S60 ; wait" not in text           # the default is not used


def test_unknown_variable_logged(libset, cube_stl):
    m = Profile("machine", "typo", workflow="fdm", values={"start_gcode": "M109 S{nozle_temp}"})
    text, log = _slice(_fdm_job(libset, cube_stl, machine=m))
    assert "M109 S{nozle_temp}" in text and "unknown variable 'nozle_temp'" in log


def test_chamber_via_default_template(libset, cube_stl):
    m = Profile("machine", "ch", workflow="fdm", values={"heated_chamber": True, "wait_for_chamber": True})
    text, _ = _slice(_fdm_job(libset, cube_stl, machine=m, material=libset["material"].get("abs")))
    assert "M141 S45 ; set chamber" in text and "M191 S45 ; wait for chamber" in text
    assert "M141 S0 ; chamber off" in text


def test_cam_templates(libset, cube_stl):
    job = build_job(wf.CAM, libset.machines.get("generic-300-router"), mesh=load_mesh(cube_stl),
                    tools=[libset["tool"].get("3-mm-flat-endmill")])
    text, _ = _slice(job)
    assert "T2 M6 ; tool change" in text and "M3 S20000 ; spindle on" in text and "M30 ; end of program" in text
