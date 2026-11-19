"""Shared removal-region geometry for Pocket and 3D Waterfall."""
from __future__ import annotations

import math

from gcodeproducer.core.cam.paths import overcut_region, part_section


def validate_overcut(op):
    if op.overcut < 0 or not math.isfinite(op.overcut):
        raise ValueError(f"{op.name}: overcut must be finite and zero or positive")


def clearing_part_section(run, planning):
    depths = [run.depth(i) for i in range(run.count)] + [run.start]
    depths.extend(math.ceil(float(hi[2])*1000-1e-9)/1000 for _, hi in planning.tabs
                  if run.end < hi[2] < run.start)
    # The path's cutter offset already leaves roughing clearance on part walls.
    return part_section(planning.job.mesh, depths)


def apply_overcut(region, op, protected, limit, ctx):
    grown = overcut_region(region, op.overcut, protected, limit)
    ctx.log(f"  {op.name}: overcut {op.overcut:g} mm into void material adds "
            f"{grown.area - region.area:.1f} mm² (part sections protected, "
            f"material limit {op.material_limit:+g} mm)")
    return grown
