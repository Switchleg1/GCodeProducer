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

from gcodeproducer.core.workflows.incompatible_workflow_error import IncompatibleWorkflowError
from gcodeproducer.core.workflows.workflows_constants import (
    FDM,
    CAM,
    ALL,
    LABELS,
    SHORT,
    LIBRARIES,
    _ALIASES,
)


#: library kinds each workflow uses (machine always; then its consumables)


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
