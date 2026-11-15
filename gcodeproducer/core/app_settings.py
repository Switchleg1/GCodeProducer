"""Global application preferences (Qt-free; shared with the compute process).

Stored as JSON next to the profile libraries. Unlike machine/tool profiles these
apply to every job, and unlike QSettings window state they influence generated
output, so they travel inside ``Job.preferences``.
"""
from __future__ import annotations

import json
from pathlib import Path

from .params import Param
from .profiles import default_root

SCHEMA = [
    Param("skip_air_cuts", "bool", True, group="CAM toolpaths", label="Remove air cutting",
          help="Start each operation at the first depth that still holds material (estimated from earlier "
               "operations) and drop pocket contours that lie entirely in already-removed material. "
               "Off keeps every requested depth pass."),
    Param("short_retracts", "bool", True, group="CAM toolpaths", label="Short retracts within cleared material",
          help="Between entries, retract only to clearance above the CURRENT material along the travel (from the "
               "material simulation) and rapid down to the entry plane, instead of returning to safe Z and feeding "
               "down through air. Needs allocated stock. Fixtures/clamps are not modelled: turn off if they stand "
               "above the material."),
    Param("retract_clearance", "float", 1.0, min=.1, max=100, unit="mm", group="CAM toolpaths",
          label="Short retract clearance",
          help="With short retracts, rapid travels pass this far above the highest current material under the "
               "cutter along the move (never above safe Z)."),
    Param("lead_clearance", "float", .5, min=.05, max=50, unit="mm", group="CAM toolpaths",
          label="Lead-in start above material",
          help="A lead-in ramp starts this far above the current local material (the tool rapids down to "
               "there). The machine clearance Z still sets the height of short rapid travels."),
    Param("stock_resolution", "float", .2, min=.02, max=5, unit="mm", group="Material simulation",
          label="Material grid resolution",
          help="Height-field cell size for current-material checks, lead entry heights and the Material display. "
               "Finer grids catch smaller contacts but cost memory/time; the cell limit below can coarsen it."),
    Param("stock_max_cells", "int", 2_000_000, min=10_000, max=50_000_000, group="Material simulation",
          label="Maximum grid cells",
          help="Upper bound on height-field cells. When width x depth / resolution^2 exceeds it the grid is "
               "coarsened and a warning is issued."),
    Param("highlight_conflicts", "bool", True, group="Warnings", label="Colour conflicts and collisions",
          help="Recolour flagged moves as Conflict / Collision features in Feature colour mode."),
    Param("default_material_limit", "float", 0.0, min=-1000, max=1000, unit="mm", group="Default operation settings",
          label="Material boundary limit",
          help="Initial value for new operations. Where a pocket region reaches the blank edge, the cutter's outer "
               "edge may travel this far relative to that edge: 0 touches it, -1 leaves 1 mm of material, "
               "+1 lets the tool pass 1 mm beyond it."),
    Param("default_area_order", "choice", "area", group="Default operation settings",
          label="Area order", choices=[("area", "Each area to full depth"), ("depth", "Each depth across all areas")],
          help="Initial order for new operations with separate machining areas. Each area to full depth finishes "
               "one area before moving to the next; each depth visits all areas before stepping down."),
    Param("default_overcut", "float", 0.0, min=0, max=1000, unit="mm", group="Default operation settings",
          label="Pocket overcut into void",
          help="Initial overcut for new Pocket operations."),
]

# Pop-up messages that offer "Don't show this again". Every message is still
# recorded in the Messages panel when its pop-up is disabled.
MESSAGES = {
    "cam_warnings": "CAM material / engagement warnings after generation",
    "cam_stale_export": "CAM export blocked: regenerate paths",
    "cannot_slice": "Cannot slice / generate (setup error)",
    "slice_failed": "Slicing / generation failed",
    "auto_generate_failed": "Automatic support generation failed",
    "import_failed": "Model import failed",
    "no_model": "No model loaded",
    "no_machine": "No machine for this workflow",
    "outside_volume": "Model outside the build volume (continue without asking)",
    "settings_save_failed": "Settings could not be saved",
    "opengl": "OpenGL errors",
}

DEFAULTS = {p.name: p.default for p in SCHEMA}
DEFAULTS["messages"] = {key: True for key in MESSAGES}


def settings_path(root: Path | None = None) -> Path:
    return Path(root or default_root()) / "settings.json"


def load(root: Path | None = None) -> dict:
    path = settings_path(root)
    data = dict(DEFAULTS)
    try:
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULTS})
                if stored.get("warning_dialog") is False:      # pre-'messages' preference
                    data["messages"] = {**DEFAULTS["messages"], **dict(data.get("messages") or {}), "cam_warnings": False}
    except (OSError, ValueError):
        pass          # corrupt preferences must not prevent start-up; defaults apply
    return validated(data)


def save(data: dict, root: Path | None = None) -> None:
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validated(data), indent=2), encoding="utf-8")


def validated(data: dict) -> dict:
    out = dict(DEFAULTS)
    stored = data.get("messages")
    out["messages"] = {key: bool(stored.get(key, True)) if isinstance(stored, dict) else True for key in MESSAGES}
    for p in SCHEMA:
        v = data.get(p.name, p.default)
        if p.type == "bool":
            out[p.name] = bool(v)
        elif p.type in ("float", "int"):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = p.default
            if v != v:          # NaN
                v = p.default
            if p.min is not None:
                v = max(p.min, v)
            if p.max is not None:
                v = min(p.max, v)
            out[p.name] = int(v) if p.type == "int" else v
        elif p.type == "choice":
            out[p.name] = v if v in p.choice_values() else p.default
        else:
            out[p.name] = v
    return out


def pref(job, key):
    """Preference lookup that is safe for jobs built without preferences (CLI/tests)."""
    prefs = getattr(job, "preferences", None) or {}
    return prefs.get(key, DEFAULTS[key])


def message_enabled(prefs: dict, key: str) -> bool:
    return bool((prefs.get("messages") or {}).get(key, True))
