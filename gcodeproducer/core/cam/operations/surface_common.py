"""Shared preparation of the model-surface-limited operations (Waterfall, Contour)."""
from __future__ import annotations
import math


def drop_surface(run, region, planning):
    """The model's drop-height grid over ``region`` for this run's cutter (warns when the cell limit coarsens it)."""
    from gcodeproducer.core.cam.drop_surface import DropSurface
    from gcodeproducer.core.cam.cam_constants import SURFACE_MIN_RESOLUTION, SURFACE_CELLS_PER_DIAMETER
    from gcodeproducer.core.settings.preferences import pref
    op, job = run.op, planning.job
    explicit = float(pref(job, "cam_surface_resolution"))
    wanted = (max(.01, explicit) if explicit > 0 else
              max(SURFACE_MIN_RESOLUTION, min(float(pref(job, "stock_resolution")),
                                              run.diameter/SURFACE_CELLS_PER_DIAMETER)))
    minx, miny, maxx, maxy = region.bounds
    pad = run.radius+3*wanted
    surface = DropSurface(job.mesh, (minx-pad, miny-pad), (maxx+pad, maxy+pad), wanted,
                          int(pref(job, "stock_max_cells")))
    if surface.resolution > wanted+1e-9:
        planning.warn(f"{op.name}: surface height grid coarsened to {surface.resolution:.3f} mm (cell limit); "
                      "more material is left on slopes.", "SURFACE")
    return surface


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
