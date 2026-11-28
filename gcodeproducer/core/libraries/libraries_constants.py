"""Shared libraries constants and declarative tables."""
from __future__ import annotations
import re, gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.parameters.parameters_constants import ALL_ITEMS
from gcodeproducer.core.parameters.param import Param
from gcodeproducer.core.cam.cam_constants import material_parameters

_SLUG_RE = re.compile(r"[^a-z0-9]+")

KINDS = ("machine", "material", "nozzle", "tool")

KIND_WORKFLOW = {"material": wf.FDM, "nozzle": wf.FDM, "tool": wf.CAM}  # machine: both

KIND_LABEL = {"machine": "Machine", "material": "Material", "nozzle": "Nozzle", "tool": "Tool"}

def _machine_schema(workflow: str) -> list:
    from gcodeproducer.core.gcode.gcode_constants import DEFAULT_END
    from gcodeproducer.core.gcode.gcode_constants import DEFAULT_START
    w = wf.normalize(workflow)
    common_tail = [
        Param("start_gcode", "gcode", default=DEFAULT_START[w], label="Start G-code", group="G-code",
              help="Written before the job. A template: {variables}, {if ...}{else}{endif}. "
                   "Empty = the default."),
        Param("end_gcode", "gcode", default=DEFAULT_END[w], label="End G-code", group="G-code",
              help="Written after the job. A template like the start G-code. Empty = the default."),
    ]
    if workflow == wf.CAM:
        return [
            Param("work_x", "float", 300.0, unit="mm", group="Work area"),
            Param("work_y", "float", 300.0, unit="mm", group="Work area"),
            Param("work_z", "float", 100.0, unit="mm", group="Work area"),
            Param("origin", "choice", "front-left-bottom", group="Work area",
                  choices=["front-left-bottom", "center", "front-left-top"]),
            Param("safe_z", "float", 15.0, unit="mm", group="Clearance",
                  help="Retract height for rapids between features."),
            Param("clearance_z", "float", 5.0, unit="mm", group="Clearance",
                  help="Stored only: entries use the global lead-in and short-retract clearances (Settings)."),
            Param("rapid_xy", "float", 3000.0, unit="mm/min", group="Speeds & feeds"),
            Param("rapid_z", "float", 1000.0, unit="mm/min", group="Speeds & feeds"),
            Param("max_feed", "float", 2000.0, unit="mm/min", min=0, group="Speeds & feeds",
                  help="Caps cutting, engagement-adjusted/link and plunge G1 feeds; 0 = no cap. Not a spindle or G0 limit."),
            Param("auto_tool_change", "bool", True, label="Automatic tool changer", group="Tool changes",
                  help="On: tool groups are joined in one program with M5 / T M6 / M3. Off: one G-code file "
                       "per tool group, each wrapped in the start and end G-code, for manual tool changes."),
            Param("max_tool_number", "int", 0, min=0, max=999, label="Highest tool number", group="Tool changes",
                  help="Largest T number the tool changer can load (pockets / slots). Generation warns when a "
                       "tool group uses a higher one. 0 = no limit. Ignored without an automatic tool changer."),
            Param("spindle_min", "float", 6000.0, unit="rpm", group="Spindle"),
            Param("spindle_max", "float", 24000.0, unit="rpm", group="Spindle"),
            Param("chuck_diameter", "float", 0.0, unit="mm", min=0, group="Spindle", label="Chuck diameter",
                  help="Widest diameter of the chuck or collet nut. With it set, the chuck may go down into the "
                       "part: every move is checked so that the chuck (its face a tool stickout above the tip) "
                       "never meets material. 0 = not set: the chuck may not go below the top of the stock."),
            Param("chuck_stickout", "float", 0.0, unit="mm", min=0, group="Spindle", label="Chuck stickout",
                  help="How far the chuck or collet nut stands out below the spindle body. The chuck may go this "
                       "far below the top of the stock before the spindle body would meet it. Used with Chuck "
                       "diameter."),
            Param("units", "choice", "mm", choices=["mm", "inch"], group="Work area"),
            Param("cut_direction", "choice", "climb", label="Default cutting direction", group="Toolpaths",
                  choices=[("climb", "Climb"), ("conventional", "Conventional"), ("meander", "Meander")],
                  help="Requested one-sided hand for CAM pockets/profiles (M3). Remaining material chooses "
                       "direction; full slots are neutral. Operations may override. Meander alternates one-sided passes."),
            Param("hsm_engagement_threshold", "float", 15., min=1, max=79, unit="%", group="Engagement",
                  label="HSM / Cut boundary",
                  help="Radial engagement below this is HSM (light, high-speed-style cutting). Keep it well away "
                       "from your usual stepover: a stepover equal to the boundary flips HSM/Cut on grid noise."),
            Param("high_engagement_threshold", "float", 80., min=1, max=99, unit="%", group="Engagement",
                  label="High engagement above"),
            Param("slot_engagement_threshold", "float", 95., min=1, max=100, unit="%", group="Engagement",
                  label="Slot at / above"),
            Param("high_engagement_feed", "float", 75., min=1, max=300, unit="%", group="Engagement",
                  label="High engagement feed modifier"),
            Param("slotting_feed", "float", 50., min=1, max=300, unit="%", group="Engagement",
                  label="Slot feed modifier"),
            Param("plunge_feed_modifier", "float", 30., min=1, max=100, unit="%", group="Engagement",
                  label="Plunge feed modifier",
                  help="Feed straight down into material, as a % of the tool feed. Descents between level and "
                       "straight down blend from the cut feed through the lead-in feed to this. Operations may override."),
            Param("stock_resolution", "float", .5, min=.02, max=5, unit="mm", group="Material simulation", hidden=True,
                  label="Legacy stock resolution (global settings now own this)",
                  help="Ignored. The material grid resolution is a global application setting (Settings dialog)."),
            Param("allowed_tools", "multi", ALL_ITEMS, choices_from="tool", group="Allowed consumables",
                  help="Tools from the tool library that are mounted / available."),
        ] + common_tail
    # FDM
    return [
        Param("bed_x", "float", 220.0, unit="mm", group="Build volume"),
        Param("bed_y", "float", 220.0, unit="mm", group="Build volume"),
        Param("height", "float", 250.0, unit="mm", group="Build volume"),
        Param("origin_center", "bool", False, group="Build volume",
              help="Origin at bed centre (delta / some corexy) instead of front-left."),
        # limits: what the machine can do. The *requested* speeds are process settings
        # (Process > Speed & travel); the slicer caps them at these values.
        Param("max_print_speed", "float", 200.0, unit="mm/s", min=1, decimals=0, group="Speed limits",
              help="Fastest printing move. Process speeds above this are capped."),
        Param("max_travel_speed", "float", 300.0, unit="mm/s", min=1, decimals=0, group="Speed limits",
              help="Fastest travel (non-printing) move."),
        Param("max_acceleration", "float", 5000.0, unit="mm/s\u00b2", min=0, decimals=0, group="Speed limits",
              help="Highest acceleration the process may request (0 = no limit)."),
        Param("print_acceleration", "float", 1500.0, unit="mm/s\u00b2", min=1, decimals=0, group="Motion",
              label="Firmware print acceleration",
              help="Acceleration the firmware uses for printing moves when the process does not set one (M204 P/S). "
                   "Used for the print time estimate."),
        Param("travel_acceleration", "float", 0.0, unit="mm/s\u00b2", min=0, decimals=0, group="Motion",
              label="Firmware travel acceleration",
              help="Acceleration for non-printing moves (M204 T); 0 = same as print acceleration. "
                   "Used for the print time estimate."),
        Param("junction_deviation", "float", 0.013, unit="mm", min=0, decimals=3, group="Motion",
              label="Junction deviation",
              help="Cornering setting of the firmware (Marlin default 0.013 mm). Klipper: square_corner_velocity\u00b2 "
                   "\u00d7 0.414 / acceleration. Used for the print time estimate."),
        Param("max_flow", "float", 0.0, unit="mm\u00b3/s", min=0, decimals=1, group="Speed limits",
              help="Machine (hot-end / extruder) volumetric limit; 0 = only the nozzle's limit applies."),
        Param("max_nozzle_temp", "float", 280.0, unit="\u00b0C", min=0, decimals=0, group="Temperature limits",
              help="Material nozzle temperatures above this are capped."),
        Param("max_bed_temp", "float", 110.0, unit="\u00b0C", min=0, decimals=0, group="Temperature limits"),
        Param("heated_chamber", "bool", False, group="Chamber",
              help="The machine has a heated / controlled chamber (M141)."),
        Param("max_chamber_temp", "float", 60.0, unit="\u00b0C", min=0, decimals=0, group="Chamber",
              help="Material chamber temperatures above this are capped."),
        Param("wait_for_chamber", "bool", False, group="Chamber",
              help="Wait for the chamber to reach temperature before printing (M191)."),
        Param("relative_e", "bool", True, group="Motion", help="Use M83 relative extrusion."),
        Param("allowed_nozzles", "multi", ALL_ITEMS, choices_from="nozzle", group="Allowed consumables"),
        Param("allowed_materials", "multi", ALL_ITEMS, choices_from="material", group="Allowed consumables"),
    ] + common_tail

