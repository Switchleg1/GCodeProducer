"""Built-in starter profiles, used to seed an empty library."""
from __future__ import annotations

from . import workflow as wf
from .pipeline import SlicePipeline
from .process import ProcessPreset
from .profiles import LibrarySet, Profile


def builtin_profiles() -> list:
    return [
        Profile("machine", "Generic 220 FDM", workflow=wf.FDM, values={
            "bed_x": 220, "bed_y": 220, "height": 250,
            "max_print_speed": 200, "max_travel_speed": 300, "max_acceleration": 5000,
            "max_nozzle_temp": 280, "max_bed_temp": 110,
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
        Profile("material", "ABS", values={
            "type": "ABS", "density": 1.04, "temp_nozzle": 245, "temp_nozzle_first": 250,
            "temp_bed": 100, "temp_bed_first": 100, "temp_chamber": 45, "fan_speed": 20,
            "retract_length": 1.0,
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


def _fdm_process(name, *, layer_height, first_layer_height=None, perimeters=2,
                 density=20, pattern="grid", top=4, bottom=4, adhesion="skirt", brim_width=5.0):
    pipe = SlicePipeline.default(wf.FDM)
    pset = {
        "fdm_slice": {"layer_height": layer_height,
                      "first_layer_height": first_layer_height or layer_height},
        "fdm_skirt_brim": {"type": adhesion, "brim_width": brim_width},
        "fdm_perimeters": {"perimeters": perimeters},
        "fdm_top_bottom": {"top_layers": top, "bottom_layers": bottom},
        "fdm_infill": {"density": density, "pattern": pattern},
    }
    for step in pipe.steps:
        step.params.update(pset.get(step.stage, {}))
    return ProcessPreset(name, wf.FDM, pipeline=pipe.to_dict())


def builtin_processes() -> list:
    return [
        _fdm_process("0.20 mm Standard", layer_height=0.2, perimeters=2, density=20, pattern="grid"),
        _fdm_process("0.30 mm Draft", layer_height=0.3, first_layer_height=0.3,
                     perimeters=2, density=15, pattern="grid"),
        _fdm_process("0.12 mm Fine", layer_height=0.12, perimeters=3, density=20,
                     pattern="triangles", top=6, bottom=5),
        _fdm_process("Strong (cubic 40%)", layer_height=0.2, perimeters=4, density=40,
                     pattern="cubic", top=5, bottom=5, adhesion="brim", brim_width=6.0),
        ProcessPreset("Profile cut", wf.CAM),
    ]


def seed(libset: LibrarySet, save: bool = True) -> int:
    """Populate every empty library with the starter profiles / processes."""
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
    if len(libset.processes) == 0:
        for pr in builtin_processes():
            libset.processes.add(pr)
            added += 1
    if save and added:
        libset.save()
    return added
