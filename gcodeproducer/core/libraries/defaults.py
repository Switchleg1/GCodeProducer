"""Built-in starter profiles, used to seed an empty library."""
from __future__ import annotations
from copy import deepcopy
from .libraries_constants import BUILTIN_PROFILE_SPECS, BUILTIN_FDM_PROCESSES, BUILTIN_CAM_PROCESSES
import gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.libraries.process_preset import ProcessPreset
from gcodeproducer.core.libraries.library_set import LibrarySet
from gcodeproducer.core.libraries.profile import Profile


def builtin_profiles() -> list:
    return [Profile(**deepcopy(spec)) for spec in BUILTIN_PROFILE_SPECS]


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
    return ([_fdm_process(**spec) for spec in BUILTIN_FDM_PROCESSES]
            + [ProcessPreset(name, wf.CAM) for name in BUILTIN_CAM_PROCESSES])


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
