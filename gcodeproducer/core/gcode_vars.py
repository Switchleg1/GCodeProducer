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

import datetime
import math
from dataclasses import dataclass

from . import workflow as wf

FDM, CAM, BOTH = (wf.FDM,), (wf.CAM,), (wf.FDM, wf.CAM)


@dataclass(frozen=True)
class Var:
    name: str
    category: str
    description: str
    example: object
    workflows: tuple = BOTH


VARIABLES = [
    # ---- general
    Var("machine", "General", "Machine profile name", "Generic 220 FDM"),
    Var("model", "General", "Model file name", "bracket.stl"),
    Var("date", "General", "Date the G-code was produced (YYYY-MM-DD)", "2025-01-31"),
    Var("time", "General", "Time the G-code was produced (HH:MM)", "14:05"),
    Var("version", "General", "GCodeProducer version", "0.1.0"),
    # ---- machine
    Var("bed_x", "Machine", "Bed / work area size X (mm)", 220.0),
    Var("bed_y", "Machine", "Bed / work area size Y (mm)", 220.0),
    Var("max_height", "Machine", "Build / work height (mm)", 250.0),
    Var("bed_center_x", "Machine", "X of the bed centre (mm)", 110.0),
    Var("bed_center_y", "Machine", "Y of the bed centre (mm)", 110.0),
    Var("relative_e", "Machine", "1 if extrusion is relative (M83), else 0", True, FDM),
    Var("heated_chamber", "Machine", "1 if the machine has a heated chamber", False, FDM),
    Var("wait_for_chamber", "Machine", "1 if the start should wait for the chamber (M191)", False, FDM),
    Var("max_nozzle_temp", "Machine", "Machine maximum nozzle temperature (\u00b0C)", 280.0, FDM),
    Var("max_bed_temp", "Machine", "Machine maximum bed temperature (\u00b0C)", 110.0, FDM),
    Var("max_chamber_temp", "Machine", "Machine maximum chamber temperature (\u00b0C)", 60.0, FDM),
    Var("safe_z", "Machine", "Safe Z for rapids (mm)", 15.0, CAM),
    # ---- temperatures (material values, already capped at the machine limits)
    Var("nozzle_temp", "Temperatures", "Nozzle temperature (\u00b0C)", 205.0, FDM),
    Var("nozzle_temp_first", "Temperatures", "First-layer nozzle temperature (\u00b0C)", 210.0, FDM),
    Var("bed_temp", "Temperatures", "Bed temperature (\u00b0C)", 60.0, FDM),
    Var("bed_temp_first", "Temperatures", "First-layer bed temperature (\u00b0C)", 60.0, FDM),
    Var("chamber_temp", "Temperatures", "Chamber temperature (\u00b0C); 0 = none / no heated chamber", 0.0, FDM),
    # ---- tool / nozzle / material
    Var("tool", "Tool", "Tool / extruder number (T)", 0),
    Var("nozzle", "Tool", "Nozzle profile name", "0.4 mm", FDM),
    Var("nozzle_diameter", "Tool", "Nozzle diameter (mm)", 0.4, FDM),
    Var("line_width", "Tool", "Default line width (mm)", 0.45, FDM),
    Var("material", "Material", "Material profile name", "PLA", FDM),
    Var("material_type", "Material", "Material type (PLA, PETG, ABS ...)", "PLA", FDM),
    Var("filament_diameter", "Material", "Filament diameter (mm)", 1.75, FDM),
    Var("flow", "Material", "Flow multiplier (%)", 100.0, FDM),
    Var("fan_speed", "Material", "Part fan speed (%)", 100.0, FDM),
    Var("fan_speed_pwm", "Material", "Part fan speed as 0-255 (for M106 S)", 255, FDM),
    Var("retract_length", "Material", "Retraction length (mm)", 1.0, FDM),
    Var("retract_speed", "Material", "Retraction speed (mm/s)", 35.0, FDM),
    Var("tool_name", "Tool", "Cutter profile name", "6 mm flat endmill", CAM),
    Var("tool_diameter", "Tool", "Cutter diameter (mm)", 6.0, CAM),
    Var("spindle_rpm", "Tool", "Spindle speed (rpm)", 18000.0, CAM),
    Var("feed", "Tool", "Cutting feed (mm/min)", 1000.0, CAM),
    Var("plunge_feed", "Tool", "Plunge feed (mm/min)", 300.0, CAM),
    # ---- CAM blank
    Var("stock_material", "Stock", "Stock material name", "Aluminium", CAM),
    Var("stock_density", "Stock", "Stock density (g/cm³)", 2.7, CAM),
    Var("stock_width", "Stock", "Stock size X (mm)", 24.0, CAM),
    Var("stock_depth", "Stock", "Stock size Y (mm)", 24.0, CAM),
    Var("stock_height", "Stock", "Stock thickness Z (mm)", 22.0, CAM),
    Var("stock_top", "Stock", "Stock surface Z (mm)", 0.0, CAM),
    Var("stock_bottom", "Stock", "Stock bottom Z (mm)", -22.0, CAM),
    # ---- layers
    Var("layer_height", "Layers", "Layer height (mm)", 0.2, FDM),
    Var("first_layer_height", "Layers", "First layer height (mm)", 0.2, FDM),
    Var("current_layer_height", "Layers", "Height of the current layer (mm); the first layer at the start",
        0.2, FDM),
    Var("layer", "Layers", "Current layer number (1-based); 1 at the start, last layer at the end", 1),
    Var("layer_z", "Layers", "Z of the current layer (mm)", 0.2),
    Var("layer_count", "Layers", "Number of layers / depth passes", 100),
    # ---- part
    Var("print_min_x", "Part", "Smallest X of the placed model (mm)", 100.0),
    Var("print_min_y", "Part", "Smallest Y of the placed model (mm)", 100.0),
    Var("print_min_z", "Part", "Smallest Z of the placed model (mm)", 0.0),
    Var("print_max_x", "Part", "Largest X of the placed model (mm)", 120.0),
    Var("print_max_y", "Part", "Largest Y of the placed model (mm)", 120.0),
    Var("print_max_z", "Part", "Largest Z of the placed model (mm)", 20.0),
]

