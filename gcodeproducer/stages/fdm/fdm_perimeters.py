"""FDM stage 2: generate perimeter (wall) loops from the layer contours."""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMPERIMETERS_PARAMS
import gcodeproducer.core.geometry.kernel as geometry
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
            loops_per_contour = geometry.perimeter_loops(layer.contours, lw, count)
            # innermost loops define the region infill will fill
            layer_inner = []
            for loops in loops_per_contour:
                # print inner walls first, outer wall last (better surface)
                for k, loop in enumerate(reversed(loops)):
                    wall_index = len(loops) - 1 - k   # 0 = outer
                    feat = "outer_perimeter" if wall_index == 0 else "inner_perimeter"
                    layer.paths.append(Path(feat, loop, closed=True, width=lw))
                    total += 1
                layer_inner.append(loops[-1])
            layer.contours = layer_inner        # hand innermost loops to infill
            ctx.progress((i + 1) / n)
        return f"{total} wall loops ({count} perimeters, {lw} mm)"
