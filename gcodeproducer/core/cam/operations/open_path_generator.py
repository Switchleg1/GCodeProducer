"""OpenPathGenerator — Slot and Engrave: follow the selected constant-Z chains as cut."""
from __future__ import annotations
import numpy as np
from .operation_generator import OperationGenerator


class OpenPathGenerator(OperationGenerator):
    kinds = ("slot", "engrave")

    def paths(self, run, selection, planning):
        from gcodeproducer.core.jobs.path import Path
        if any(np.ptp(p[:, 2]) > 1e-4 for p in selection.polys):
            raise ValueError(f"{run.op.name}: only constant-Z engraving is supported")
        return [Path("cut", p[:, :2], width=run.diameter) for p in selection.polys], None
