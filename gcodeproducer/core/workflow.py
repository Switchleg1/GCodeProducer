"""Workflow types.

GCodeProducer turns geometry into G-code through a *workflow*.  Each workflow
has its own importer(s), slice pipeline stages and library kinds:

* ``FDM`` - fused deposition 3D printing.
    machine -> material library + nozzle library
    (extruder, E axis, retraction, perimeters, infill, temperature, cooling...)
* ``CAM`` - subtractive machining (mills, routers).
    machine -> tool library
    (spindle, cutting depths, stepover, feeds & speeds...)

A slice stage declares which workflows it belongs to, and a pipeline for a
given workflow only ever runs stages that target it, so FDM operations such as
retraction or infill can never leak into a machining job (and vice versa).
"""
from __future__ import annotations

FDM = "fdm"
CAM = "cam"
ALL = (FDM, CAM)

LABELS = {FDM: "FDM (3D printing)", CAM: "CAM (machining)"}
SHORT = {FDM: "FDM", CAM: "CAM"}

#: library kinds each workflow uses (machine always; then its consumables)
LIBRARIES = {
    FDM: ("machine", "material", "nozzle"),
    CAM: ("machine", "tool"),
}

_ALIASES = {
    "fdm": FDM, "fff": FDM, "fff/fdm": FDM, "printer": FDM, "3dp": FDM, "print": FDM,
    "cam": CAM, "cnc": CAM, "mill": CAM, "milling": CAM, "router": CAM, "machining": CAM,
}


class IncompatibleWorkflowError(RuntimeError):
    """Raised when a stage is executed in a workflow it does not support."""


# Backwards-compatible alias (viewer / toolpath import this name)
IncompatibleMachineError = IncompatibleWorkflowError


def normalize(value: str) -> str:
    try:
        return _ALIASES[str(value).strip().lower()]
    except KeyError:
        raise ValueError(f"unknown workflow '{value}' (use 'fdm' or 'cam')") from None


def normalize_all(values) -> tuple:
    if isinstance(values, str):
        values = (values,)
    out = []
    for v in values or ():
        m = normalize(v)
        if m not in out:
            out.append(m)
    return tuple(out)


def short(workflow: str) -> str:
    return SHORT.get(workflow, str(workflow).upper())


def label(workflow: str) -> str:
    return LABELS.get(workflow, str(workflow))


def tag(workflows) -> str:
    """'FDM', 'CAM' or 'FDM+CAM'."""
    return "+".join(short(m) for m in ALL if m in workflows) or "-"
