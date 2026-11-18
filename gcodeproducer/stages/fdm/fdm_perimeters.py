"""FDM stage 2: generate perimeter (wall) loops from the layer contours."""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMPERIMETERS_PARAMS
from gcodeproducer.core.fdm.wall_regions import wall_levels
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMPerimeters(SliceStage):
    id = "fdm_perimeters"
    name = "Walls"
    description = "Outer and inner wall loops, offset inward from each layer contour."
    workflows = (FDM,)
    optional = False
    category = "Walls"
    params = FDMPERIMETERS_PARAMS

    def run(self, job, params, ctx):
        lw = params["line_width"]
        lw = job.line_width if lw in (0, AUTO) else float(lw)
        count = params["perimeters"]
        job.settings["perimeter_line_width"] = lw
        job.settings["perimeters"] = count

        total = 0
        n = max(1, len(job.layers))
        for i, layer in enumerate(job.layers):
            levels, layer.contours = wall_levels(layer.contours, lw, count)
            for k in reversed(range(len(levels))):
                feature = "outer_perimeter" if k == 0 else "inner_perimeter"
                for loop in levels[k]:
                    layer.paths.append(Path(feature, loop, closed=True, width=lw))
                    total += 1
            ctx.progress((i + 1) / n)
        return f"{total} wall loops ({count} perimeters, {lw} mm)"
