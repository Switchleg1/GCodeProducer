"""FDM stage: sparse infill inside each layer using the selected pattern.

Fills the region inside the innermost perimeter, skipping any cells already
claimed by the top / bottom solid shells (so sparse and solid never overlap).
"""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMINFILL_PARAMS
from functools import partial
from types import SimpleNamespace
import numpy as np
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.core.fdm.fdm_constants import GAP_CLIPPED_FEATURES
from gcodeproducer.core.fdm.layer_tasks import infill_task
from gcodeproducer.core.fdm.layer_threads import layer_map
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMInfill(SliceStage):
    id = "fdm_infill"
    name = "Infill"
    description = "Fill the region inside the innermost perimeter with a pattern (sparse)."
    workflows = (FDM,)
    category = "Infill"
    params = FDMINFILL_PARAMS

    def run(self, job, params, ctx):
        job.settings["optimize_mixed_infill"] = params["optimize_mixed_infill"]
        density = params["density"] / 100.0
        solid_islands = params["solid_island_area"] if params["solid_islands"] else 0.
        if density <= 0 and not params["gap_fill"] and solid_islands <= 0:
            return "infill off"
        lw = params["line_width"]
        lw = job.settings.get("perimeter_line_width", job.line_width) if lw in (0, AUTO) else float(lw)
        spacing = lw / max(density, 1e-3)
        pattern = params["pattern"]
        angle = params["angle"]
        inset = lw * 0.5 * (1.0 - params["overlap"] / 100.0)

        gap_fill = params["gap_fill"]
        wall_lw = job.settings.get("perimeter_line_width", job.line_width)
        gap_width = params["gap_fill_width"]
        gap_width = 2 * wall_lw if gap_width in (0, AUTO) else float(gap_width)
        min_width = job.settings.get("min_bead_width", lw * 0.5)
        max_width = job.settings.get("max_bead_width", lw * 1.5)
        gap_overlap = lw * 0.5 * params["overlap"] / 100.0

        cfg = {"density": density, "inset": inset, "pattern": pattern, "spacing": spacing, "angle": angle,
               "min_length": params["min_length"], "connect": params["connect"],
               "gap_width": gap_width if gap_fill else 0., "island_area": solid_islands,
               "wall_width": wall_lw, "width": lw, "min_width": min_width, "max_width": max_width,
               "gap_overlap": gap_overlap}

        total = gaps_total = island_total = 0
        n = max(1, len(job.layers))
        # workers get only what they read: outlines, masks and the solid lines to trim
        slim = [SimpleNamespace(index=l.index, z=l.z, contours=l.contours, outline=l.outline,
                                solid_mask=l.solid_mask, bridge_region=l.bridge_region,
                                paths=[p for p in l.paths if p.feature in GAP_CLIPPED_FEATURES and len(p.points) == 2])
                for l in job.layers]
        results = layer_map(partial(infill_task, cfg), slim)
        for i, (layer, result) in enumerate(zip(job.layers, results)):
            if result is not None:
                segs, solid, beads = result
                if solid is not None:
                    # solid lines come after walls and bridges, so their relative order is unchanged
                    layer.paths[:] = [p for p in layer.paths
                                      if not (p.feature in GAP_CLIPPED_FEATURES and len(p.points) == 2)] + solid
                for feature, (points, widths, closed) in beads:
                    layer.paths.append(Path(feature, points, closed=closed, width=lw, widths=widths))
                    gaps_total += feature == "gap_fill"
                    island_total += feature != "gap_fill"
                for p0, p1 in segs:
                    layer.paths.append(Path("infill", np.array([p0, p1]), closed=False, width=lw))
                    total += 1
            ctx.progress((i + 1) / n)
        gaps = f", {gaps_total} gap-fill paths" if gap_fill else ""
        if solid_islands > 0:
            gaps += f", {island_total} solid small-island loops (< {solid_islands:g} mm²)"
        if density <= 0:
            return f"infill off{gaps}"
        return f"{total} infill lines ({params['density']:.0f}% {pattern}){gaps}"
