"""Shared preparation of the model-surface-limited operations (Waterfall, Contour)."""
from __future__ import annotations
import math


def prepare_surface(run, selection, planning):
    """Validate, merge the selected outlines and start from the material surface.

    Returns ``(region, surface_top)``; ``run.start`` / ``run.count`` are raised to
    the material surface when the selected Start lies below uncut material.
    """
    from gcodeproducer.core.cam.surface_paths import selection_region
    op, ctx, job = run.op, planning.ctx, planning.job
    if not 0 < op.stepover <= 100:
        raise ValueError(f"{op.name}: stepover must be between 0 and 100 percent")
    if op.stock < 0 or not math.isfinite(op.stock):
        raise ValueError(f"{op.name}: stock to leave must be zero or positive")
    region = selection_region(selection.loops, ctx.log, op.name)
    setup = planning.setup
    surface_top = max(float(job.mesh.bounds[1][2]), setup.stock.top if setup.stock.allocated else -math.inf)
    if run.start < surface_top-1e-6:
        ctx.log(f"  {op.name}: clearing above selected Start Z{run.start:g} from material surface Z{surface_top:g}")
        run.start = surface_top
        run.count = max(1, math.ceil((run.start-run.end)/run.step))
        if run.count > 10000:
            raise ValueError(f"{op.name}: too many depth passes from the material surface")
    planning.reach(run, surface_top)
    return region, surface_top