_MATERIAL_SCHEMA = [
    Param("type", "choice", "PLA", group="General",
          choices=["PLA", "PETG", "ABS", "ASA", "TPU", "Nylon", "PC", "Other"]),
    Param("filament_diameter", "float", 1.75, unit="mm", group="General"),
    Param("density", "float", 1.24, unit="g/cm\u00b3", group="General"),
    Param("temp_nozzle", "float", 205.0, unit="\u00b0C", group="Temperature"),
    Param("temp_nozzle_first", "float", 210.0, unit="\u00b0C", group="Temperature",
          label="First layer nozzle"),
    Param("temp_bed", "float", 60.0, unit="\u00b0C", group="Temperature"),
    Param("temp_bed_first", "float", 60.0, unit="\u00b0C", group="Temperature", label="First layer bed"),
    Param("temp_chamber", "float", 0.0, unit="\u00b0C", min=0, group="Temperature", label="Chamber",
          help="Chamber temperature for this material (0 = not needed). Only used on machines with a heated "
               "chamber; capped at the machine's maximum."),
    Param("flow", "float", 100.0, unit="%", group="Flow", help="Extrusion multiplier."),
    Param("fan_speed", "float", 100.0, unit="%", group="Cooling"),
    Param("fan_first_layers", "int", 1, group="Cooling", help="Layers with the fan off."),
    Param("min_layer_time", "float", 8.0, unit="s", group="Cooling",
          help="Slow down thin layers to at least this time."),
    Param("bridge_min_area", "float", 0., unit="mm²", min=0, group="Bridging", label="Minimum unsupported area",
          help="Minimum area of one unsupported patch before growth. 0 disables bridge generation."),
    Param("bridge_speed_mode", "choice", "fixed", group="Bridging", label="Speed mode",
          choices=[("fixed", "Fixed speed"), ("modifier", "Percentage of solid infill speed")]),
    Param("bridge_speed", "float", 25., unit="mm/s", min=1, group="Bridging", label="Fixed speed"),
    Param("bridge_speed_modifier", "float", 65., unit="%", min=1, max=300,
          group="Bridging", label="Speed modifier"),
    Param("bridge_cooling_mode", "choice", "fixed", group="Bridging", label="Cooling mode",
          choices=[("fixed", "Fixed fan speed"), ("modifier", "Percentage of normal cooling")]),
    Param("bridge_cooling", "float", 100., unit="%", min=0, max=100, group="Bridging", label="Fixed fan speed"),
    Param("bridge_cooling_modifier", "float", 100., unit="%", min=0, max=500,
          group="Bridging", label="Cooling modifier"),
    Param("bridge_flow", "float", 100., unit="%", min=1, max=300, group="Bridging", label="Flow modifier",
          help="Percentage of this material's normal extrusion flow."),
    Param("bridge_growth", "float", 0.8, unit="mm", min=0, group="Bridging", label="Anchor growth",
          help="Grow the unsupported patch in every direction, clipped to the printable fill area."),
    Param("retract_length", "float", 1.0, unit="mm", group="Retraction"),
    Param("retract_speed", "float", 35.0, unit="mm/s", group="Retraction"),
    Param("zhop", "float", 0.0, unit="mm", group="Retraction"),
]

