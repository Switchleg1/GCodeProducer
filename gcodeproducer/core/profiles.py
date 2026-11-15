"""Profiles and libraries.

GCodeProducer keeps four kinds of reusable *profile* and stores each kind in
its **own library** (a directory of JSON files), so they can be shared and
versioned independently:

======================  ========  ==================================================
kind                    workflow  holds
======================  ========  ==================================================
``machine``             fdm/cam   build volume, kinematics, **speeds / feeds**,
                                  start / end G-code and the list of consumables it
                                  *allows* (which nozzles / materials / tools are
                                  available on this machine)
``material``            fdm       filament: temperatures, flow, cooling, retraction
``nozzle``              fdm       hot-end orifice: diameter, max flow, line width
``tool``                cam       cutter: type, diameter, flutes, feeds & speeds
======================  ========  ==================================================

A **machine** picks which tools / materials / nozzles are available (via its
``allowed_*`` fields); the slice pipeline only offers the operator consumables
the selected machine allows.  Speeds and feeds live on the machine profile, so
a given machine runs every material / tool at its own rates.

Each kind has a declarative :class:`~gcodeproducer.core.params.Param` schema,
so the GUI form and CLI options are generated the same way module parameters
are in GCodeTools.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import workflow as wf
from .params import ALL_ITEMS, Param, resolve_params

# --------------------------------------------------------------------------
# Profile kinds and which workflow(s) they belong to
KINDS = ("machine", "material", "nozzle", "tool")
KIND_WORKFLOW = {"material": wf.FDM, "nozzle": wf.FDM, "tool": wf.CAM}  # machine: both
KIND_LABEL = {"machine": "Machine", "material": "Material", "nozzle": "Nozzle", "tool": "Tool"}


# --------------------------------------------------------------------------
# Schemas
def _machine_schema(workflow: str) -> list:
    from .gcode_vars import DEFAULT_END, DEFAULT_START
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
            Param("clearance_z", "float", 5.0, unit="mm", group="Clearance"),
            Param("rapid_xy", "float", 3000.0, unit="mm/min", group="Speeds & feeds"),
            Param("rapid_z", "float", 1000.0, unit="mm/min", group="Speeds & feeds"),
            Param("max_feed", "float", 2000.0, unit="mm/min", min=0, group="Speeds & feeds",
                  help="Caps cutting, engagement-adjusted/link and plunge G1 feeds; 0 = no cap. Not a spindle or G0 limit."),
            Param("spindle_min", "float", 6000.0, unit="rpm", group="Spindle"),
            Param("spindle_max", "float", 24000.0, unit="rpm", group="Spindle"),
            Param("units", "choice", "mm", choices=["mm", "inch"], group="Work area"),
            Param("cut_direction", "choice", "climb", label="Default cutting direction", group="Toolpaths",
                  choices=[("climb", "Climb"), ("conventional", "Conventional"), ("meander", "Meander")],
                  help="Requested one-sided hand for CAM pockets/profiles (M3). Remaining material chooses "
                       "direction; full slots are neutral. Operations may override. Meander alternates one-sided passes."),
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
    Param("length", "float", 20.0, unit="mm", group="General", help="Flute / cutting length."),
    Param("vangle", "float", 0.0, unit="\u00b0", group="General", label="V angle",
          help="Included angle for v-bits / engravers."),
    Param("feed", "float", 800.0, unit="mm/min", group="Feeds & speeds"),
    Param("plunge_feed", "float", 300.0, unit="mm/min", group="Feeds & speeds"),
    Param("spindle_rpm", "float", 18000.0, unit="rpm", group="Feeds & speeds"),
    Param("max_doc", "float", 2.0, unit="mm", group="Engagement", label="Max depth/pass"),
    Param("stepover", "float", 40.0, unit="%", group="Engagement",
          help="Radial engagement as a % of diameter."),
    Param("low_engagement_feed", "float", 100.0, unit="%", min=1, max=300, decimals=0,
          label="Low engagement feed (<40%)", group="Engagement feeds",
          help="Percentage of base cutting feed; operations may override. Engagement is estimated."),
    Param("standard_engagement_feed", "float", 100.0, unit="%", min=1, max=300, decimals=0,
          label="Standard engagement feed (40–70%)", group="Engagement feeds",
          help="May exceed 100% when calibrated for the cutter/material; capped by machine max feed."),
    Param("high_engagement_feed", "float", 75.0, unit="%", min=1, max=300, decimals=0,
          label="High engagement feed (>70%, below slot)", group="Engagement feeds"),
    Param("slotting_feed", "float", 50.0, unit="%", min=1, max=300, decimals=0,
          label="Slotting feed (95–100%)", group="Engagement feeds",
          help="Full-width slots have no single climb/conventional hand. Percentage of base cutting feed."),
]


def schema(kind: str, workflow: str = wf.FDM) -> list:
    """Return the :class:`Param` list for a profile ``kind``."""
    if kind == "machine":
        return _machine_schema(wf.normalize(workflow))
    if kind == "material":
        return list(_MATERIAL_SCHEMA)
    if kind == "nozzle":
        return list(_NOZZLE_SCHEMA)
    if kind == "tool":
        return list(_TOOL_SCHEMA)
    raise ValueError(f"unknown profile kind '{kind}'")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", str(name).strip().lower()).strip("-")
    return s or "profile"


# --------------------------------------------------------------------------
@dataclass
class Profile:
    """One reusable profile (machine / material / nozzle / tool)."""
    kind: str
    name: str
    values: dict = field(default_factory=dict)
    workflow: str = wf.FDM               # machine: its workflow; others: fixed by kind
    id: str = ""
    path: Optional[str] = None           # file it was loaded from / saved to

    def __post_init__(self):
        if self.kind in KIND_WORKFLOW:
            self.workflow = KIND_WORKFLOW[self.kind]
        else:
            self.workflow = wf.normalize(self.workflow)
        if not self.id:
            self.id = slugify(self.name)

    # ------------------------------------------------------------- schema
    def schema(self) -> list:
        return schema(self.kind, self.workflow)

    def resolved(self) -> dict:
        """Values with defaults filled and coerced to the right types.

        Keys that are no longer part of the schema (settings removed or moved, e.g.
        the speeds that moved from the machine to the process) are ignored, so older
        profile files keep loading."""
        known = {p.name for p in self.schema()}
        return resolve_params(self.schema(), {k: v for k, v in self.values.items() if k in known})

    def get(self, key: str, default=None):
        v = self.resolved()
        return v.get(key, default)

    # ---------------------------------------------------- allowed (machine)
    def allows(self, kind: str, profile_id: str) -> bool:
        """Machine only: True if ``profile_id`` of ``kind`` is available here."""
        if self.kind != "machine":
            return True
        sel = self.get(f"allowed_{kind}s")
        if sel in (ALL_ITEMS, None) or sel == []:
            return sel != []        # [] = none allowed, "*"/None = all allowed
        return profile_id in sel

    # ----------------------------------------------------------- persist
    def to_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, "name": self.name,
                "workflow": self.workflow, "values": dict(self.values)}

    @classmethod
    def from_dict(cls, d: dict, path: Optional[str] = None) -> "Profile":
        return cls(kind=d["kind"], name=d.get("name", d.get("id", "")),
                   values=dict(d.get("values", {})), workflow=d.get("workflow", wf.FDM),
                   id=d.get("id", ""), path=path)

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        self.path = path

    @classmethod
    def load(cls, path: str) -> "Profile":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh), str(path))


# --------------------------------------------------------------------------
class Library:
    """A collection of profiles of one ``kind``, backed by a directory."""

    def __init__(self, kind: str, directory: Optional[Path] = None):
        self.kind = kind
        self.directory = Path(directory) if directory else None
        self._items: dict[str, Profile] = {}

    def add(self, profile: Profile) -> Profile:
        if profile.kind != self.kind:
            raise ValueError(f"{profile.kind} profile added to {self.kind} library")
        self._items[profile.id] = profile
        return profile

    def remove(self, profile_id: str) -> None:
        self._items.pop(profile_id, None)

    def get(self, profile_id: str) -> Profile:
        return self._items[profile_id]

    def all(self, workflow: Optional[str] = None) -> list:
        out = list(self._items.values())
        if workflow and self.kind == "machine":
            out = [p for p in out if p.workflow == wf.normalize(workflow)]
        return out

    def ids(self) -> list:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    # ----------------------------------------------------------- persist
    def load_dir(self, directory: Optional[Path] = None) -> int:
        d = Path(directory) if directory else self.directory
        if not d or not d.is_dir():
            return 0
        self.directory = d
        n = 0
        for f in sorted(d.glob("*.json")):
            try:
                p = Profile.load(str(f))
                if p.kind == self.kind:
                    self.add(p)
                    n += 1
            except Exception:
                pass
        return n

    def save_all(self, directory: Optional[Path] = None) -> None:
        d = Path(directory) if directory else self.directory
        if not d:
            raise ValueError("no directory set for library")
        d.mkdir(parents=True, exist_ok=True)
        for p in self._items.values():
            p.save(str(d / f"{p.id}.json"))


# --------------------------------------------------------------------------
class LibrarySet:
    """All libraries under one root directory (``<root>/<kind>s/*.json``)."""

    def __init__(self, root: Optional[Path] = None):
        from .process import ProcessLibrary
        self.root = Path(root) if root else default_root()
        self.libraries = {k: Library(k, self.root / f"{k}s") for k in KINDS}
        self.processes = ProcessLibrary(self.root / "processes")

    def __getitem__(self, kind: str) -> Library:
        return self.libraries[kind]

    @property
    def machines(self) -> Library:
        return self.libraries["machine"]

    def load(self) -> "LibrarySet":
        for lib in self.libraries.values():
            lib.load_dir()
        self.processes.load_dir()
        return self

    def save(self) -> None:
        for lib in self.libraries.values():
            lib.save_all()
        self.processes.save_all()

    # ------------------------------------------- consumables for a machine
    def consumables_for(self, machine: Profile, kind: str) -> list:
        """Profiles of ``kind`` that ``machine`` allows (respecting workflow)."""
        wfl = KIND_WORKFLOW.get(kind)
        if wfl and wfl != machine.workflow:
            return []
        return [p for p in self.libraries[kind].all() if machine.allows(kind, p.id)]

    def library_kinds(self, workflow: str) -> tuple:
        return wf.LIBRARIES[wf.normalize(workflow)]


def default_root() -> Path:
    import os
    env = os.environ.get("GCODEPRODUCER_LIBRARY")
    if env:
        return Path(env)
    return Path.home() / ".gcodeproducer"
