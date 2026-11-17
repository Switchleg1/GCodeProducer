"""Operation generators: one module per operation kind, called by the CAM planner."""
from __future__ import annotations
import importlib
from .operations_constants import GENERATORS


def generator_for(kind):
    """The generator instance responsible for an Operation.kind."""
    if kind not in GENERATORS:
        raise ValueError(f"Unknown CAM operation kind '{kind}'")
    module, name = GENERATORS[kind]
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)()
