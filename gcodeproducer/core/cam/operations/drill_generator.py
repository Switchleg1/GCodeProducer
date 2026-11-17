"""DrillGenerator — drill points from fitted circular hole rims."""
from __future__ import annotations
import numpy as np
from .operation_generator import OperationGenerator


class DrillGenerator(OperationGenerator):
    kinds = ("drill",)
    needs_closed = True

    def paths(self, run, selection, planning):
        from gcodeproducer.core.jobs.path import Path
        op, diameter = run.op, run.diameter
        paths = []
        for p in selection.loops:
            # A circular rim, not an arbitrary face centroid, defines a drill position.
            if len(p) < 8:
                raise ValueError(f"{op.name}: select circular hole rims (at least 8 segments)")
            A = np.column_stack((2 * p, np.ones(len(p))))
            x, y, c = np.linalg.lstsq(A, (p * p).sum(axis=1), rcond=None)[0]
            radii = np.linalg.norm(p - [x, y], axis=1)
            if np.ptp(radii) > max(0.01, radii.mean() * 0.01):
                raise ValueError(f"{op.name}: selected rim is not circular")
            if diameter > 2 * radii.mean() + 0.02:
                raise ValueError(f"{op.name}: drill is larger than the selected hole")
            paths.append(Path("drill", np.array([[x, y]]), width=diameter))
        return paths, None
