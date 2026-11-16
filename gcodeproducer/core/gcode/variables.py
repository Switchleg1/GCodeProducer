"""The variables available in G-code templates (start / end G-code, and future boxes).

:data:`VARIABLES` is the single registry: name, category, description, an example
value and the workflow(s) it applies to.  The GUI builds its *Insert variable*
menu and its live check from it, and :func:`job_variables` fills the values for
a job.  To add a variable: add it to :data:`VARIABLES` and set it in
:func:`job_variables` (a test checks that every registered variable is set).

Event-specific values (e.g. the layer being started, for a future 'layer
change' box) are passed as ``extra`` and override / add to the job values.
"""
from __future__ import annotations

from gcodeproducer.core.gcode.template_variable import Var
from gcodeproducer.core.gcode.gcode_constants import VARIABLES, _BY_NAME, DEFAULT_START, DEFAULT_END
import datetime, math, gcodeproducer.core.workflows.validation as wf
from .gcode_constants import TEMPLATE_FDM as FDM, TEMPLATE_CAM as CAM, TEMPLATE_BOTH as BOTH


def variables_for(workflow: str) -> list:
    w = wf.normalize(workflow)
    return [v for v in VARIABLES if w in v.workflows]


def names_for(workflow: str) -> list:
    return [v.name for v in variables_for(workflow)]


def example_values(workflow: str) -> dict:
    return {v.name: v.example for v in variables_for(workflow)}


def _num(v, default=0.0):
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def job_variables(job, temps: dict | None = None, extra: dict | None = None) -> dict:
    """Values of every template variable for ``job``.

    ``temps`` are the (capped) temperatures the emitter uses; ``extra`` adds or
    overrides values for a specific event (e.g. the layer being started)."""
    from gcodeproducer import __version__
    m = job.machine
    now = datetime.datetime.now()
    v: dict = {
        "machine": m.name, "model": _file_name(job.model_path), "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"), "version": __version__,
    }
    lo = hi = None
    if job.mesh is not None and len(job.mesh.vertices):
        lo, hi = job.mesh.bounds
    for i, axis in enumerate("xyz"):
        v[f"print_min_{axis}"] = float(lo[i]) if lo is not None else 0.0
        v[f"print_max_{axis}"] = float(hi[i]) if hi is not None else 0.0
    layers = job.layers or []
    v["layer_count"] = len(layers)
    v["layer"] = 1
    v["layer_z"] = float(layers[0].z) if layers else 0.0

    if job.workflow == wf.FDM:
        bx, by = _num(m.get("bed_x", 220)), _num(m.get("bed_y", 220))
        center = bool(m.get("origin_center", False))
        v.update(bed_x=bx, bed_y=by, max_height=_num(m.get("height", 250)),
                 bed_center_x=0.0 if center else bx / 2, bed_center_y=0.0 if center else by / 2,
                 relative_e=bool(m.get("relative_e", True)),
                 heated_chamber=bool(m.get("heated_chamber", False)),
                 wait_for_chamber=bool(m.get("wait_for_chamber", False)),
                 max_nozzle_temp=_num(m.get("max_nozzle_temp", 0)), max_bed_temp=_num(m.get("max_bed_temp", 0)),
                 max_chamber_temp=_num(m.get("max_chamber_temp", 0)))
        t = temps or {}
        tn = _num(job.mat("temp_nozzle", 0))
        tb = _num(job.mat("temp_bed", 0))
        v.update(nozzle_temp=t.get("nozzle", tn),
                 nozzle_temp_first=t.get("nozzle_first", _num(job.mat("temp_nozzle_first", tn)) or tn),
                 bed_temp=t.get("bed", tb),
                 bed_temp_first=t.get("bed_first", _num(job.mat("temp_bed_first", tb)) or tb),
                 chamber_temp=t.get("chamber", 0.0))
        lh = _num(job.settings.get("layer_height", job.layer_height), 0.2)
        flh = _num(job.settings.get("first_layer_height", lh), lh)
        fan = _num(job.mat("fan_speed", 100.0))
        v.update(tool=0, nozzle=job.nozzle.name if job.nozzle else "",
                 nozzle_diameter=_num(job.noz("diameter", 0.4), 0.4), line_width=_num(job.line_width, 0.45),
                 material=job.material.name if job.material else "",
                 material_type=job.mat("type", "") or "",
                 filament_diameter=_num(job.mat("filament_diameter", 1.75), 1.75),
                 flow=_num(job.mat("flow", 100.0), 100.0), fan_speed=fan,
                 fan_speed_pwm=int(round(255 * fan / 100.0)),
                 retract_length=_num(job.mat("retract_length", 0.0)),
                 retract_speed=_num(job.mat("retract_speed", 35.0)),
                 layer_height=lh, first_layer_height=flh, current_layer_height=flh)
    else:
        wx, wy = _num(m.get("work_x", 300)), _num(m.get("work_y", 300))
        center = m.get("origin") == "center"
        tool = job.tools[0] if job.tools else None
        from gcodeproducer.core.cam.stock import Stock
        stock = getattr(job.cam_setup, "stock", None) or Stock(category=job.settings.get("machining_material","soft_wood"))
        v.update(machining_material=stock.category,
                 sfm=_num(tool.get(f"{stock.category}_sfm",0)) if tool else 0.,
                 chip_load=_num(tool.get(f"{stock.category}_chip_load",0)) if tool else 0.,
                 axial_depth=_num(tool.get("max_doc",0)) if tool else 0.)
        v.update(stock_material=stock.material, stock_density=stock.density,
                 stock_width=stock.width, stock_depth=stock.depth, stock_height=stock.height,
                 stock_top=stock.top, stock_bottom=stock.top - stock.height)
        v.update(bed_x=wx, bed_y=wy, max_height=_num(m.get("work_z", 100)),
                 bed_center_x=0.0 if center else wx / 2, bed_center_y=0.0 if center else wy / 2,
                 safe_z=_num(m.get("safe_z", 15.0)),
                 tool=int(tool.get("tool_number", 1)) if tool else 0,
                 tool_name=tool.name if tool else "",
                 tool_diameter=_num(tool.get("diameter", 0)) if tool else 0.0,
                 spindle_rpm=_num(tool.get("spindle_rpm", 0)) if tool else _num(m.get("spindle_max", 0)),
                 feed=_num(tool.get("feed", 0)) if tool else _num(m.get("max_feed", 0)),
                 plunge_feed=_num(tool.get("plunge_feed", 0)) if tool else 0.0)
    if extra:
        v.update(extra)
    return v


def _file_name(path) -> str:
    if not path:
        return ""
    import os
    return os.path.basename(str(path))


def render_box(job, key: str, temps: dict | None = None, extra: dict | None = None, log=None) -> str:
    """Render the machine's G-code box ``key`` ('start_gcode' / 'end_gcode'); empty = the default."""
    from gcodeproducer.core.gcode.templates import render
    text = job.m(key) or ""
    if not text.strip():
        text = (DEFAULT_START if key == "start_gcode" else DEFAULT_END)[job.workflow]
    out, problems = render(text, job_variables(job, temps, extra))
    for p in problems:
        if log:
            log(f"  {key.replace('_', ' ')}: {p}")
    return out
