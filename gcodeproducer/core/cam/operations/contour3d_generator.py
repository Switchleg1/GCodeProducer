"""Contour3dGenerator — surface-following XYZ rasters clamped to successive depth floors."""
from __future__ import annotations
import math
from .operation_generator import OperationGenerator


class Contour3dGenerator(OperationGenerator):
    kinds = ("contour3d",)
    needs_closed = True
    allows_sloped = True

    def band_paths(self, run, region, surface, floors, z, ceiling, planning, *, simplifier=None):
        """XYZ raster lines for one depth band — pure geometry on the drop surface."""
        from gcodeproducer.core.cam.surface_paths import surface_raster
        op = run.op
        return surface_raster(region, surface, run.radius, run.diameter*op.stepover/100, z, op.stock,
                              planning.ctx.log, floors, ceiling, strategy=op.strategy, simplifier=simplifier,
                              direction=run.direction, stay_down=op.stay_down_lines)

    def generate(self, run, selection, planning):
        from shapely.geometry import box
        from gcodeproducer.core.jobs.path import Path
        from gcodeproducer.core.cam.surface_simplifier import SurfaceSimplifier
        from gcodeproducer.core.settings.preferences import pref
        from .surface_common import drop_surface, prepare_surface
        op, ctx, job = run.op, planning.ctx, planning.job
        region, surface_top = prepare_surface(run, selection, planning)
        surface = drop_surface(run, region, planning)
        floors = [(box(lo[0], lo[1], hi[0], hi[1]).buffer(run.radius+op.stock+surface.resolution),
                   math.ceil(float(hi[2])*1000-1e-9)/1000) for lo, hi in planning.tabs]
        ceiling = min(run.start, surface_top)
        bands = [run.depth(i) for i in range(run.count) if run.depth(i) < surface_top-1e-6]
        produced = 0
        simplifier = SurfaceSimplifier(float(pref(job, "cam_surface_tolerance")))
        for z in bands:
            lines = self.band_paths(run, region, surface, floors, z, ceiling, planning, simplifier=simplifier)
            if not lines:
                continue
            low = min(float(p[:, 2].min()) for p in lines)
            # Clamp to successive floors: never drop straight to the final
            # surface through uncleared material above it.
            run.add_layer(planning, [Path("cut", p, width=run.diameter) for p in lines], low,
                          min(run.step, run.start-z), 0)
            produced += 1
        if not produced:
            raise ValueError(f"{op.name}: no model surface below Start Z{run.start:g} that the cutter can reach in the "
                             "selected area. Check Start/End Z and the tool diameter.")
        ctx.log(f"  {op.name}: 3D Contour, {produced} depth-limited surface passes, "
                f"maximum depth per pass {run.step:g} mm, Z{run.start:g} to Z{run.end:g}")