_BY_NAME = {v.name: v for v in VARIABLES}


def variables_for(workflow: str) -> list:
    w = wf.normalize(workflow)
    return [v for v in VARIABLES if w in v.workflows]


def names_for(workflow: str) -> list:
    return [v.name for v in variables_for(workflow)]


def example_values(workflow: str) -> dict:
    return {v.name: v.example for v in variables_for(workflow)}


# --------------------------------------------------------------------------
DEFAULT_START = {
    wf.FDM: """\
; {machine} - {material} ({material_type}), {nozzle} nozzle, {layer_height} mm layers
G21 ; millimetres
G90 ; absolute positioning
{if chamber_temp > 0}M141 S{chamber_temp} ; set chamber
{endif}M140 S{bed_temp_first} ; set bed
M104 S{nozzle_temp_first} T{tool} ; set nozzle
M190 S{bed_temp_first} ; wait for bed
{if chamber_temp > 0 and wait_for_chamber}M191 S{chamber_temp} ; wait for chamber
{endif}M109 S{nozzle_temp_first} T{tool} ; wait for nozzle
G28 ; home all axes
""",
    wf.CAM: """\
; {machine} - {tool_name} (T{tool}, {tool_diameter} mm)
G21 ; millimetres
G90 ; absolute positioning
G0 Z{safe_z} ; safe height
T{tool} M6 ; tool change
M3 S{spindle_rpm} ; spindle on
""",
}

DEFAULT_END = {
    wf.FDM: """\
M104 S0 T{tool} ; nozzle off
M140 S0 ; bed off
{if chamber_temp > 0}M141 S0 ; chamber off
{endif}M107 ; fan off
G91 ; relative
G1 Z10 F600 ; lift
G90 ; absolute
M84 ; motors off
""",
    wf.CAM: """\
G0 Z{safe_z} ; safe height
M5 ; spindle off
G0 X0 Y0 ; park
M30 ; end of program
""",
}


# --------------------------------------------------------------------------
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
    from .. import __version__
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
        from .stock import Stock
        stock = getattr(job.cam_setup, "stock", None) or Stock()
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
    from .gcode_template import render
    text = job.m(key) or ""
    if not text.strip():
        text = (DEFAULT_START if key == "start_gcode" else DEFAULT_END)[job.workflow]
    out, problems = render(text, job_variables(job, temps, extra))
    for p in problems:
        if log:
            log(f"  {key.replace('_', ' ')}: {p}")
    return out
