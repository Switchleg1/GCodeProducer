"""Shared gcode constants and declarative tables."""
from __future__ import annotations
import re, ast, operator, gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.gcode.template_variable import Var
from gcodeproducer import __version__

FEATURE_TABLE = [
    ("outer_perimeter",   "Outer perimeter",      (1.00, 0.50, 0.10)),
    ("middle_perimeter",  "Middle perimeter",     (1.00, 0.72, 0.25)),
    ("inner_perimeter",   "Inner perimeter",      (1.00, 0.88, 0.35)),
    ("overhang_perimeter", "Overhang perimeter",  (0.15, 0.30, 1.00)),
    ("infill",            "Infill (sparse)",      (0.78, 0.22, 0.22)),
    ("dense_infill",      "Dense infill",         (0.85, 0.40, 0.40)),
    ("solid_infill",      "Solid infill",         (0.60, 0.25, 0.85)),
    ("top_infill",        "Top solid infill",     (0.95, 0.30, 0.50)),
    ("bridge",            "Bridge",               (0.30, 0.60, 1.00)),
    ("gap_fill",          "Gap fill",             (0.95, 0.95, 0.95)),
    ("skirt",             "Skirt / brim",         (0.00, 0.80, 0.60)),
    ("support",           "Support",              (0.45, 0.85, 0.25)),
    ("support_interface", "Support interface",    (0.20, 0.60, 0.30)),
    ("raft",              "Raft",                 (0.50, 0.50, 0.80)),
    ("prime_tower",       "Prime tower / wipe",   (0.70, 0.70, 0.30)),
    ("shield",            "Ooze shield",          (0.55, 0.55, 0.45)),
    ("ironing",           "Ironing",              (0.90, 0.60, 0.90)),
    ("custom",            "Custom / start-end",   (0.50, 0.50, 0.50)),
    # ---- CAM (machining)
    ("rapid",             "Rapid",                (1.00, 0.30, 0.30)),
    ("plunge",            "Plunge",               (0.95, 0.25, 0.95)),
    ("retract",           "Retract (feed up)",    (0.60, 0.60, 1.00)),
    ("lead_in",           "Lead-in (ramp / helix / arc)", (0.15, 0.90, 0.95)),
    ("lead_out",          "Lead-out",             (0.20, 0.55, 1.00)),
    ("slot",              "Slot",    (1.00, 0.55, 0.00)),
    ("high_engagement",   "High engagement",     (1.00, 0.20, 0.10)),
    ("cut",               "Cut",                  (0.30, 0.85, 0.35)),
    ("hsm",               "HSM",                  (0.20, 0.65, 1.00)),
    ("air",               "Air cut",              (0.55, 0.55, 0.55)),
    ("conflict",          "Conflict (wrong hand / uncertain)", (1.00, 0.95, 0.10)),
    ("collision",         "Collision (material contact)", (1.00, 0.00, 1.00)),
    ("unknown",           "Unknown",              (0.65, 0.65, 0.65)),
]

FEATURE_IDS = [f[0] for f in FEATURE_TABLE]

FEATURE_LABELS = {f[0]: f[1] for f in FEATURE_TABLE}

_FEATURE_COLORS = {f[0]: f[2] for f in FEATURE_TABLE}

CAM_FEATURES = ["rapid", "plunge", "retract", "lead_in", "lead_out", "slot", "high_engagement", "cut", "hsm", "air",
                "conflict", "collision"]

CAM_CUT_FEATURES = {"cut", "slot", "high_engagement", "hsm", "air", "conflict"}

FEATURE_TOOLTIPS = {"hsm": "HSM: low horizontal (radial) engagement, below the machine HSM threshold",
                    "conflict": "Cut segments the planner could not keep on the requested climb/conventional hand",
                    "collision": "Moves the stock checks flagged: rapid/spindle-off/unexpected contact, below-bottom or deep entry"}

PRINT_FEATURES = [f for f in FEATURE_IDS if f not in ("custom", "unknown") and f not in CAM_FEATURES]

FDM_FEATURES = PRINT_FEATURES

_WORD_RE = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")

