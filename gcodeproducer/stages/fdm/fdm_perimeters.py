"""FDM stage 2: generate perimeter (wall) loops from the layer contours."""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMPERIMETERS_PARAMS
from gcodeproducer.core.fdm.layer_threads import layer_map
from gcodeproducer.core.fdm.variable_walls import variable_wall_levels
from gcodeproducer.core.fdm.wall_regions import slice_region, wall_levels
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

        variable = params["variable_width"]
        min_width = lw * params["min_bead_width"] / 100.0
        max_width = lw * max(100.0, params["max_bead_width"]) / 100.0
        job.settings["min_bead_width"] = min_width
        job.settings["max_bead_width"] = max_width

        def walls(contours):
            if variable:
                return variable_wall_levels(slice_region(contours), lw, count, min_width, max_width)
            levels, inner = wall_levels(contours, lw, count)
            return [[(loop, None, True) for loop in level] for level in levels], inner

        total = varied = 0
        n = max(1, len(job.layers))
        results = layer_map(walls, [layer.contours for layer in job.layers])
        for i, (layer, (levels, inner)) in enumerate(zip(job.layers, results)):
            layer.contours = inner
            for k in reversed(range(len(levels))):
                feature = "outer_perimeter" if k == 0 else "inner_perimeter"
                for points, widths, closed in levels[k]:
                    layer.paths.append(Path(feature, points, closed=closed, width=lw, widths=widths))
                    total += 1
                    varied += widths is not None
            ctx.progress((i + 1) / n)
        extra = f", {varied} variable-width" if variable else ""
        return f"{total} wall paths ({count} perimeters, {lw} mm{extra})"
