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
    Param("warning_dialog", "bool", True, group="Warnings", label="Show warning dialog after generation",
          help="Off still lists warnings in the log and blocks/confirms export as before."),
]
DEFAULTS = {p.name: p.default for p in SCHEMA}


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
    except (OSError, ValueError):
        pass          # corrupt preferences must not prevent start-up; defaults apply
    return validated(data)


def save(data: dict, root: Path | None = None) -> None:
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validated(data), indent=2), encoding="utf-8")


def validated(data: dict) -> dict:
    out = dict(DEFAULTS)
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
        else:
            out[p.name] = v
    return out


def pref(job, key):
    """Preference lookup that is safe for jobs built without preferences (CLI/tests)."""
    prefs = getattr(job, "preferences", None) or {}
    return prefs.get(key, DEFAULTS[key])