_NOZZLE_SCHEMA = [
    Param("diameter", "float", 0.4, unit="mm", group="General"),
    Param("line_width", "float", 0.45, unit="mm", group="General",
          help="Default extrusion width (auto = 1.1 \u00d7 diameter)."),
    Param("max_flow", "float", 12.0, unit="mm\u00b3/s", group="Limits"),
    Param("max_layer_height", "float", 0.32, unit="mm", group="Limits",
          help="Usually ~0.8 \u00d7 diameter."),
    Param("min_layer_height", "float", 0.08, unit="mm", group="Limits"),
]

_TOOL_SCHEMA = [
    Param("tool_number", "int", 1, group="General", help="T-number / pocket."),
    Param("type", "choice", "endmill", group="General",
          choices=["endmill", "ballnose", "vbit", "drill", "chamfer", "facemill", "engraver"]),
    Param("diameter", "float", 6.0, unit="mm", group="General"),
    Param("flutes", "int", 2, group="General"),
    Param("length", "float", 20.0, unit="mm", min=0, group="General", label="Flute length",
          help="Length of the cutting flutes. An operation may not cut deeper than this below the material "
               "around it (the shank would rub the wall). 0 = not checked."),
    Param("stickout", "float", 0.0, unit="mm", min=0, group="General", label="Stickout length",
          help="From the collet face to the tip, as the tool is set in the spindle. An operation may not reach "
               "deeper than this below the top of the stock (the collet would hit it). 0 = not set: not checked."),
    Param("vangle", "float", 0.0, unit="\u00b0", group="General", label="V angle",
          help="Included angle for v-bits / engravers."),
    Param("feed", "float", 800.0, unit="mm/min", group="Fixed rates (calculation off)", label="Fixed cut feed",
          help="Used with SFM calculation off; operation unlocks can override calculated or fixed bases."),
    Param("plunge_feed", "float", 300.0, unit="mm/min", group="Fixed rates (calculation off)", label="Fixed lead-in feed",
          help="Lead-in ramps, arcs and lead-outs with calculation off. The plunge feed is the machine's Plunge feed "
               "modifier (operations may override)."),
    Param("spindle_rpm", "float", 18000.0, unit="rpm", group="Fixed rates (calculation off)", label="Fixed spindle RPM"),
    Param("max_doc", "float", 2.0, unit="mm", min=0, group="Engagement", label="Max depth/pass",
          help="Positive values cap axial depth; 0 disables this cap, not a safety recommendation."),
    Param("stepover", "float", 40.0, unit="%", group="Engagement",
          help="Radial engagement as a % of diameter."),
    Param("low_engagement_feed", "float", 100.0, unit="%", min=1, max=300, decimals=0,
          label="HSM feed", group="Engagement feeds",
          help="HSM = low horizontal (radial) engagement. Percentage of base cutting feed; operations may override. Engagement is estimated."),
    Param("standard_engagement_feed", "float", 100.0, unit="%", min=1, max=300, decimals=0,
          label="Cut feed", group="Engagement feeds",
          help="May exceed 100% when calibrated for the cutter/material; capped by machine max feed."),
    Param("high_engagement_feed", "float", 75.0, unit="%", min=1, max=300, decimals=0,
          label="Legacy high engagement feed (machine now owns default)", group="Engagement feeds", hidden=True),
    Param("slotting_feed", "float", 50.0, unit="%", min=1, max=300, decimals=0,
          label="Legacy slot feed (machine now owns default)", group="Engagement feeds", hidden=True,
          help="Full-width slots have no single climb/conventional hand. Percentage of base cutting feed."),
]