_PAREN_RE = re.compile(r"\(([^)]*)\)")

TEXT_COMMANDS = {"M117", "M118", "M23", "M28", "M29", "M30", "M32", "M928", "M587", "M588", "M550", "M551", "M552"}

MOTION_COMMANDS = {"G0", "G1", "G2", "G3"}

DECIMALS = {"X": 3, "Y": 3, "Z": 3, "E": 5, "F": 1, "I": 4, "J": 4, "K": 4, "R": 4, "S": 2, "P": 2}

_EMPTY: dict = {}

_TAG = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}

_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge}

_FUNCS = {"round": round, "int": int, "float": float, "min": min, "max": max, "abs": abs, "str": str}

TEMPLATE_FDM, TEMPLATE_CAM, TEMPLATE_BOTH = (wf.FDM,), (wf.CAM,), (wf.FDM,wf.CAM)

VARIABLES = [
    # ---- general
    Var("machine", "General", "Machine profile name", "Generic 220 FDM"),
    Var("model", "General", "Model file name", "bracket.stl"),
    Var("date", "General", "Date the G-code was produced (YYYY-MM-DD)", "2025-01-31"),
    Var("time", "General", "Time the G-code was produced (HH:MM)", "14:05"),
    Var("version", "General", "GCodeProducer version", __version__),
    # ---- machine
    Var("bed_x", "Machine", "Bed / work area size X (mm)", 220.0),
    Var("bed_y", "Machine", "Bed / work area size Y (mm)", 220.0),
    Var("max_height", "Machine", "Build / work height (mm)", 250.0),
    Var("bed_center_x", "Machine", "X of the bed centre (mm)", 110.0),
    Var("bed_center_y", "Machine", "Y of the bed centre (mm)", 110.0),
    Var("relative_e", "Machine", "1 if extrusion is relative (M83), else 0", True, TEMPLATE_FDM),
    Var("heated_chamber", "Machine", "1 if the machine has a heated chamber", False, TEMPLATE_FDM),
    Var("wait_for_chamber", "Machine", "1 if the start should wait for the chamber (M191)", False, TEMPLATE_FDM),
    Var("max_nozzle_temp", "Machine", "Machine maximum nozzle temperature (\u00b0C)", 280.0, TEMPLATE_FDM),
    Var("max_bed_temp", "Machine", "Machine maximum bed temperature (\u00b0C)", 110.0, TEMPLATE_FDM),
    Var("max_chamber_temp", "Machine", "Machine maximum chamber temperature (\u00b0C)", 60.0, TEMPLATE_FDM),
    Var("clearance_z", "Machine", "Entry clearance Z in work coordinates (mm)", 5.0, TEMPLATE_CAM),
    Var("safe_z", "Machine", "Safe Z for rapids (mm)", 15.0, TEMPLATE_CAM),
    # ---- temperatures (material values, already capped at the machine limits)
    Var("nozzle_temp", "Temperatures", "Nozzle temperature (\u00b0C)", 205.0, TEMPLATE_FDM),
    Var("nozzle_temp_first", "Temperatures", "First-layer nozzle temperature (\u00b0C)", 210.0, TEMPLATE_FDM),
    Var("bed_temp", "Temperatures", "Bed temperature (\u00b0C)", 60.0, TEMPLATE_FDM),
    Var("bed_temp_first", "Temperatures", "First-layer bed temperature (\u00b0C)", 60.0, TEMPLATE_FDM),
    Var("chamber_temp", "Temperatures", "Chamber temperature (\u00b0C); 0 = none / no heated chamber", 0.0, TEMPLATE_FDM),
    # ---- tool / nozzle / material
    Var("tool", "Tool", "Tool / extruder number (T)", 0),
    Var("nozzle", "Tool", "Nozzle profile name", "0.4 mm", TEMPLATE_FDM),
    Var("nozzle_diameter", "Tool", "Nozzle diameter (mm)", 0.4, TEMPLATE_FDM),
    Var("line_width", "Tool", "Default line width (mm)", 0.45, TEMPLATE_FDM),
    Var("material", "Material", "Material profile name", "PLA", TEMPLATE_FDM),
    Var("material_type", "Material", "Material type (PLA, PETG, ABS ...)", "PLA", TEMPLATE_FDM),
    Var("filament_diameter", "Material", "Filament diameter (mm)", 1.75, TEMPLATE_FDM),
    Var("flow", "Material", "Flow multiplier (%)", 100.0, TEMPLATE_FDM),
    Var("fan_speed", "Material", "Part fan speed (%)", 100.0, TEMPLATE_FDM),
    Var("fan_speed_pwm", "Material", "Part fan speed as 0-255 (for M106 S)", 255, TEMPLATE_FDM),
    Var("retract_length", "Material", "Retraction length (mm)", 1.0, TEMPLATE_FDM),
    Var("retract_speed", "Material", "Retraction speed (mm/s)", 35.0, TEMPLATE_FDM),
    Var("tool_name", "Tool", "Cutter profile name", "6 mm flat endmill", TEMPLATE_CAM),
    Var("tool_diameter", "Tool", "Cutter diameter (mm)", 6.0, TEMPLATE_CAM),
    Var("spindle_rpm", "Tool", "Selected spindle speed (rpm)", 18000.0, TEMPLATE_CAM),
    Var("machining_material", "Stock", "Machining category (not FDM filament)", "non_iron_metal", TEMPLATE_CAM),
    Var("sfm", "Tool", "Configured tool/material SFM ceiling (ft/min)", 200.0, TEMPLATE_CAM),
    Var("chip_load", "Tool", "Configured tool/material chip load (mm/tooth)", .025, TEMPLATE_CAM),
    Var("axial_depth", "Layers", "Resolved maximum depth per pass (mm)", .75, TEMPLATE_CAM),
    Var("feed", "Tool", "Cutting feed (mm/min)", 1000.0, TEMPLATE_CAM),
    Var("plunge_feed", "Tool", "Plunge feed (mm/min)", 300.0, TEMPLATE_CAM),
    # ---- CAM blank
    Var("stock_material", "Stock", "Stock material name", "Aluminium", TEMPLATE_CAM),
    Var("stock_density", "Stock", "Stock density (g/cm³)", 2.7, TEMPLATE_CAM),
    Var("stock_width", "Stock", "Stock size X (mm)", 24.0, TEMPLATE_CAM),
    Var("stock_depth", "Stock", "Stock size Y (mm)", 24.0, TEMPLATE_CAM),
    Var("stock_height", "Stock", "Stock thickness Z (mm)", 22.0, TEMPLATE_CAM),
    Var("stock_top", "Stock", "Stock surface Z (mm)", 0.0, TEMPLATE_CAM),
    Var("stock_bottom", "Stock", "Stock bottom Z (mm)", -22.0, TEMPLATE_CAM),
    # ---- layers
    Var("layer_height", "Layers", "Layer height (mm)", 0.2, TEMPLATE_FDM),
    Var("first_layer_height", "Layers", "First layer height (mm)", 0.2, TEMPLATE_FDM),
    Var("current_layer_height", "Layers", "Height of the current layer (mm); the first layer at the start",
        0.2, TEMPLATE_FDM),
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

EPS_E = 1e-7

EPS_XYZ = 1e-7

EXTRUDE, TRAVEL, CUT, RAPID = 0, 1, 2, 3
RETRACT, UNRETRACT = 0, 1

KIND_NAMES = {EXTRUDE: "Extrusion", TRAVEL: "Travel", CUT: "Cut", RAPID: "Rapid"}

SOLID_KINDS = (EXTRUDE, CUT)

# Firmware motion assumed by the time estimate when the program does not say
# (``feed`` in mm/min for moves before any F word).
MOTION_DEFAULTS = {"print_acceleration": 1500., "travel_acceleration": 0., "junction_deviation": .013,
                   "feed": 1500.}
MOTION_COMMENT = "MOTION"                # ";MOTION key=value ..." header written by the FDM output
MOTION_KEYS = ("print_acceleration", "travel_acceleration", "junction_deviation")
MOTION_HEADER_LINES = 200               # how far to look for the ;MOTION header
