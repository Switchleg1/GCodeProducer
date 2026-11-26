"""OperationGenerator — the API every operation kind implements for the planner.

A generator owns only its kind's *geometry*: validation of the picked
selection and the cut paths. Depth sequencing, material, air removal,
engagement, entries, links and feeds belong to the planner, which calls the
generator and offers it services through :class:`PlanningContext`.
"""
from __future__ import annotations


class OperationGenerator:
    kinds = ()                 # Operation.kind values handled
    clearing = False           # face = pocket boundary; material edge = whole blank rim
    needs_closed = False       # selection must be closed loops
    allows_sloped = False      # sloped edge chains accepted (model-surface-limited kinds)

    def validate(self, run, selection):
        op = run.op
        if not selection.flat and not self.allows_sloped:
            from gcodeproducer.core.cam.cam_constants import KIND_LABELS
            raise ValueError(f"{op.name}: {KIND_LABELS[op.kind]} needs constant-Z edges; 3D Pocket "
                             "and 3D Contour accept sloped boundaries; use 3D Pocket for surface-limited clearing")
        if self.needs_closed and not selection.closed:
            raise ValueError(f"{op.name}: select closed edges or a horizontal face")

    def paths(self, run, selection, planning):
        """Base XY paths and the removal region (or None) for a planar operation."""
        raise NotImplementedError

    def generate(self, run, selection, planning):
        """Default planar operation: geometry from :meth:`paths`, shared scheduling."""
        from gcodeproducer.core.cam.planner.pass_scheduler import schedule_planar
        paths, region = self.paths(run, selection, planning)
        schedule_planar(run, paths, region, planning)
