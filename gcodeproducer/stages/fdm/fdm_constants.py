"""Shared fdm constants and declarative tables."""
from __future__ import annotations

_FEATURE_SPEED = {
    "outer_perimeter": "outer_wall_speed",
    "middle_perimeter": "inner_wall_speed",
    "inner_perimeter": "inner_wall_speed",
    "infill": "infill_speed",
    "solid_infill": "solid_infill_speed",
    "top_infill": "top_infill_speed",
    "support": "support_speed",
    "support_interface": "support_interface_speed",
    "skirt": "skirt_speed",
}

from gcodeproducer.stages.base.api import Param, AUTO
import gcodeproducer.core.geometry.infill as infill_gen, gcodeproducer.core.fdm.support as support

def _speed(name, default, label, help=""):
    return Param(name, "float", default, label=label, unit="mm/s", min=1, max=2000, decimals=1,
                 group="Speeds", help=help)

FDMEMIT_PARAMS = [
        _speed("outer_wall_speed", 30.0, "Outer wall"),
        _speed("inner_wall_speed", 45.0, "Inner walls"),
        _speed("infill_speed", 60.0, "Infill"),
        _speed("solid_infill_speed", 40.0, "Solid infill", "Bottom / internal solid layers."),
        _speed("top_infill_speed", 30.0, "Top solid infill"),
        _speed("support_speed", 50.0, "Support"),
        _speed("support_interface_speed", 35.0, "Support interface"),
        _speed("skirt_speed", 30.0, "Skirt / brim"),
        _speed("print_speed", 50.0, "Other features", "Anything not listed above."),
        _speed("first_layer_speed", 20.0, "First layer", "Every printing move on the first layer."),
        _speed("travel_speed", 150.0, "Travel"),
        Param("acceleration", "float", 0.0, unit="mm/s\u00b2", min=0, max=100000, decimals=0, group="Speeds",
              help="Print acceleration (M204); 0 = leave the firmware setting. Capped at the machine's maximum."),
        Param("retract", "bool", True, label="Retract on travel", group="Travel",
              help="Retract on travels between features (length / speed from the material)."),
        Param("min_travel_retract", "float", 1.5, label="Min travel to retract", unit="mm",
              min=0, decimals=2, group="Travel", help="Shorter travels do not retract."),
        Param("avoid_open_spaces", "bool", False, label="Avoid crossing open spaces", group="Travel",
              help="Prefer a route within the same layer island, around holes or gaps, when within the detour budget."),
        Param("travel_detour_time", "float", 0.1, label="Max extra time per travel", unit="s",
              min=0, decimals=3, group="Travel",
              help="Extra XY distance divided by travel speed (ignores acceleration); 0 = no detours."),
        Param("seam", "choice", "nearest", label="Perimeter start / stop", group="Seam",
              choices=[("nearest", "Fastest (nearest start)"), ("xy", "Toward XY point"),
                       ("origin", "Fixed (loop start)")],
              help="Choose where each perimeter starts and ends. Fastest minimizes the local approach distance."),
        Param("seam_x", "float", 0., label="Target X", unit="mm", decimals=2, group="Seam",
              help="Bed-coordinate target for Toward XY point. May be outside the part."),
        Param("seam_y", "float", 0., label="Target Y", unit="mm", decimals=2, group="Seam",
              help="Bed-coordinate target for Toward XY point. May be outside the part."),
    ]

FDMINFILL_PARAMS = [
        Param("optimize_mixed_infill", "bool", True, label="Print nearby infill together", group="Lines",
              help="Interleave sparse, top and bottom solid fill on the same layer to reduce travel."),
        Param("density", "float", 20.0, unit="%", min=0, max=100, decimals=1, group="Pattern",
              help="0 = hollow (walls and shells only)."),
        Param("pattern", "choice", "grid", choices=list(infill_gen.PATTERNS), group="Pattern"),
        Param("angle", "float", 45.0, unit="\u00b0", min=-180, max=180, decimals=1, group="Pattern"),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Lines", help="auto = wall line width."),
        Param("overlap", "float", 15.0, unit="%", min=-100, max=100, decimals=1, group="Lines",
              help="Overlap with the innermost wall (% of infill width)."),
        Param("min_length", "float", 0.5, unit="mm", min=0, decimals=2, group="Lines"),
        Param("connect", "bool", True, label="Shortest travel order", group="Lines",
              help="Order lines nearest-first to shorten travels."),
    ]

