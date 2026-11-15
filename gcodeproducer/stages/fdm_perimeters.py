"""FDM stage 2: generate perimeter (wall) loops from the layer contours."""
from __future__ import annotations

from ..core import geometry
from ..core.job import Path
from .base import AUTO, FDM, Param, SliceStage


class FDMPerimeters(SliceStage):
    id = "fdm_perimeters"
    name = "Walls"
    description = "Outer and inner wall loops, offset inward from each layer contour."
    workflows = (FDM,)
    optional = False
    category = "Walls"
    params = [
        Param("perimeters", "int", 2, label="Wall loops", min=1, max=20, group="Walls",
              help="Number of perimeter loops."),
        Param("line_width", "float", AUTO, label="Wall line width", unit="mm", min=0.05, max=3,
              allow_auto=True, hint=0.45, group="Walls", help="auto = nozzle line width."),
    ]

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