_TOOL_SCHEMA += material_parameters()

PROFILE_SCHEMAS = {
    "material": _MATERIAL_SCHEMA,
    "nozzle": _NOZZLE_SCHEMA,
    "tool": _TOOL_SCHEMA,
}

BUILTIN_PROFILE_SPECS = (
    {"kind": "machine", "name": "Generic 220 FDM", "workflow": wf.FDM, "values": {
            "bed_x": 220, "bed_y": 220, "height": 250,
            "max_print_speed": 200, "max_travel_speed": 300, "max_acceleration": 5000,
            "max_nozzle_temp": 280, "max_bed_temp": 110,
        }},
    {"kind": "machine", "name": "Generic 300 Router", "workflow": wf.CAM, "values": {
            "work_x": 300, "work_y": 300, "work_z": 100,
            "safe_z": 15, "rapid_xy": 3000, "rapid_z": 1000, "max_feed": 2000,
        }},
    {"kind": "material", "name": "PLA", "values": {
            "type": "PLA", "temp_nozzle": 205, "temp_nozzle_first": 210,
            "temp_bed": 60, "temp_bed_first": 60, "retract_length": 1.0,
        }},
    {"kind": "material", "name": "PETG", "values": {
            "type": "PETG", "temp_nozzle": 235, "temp_nozzle_first": 240,
            "temp_bed": 80, "temp_bed_first": 80, "retract_length": 1.5, "fan_speed": 50,
        }},
    {"kind": "material", "name": "ABS", "values": {
            "type": "ABS", "density": 1.04, "temp_nozzle": 245, "temp_nozzle_first": 250,
            "temp_bed": 100, "temp_bed_first": 100, "temp_chamber": 45, "fan_speed": 20,
            "retract_length": 1.0,
        }},
    {"kind": "nozzle", "name": "0.4 mm", "values": {"diameter": 0.4, "line_width": 0.45, "max_flow": 12}},
    {"kind": "nozzle", "name": "0.6 mm", "values": {"diameter": 0.6, "line_width": 0.68, "max_flow": 20}},
    {"kind": "tool", "name": "6 mm flat endmill", "values": {
            "tool_number": 1, "type": "endmill", "diameter": 6.0, "flutes": 2, "length": 20.0, "stickout": 30.0,
            "feed": 1000, "plunge_feed": 300, "spindle_rpm": 18000, "max_doc": 2.0}},
    {"kind": "tool", "name": "3 mm flat endmill", "values": {
            "tool_number": 2, "type": "endmill", "diameter": 3.0, "flutes": 2, "length": 12.0, "stickout": 20.0,
            "feed": 600, "plunge_feed": 200, "spindle_rpm": 20000, "max_doc": 1.0}},
)

BUILTIN_FDM_PROCESSES = (
    {"name": "0.20 mm Standard", "layer_height": 0.2, "perimeters": 2, "density": 20, "pattern": "grid"},
    {"name": "0.30 mm Draft", "layer_height": 0.3, "first_layer_height": 0.3, "perimeters": 2, "density": 15, "pattern": "grid"},
    {"name": "0.12 mm Fine", "layer_height": 0.12, "perimeters": 3, "density": 20, "pattern": "triangles", "top": 6, "bottom": 5},
    {"name": "Strong (cubic 40%)", "layer_height": 0.2, "perimeters": 4, "density": 40, "pattern": "cubic", "top": 5, "bottom": 5, "adhesion": "brim", "brim_width": 6.0},
)

BUILTIN_CAM_PROCESSES = (
    "Profile cut",
)
