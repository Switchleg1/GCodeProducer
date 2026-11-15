"""Built-in starter profiles, used to seed an empty library."""
from __future__ import annotations

from . import workflow as wf
from .profiles import LibrarySet, Profile


def builtin_profiles() -> list:
    return [
        Profile("machine", "Generic 220 FDM", workflow=wf.FDM, values={
            "bed_x": 220, "bed_y": 220, "height": 250,
            "print_speed": 60, "perimeter_speed": 45, "outer_perimeter_speed": 30,
            "infill_speed": 60, "travel_speed": 150, "first_layer_speed": 20,
        }),
        Profile("machine", "Generic 300 Router", workflow=wf.CAM, values={
            "work_x": 300, "work_y": 300, "work_z": 100,
            "safe_z": 15, "rapid_xy": 3000, "rapid_z": 1000, "max_feed": 2000,
        }),
        Profile("material", "PLA", values={
            "type": "PLA", "temp_nozzle": 205, "temp_nozzle_first": 210,
            "temp_bed": 60, "temp_bed_first": 60, "retract_length": 1.0,
        }),
        Profile("material", "PETG", values={
            "type": "PETG", "temp_nozzle": 235, "temp_nozzle_first": 240,
            "temp_bed": 80, "temp_bed_first": 80, "retract_length": 1.5, "fan_speed": 50,
        }),
        Profile("nozzle", "0.4 mm", values={"diameter": 0.4, "line_width": 0.45, "max_flow": 12}),
        Profile("nozzle", "0.6 mm", values={"diameter": 0.6, "line_width": 0.68, "max_flow": 20}),
        Profile("tool", "6 mm flat endmill", values={
            "tool_number": 1, "type": "endmill", "diameter": 6.0, "flutes": 2,
            "feed": 1000, "plunge_feed": 300, "spindle_rpm": 18000, "max_doc": 2.0}),
        Profile("tool", "3 mm flat endmill", values={
            "tool_number": 2, "type": "endmill", "diameter": 3.0, "flutes": 2,
            "feed": 600, "plunge_feed": 200, "spindle_rpm": 20000, "max_doc": 1.0}),
    ]


def seed(libset: LibrarySet, save: bool = True) -> int:
    """Populate every empty library with the starter profiles."""
    added = 0
    by_kind: dict = {}
    for p in builtin_profiles():
        by_kind.setdefault(p.kind, []).append(p)
    for kind, profs in by_kind.items():
        lib = libset[kind]
        if len(lib) == 0:
            for p in profs:
                lib.add(p)
                added += 1
    if save and added:
        libset.save()
    return added
