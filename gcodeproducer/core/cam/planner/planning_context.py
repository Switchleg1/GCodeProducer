"""PlanningContext — services the planner offers to operation generators.

Operations ask the context for current material, the model shadow, holding
tabs, stock limits, warnings and logging instead of reaching into the job.
"""
from __future__ import annotations


class PlanningContext:
    def __init__(self, job, ctx, topo, material, tabs, skip_air):
        self.job = job
        self.ctx = ctx
        self.setup = job.cam_setup
        self.topo = topo
        self.material = material         # MaterialModel (planar history used here)
        self.tabs = tabs                 # resolved holding-tab bounds
        self.skip_air = skip_air
        self.layers = []
        self.debug_partial = False
        self._shadow = None

    @property
    def shadow(self):
        """XY shadow of all model material above a level (built once, on demand)."""
        if self._shadow is None:
            from gcodeproducer.core.cam.model_shadow import ModelShadow
            self._shadow = ModelShadow(self.job.mesh)
        return self._shadow

    def log(self, message):
        self.ctx.log(message)

    def warn(self, message, prefix):
        if message not in self.job.warnings:
            self.job.warnings.append(message)
            self.ctx.log(f"{prefix} WARNING: {message}")

    def mark_partial(self, message):
        self.debug_partial = True
        self.warn(message, 'ADAPTIVE')

    def add_warnings(self, warnings):
        for warning in warnings:
            if warning not in self.job.warnings:
                self.job.warnings.append(warning)

    def reach(self, run, surface):
        """Warn when the depth below the current material exceeds the tool's flute length."""
        reach = float(run.tool.get("length", 0) or 0)
        if reach > 0 and surface-run.end > reach+1e-3:
            self.warn(f"{run.op.name}: {surface-run.end:g} mm below the current material surface (Z{surface:g}) exceeds the "
                      f"tool cutting length {reach:g} mm; verify reach, shank and holder clearance.", "REACH")