FDMPERIMETERS_PARAMS = [
        Param("perimeters", "int", 2, label="Wall loops", min=1, max=20, group="Walls",
              help="Number of perimeter loops."),
        Param("line_width", "float", AUTO, label="Wall line width", unit="mm", min=0.05, max=3,
              allow_auto=True, hint=0.45, group="Walls", help="auto = nozzle line width."),
    ]

FDMSKIRTBRIM_PARAMS = [
        Param("type", "choice", "skirt", group="Adhesion",
              choices=[("none", "None"), ("skirt", "Skirt"), ("brim", "Brim"), ("both", "Skirt + brim")]),
        Param("skirt_loops", "int", 1, min=1, max=20, group="Skirt"),
        Param("skirt_distance", "float", 3.0, unit="mm", min=0, decimals=2, group="Skirt",
              help="Gap between the part (or brim) and the skirt."),
        Param("skirt_height", "int", 1, label="Skirt layers", min=1, max=1000, group="Skirt",
              help="Number of layers the skirt is printed on (tall skirt = draft shield)."),
        Param("brim_width", "float", 5.0, unit="mm", min=0, decimals=2, group="Brim"),
        Param("brim_gap", "float", 0.0, unit="mm", min=0, decimals=2, group="Brim",
              help="Gap between the part and the brim (makes it easier to remove)."),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Lines", help="auto = nozzle line width."),
    ]

FDMSLICE_PARAMS = [
        Param("layer_height", "float", 0.2, unit="mm", min=0.01, max=2.0, step=0.02,
              group="Layer height", help="Height of every layer after the first."),
        Param("first_layer_height", "float", AUTO, unit="mm", min=0.01, max=2.0, step=0.02,
              allow_auto=True, hint=0.25, group="Layer height",
              help="auto = same as the layer height."),
    ]

FDMSUPPORT_PARAMS = [
        Param("density", "float", 15.0, unit="%", min=1, max=100, decimals=1, group="Pattern"),
        Param("pattern", "choice", "lines", group="Pattern",
              choices=[("lines", "Lines"), ("grid", "Grid")]),
        Param("xy_distance", "float", 0.8, unit="mm", min=0, decimals=2, group="Distances",
              help="Horizontal gap between support and the model."),
        Param("z_gap_layers", "int", 1, label="Top Z gap (layers)", min=0, max=10, group="Distances",
              help="Empty layers between the top of the support and the overhang."),
        Param("bottom_z_gap_layers", "int", 1, label="Bottom Z gap (layers)", min=0, max=10, group="Distances",
              help="Empty layers between the model and support standing on it (Everywhere / manual "
                   "blocks). Support on the bed starts on the first layer."),
        Param("interface_layers", "int", 2, label="Top interface layers", min=0, max=20, group="Interface",
              help="Dense layers at the top of the support, under the overhang (0 = off)."),
        Param("bottom_interface_layers", "int", 2, label="Bottom interface layers", min=0, max=20,
              group="Interface",
              help="Dense layers at the bottom of the support, where it stands on the model or on the bed "
                   "(0 = off)."),
        Param("interface_density", "float", 70.0, unit="%", min=5, max=100, decimals=1, group="Interface"),
        Param("min_area", "float", 1.0, unit="mm\u00b2", min=0, decimals=2, group="Distances",
              help="Ignore overhang specks smaller than this."),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Pattern", help="auto = nozzle line width."),
    ]

FDMTOPBOTTOM_PARAMS = [
        Param("top_layers", "int", 4, min=0, max=50, group="Shells",
              help="Number of solid top layers (0 = off)."),
        Param("bottom_layers", "int", 4, min=0, max=50, group="Shells",
              help="Number of solid bottom layers (0 = off)."),
        Param("pattern", "choice", "rectilinear", group="Solid fill",
              choices=[("rectilinear", "Rectilinear (alternating 90\u00b0)"),
                       ("lines", "Lines (same direction)"),
                       ("grid", "Grid")]),
        Param("angle", "float", 45.0, unit="\u00b0", min=-180, max=180, decimals=1, group="Solid fill"),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Solid fill", help="auto = wall line width."),
        Param("overlap", "float", 25.0, unit="%", min=-100, max=100, decimals=1, group="Solid fill",
              help="Overlap with the innermost wall (% of line width)."),
        Param("min_length", "float", 0.4, unit="mm", min=0, decimals=2, group="Solid fill"),
    ]
