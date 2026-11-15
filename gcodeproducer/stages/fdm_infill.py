"""FDM stage: sparse infill inside each layer, using any GCodeTools pattern.

Fills the region inside the innermost perimeter, skipping any cells already
claimed by the top / bottom solid shells (so sparse and solid never overlap).
"""
from __future__ import annotations

import numpy as np

from ..core import infill_gen
from ..core.job import Path
from .base import AUTO, FDM, Param, SliceStage


class FDMInfill(SliceStage):
    id = "fdm_infill"
    name = "Infill"
    description = "Fill the region inside the innermost perimeter with a pattern (sparse)."
    workflows = (FDM,)
    category = "Infill"
    params = [
        Param("density", "float", 20.0, unit="%", min=0, max=100, decimals=1, group="Pattern",
              help="0 = hollow (walls and shells only)."),
        Param("pattern", "choice", "grid", choices=list(infill_gen.PATTERNS), group="Pattern"),
        Param("angle", "float", 45.0, unit="\u00b0", min=-180, max=180, decimals=1, group="Pattern"),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Lines", help="auto = wall line width."),
        Param("overlap", "float", 15.0, unit="%", min=-100, max=100, decimals=1, group="Lines",
              help="Overlap with the innermost wall (% of infill width)."),
        Param("min_length", "float", 0.5, unit="mm", min=0, decimals=2, group="Lines"),
        Param("connect", "bool", True, label="Shortest travel order", group="Lines",
              help="Order lines nearest-first to shorten travels."),
    ]

    def run(self, job, params, ctx):
        density = params["density"] / 100.0
        if density <= 0:
            return "infill off"
        lw = params["line_width"]
        lw = job.settings.get("perimeter_line_width", job.line_width) if lw in (0, AUTO) else float(lw)
        spacing = lw / max(density, 1e-3)
        pattern = params["pattern"]
        angle = params["angle"]
        inset = lw * 0.5 * (1.0 - params["overlap"] / 100.0)

        total = 0
        n = max(1, len(job.layers))
        for i, layer in enumerate(job.layers):
            regions = [np.asarray(c, float) for c in layer.contours if len(c) >= 3]
            if not regions:
                ctx.progress((i + 1) / n)
                continue
            block = layer.solid_mask            # RegionMask of solid cells, or None
            segs_all = []
            for phi, period, off in infill_gen.pattern_families(pattern, layer.index, layer.z,
                                                                spacing, angle):
                s = infill_gen.scan_fill(regions, phi, period, off, inset, params["min_length"])
                if block is not None and len(s):
                    s = infill_gen.split_by_raster(s, block, params["min_length"])
                if len(s):
                    segs_all.append(s)
            if not segs_all:
                ctx.progress((i + 1) / n)
                continue
            segs = np.concatenate(segs_all)
            if params["connect"]:
                segs = infill_gen.order_segments(segs, start=(0.0, 0.0))
            for p0, p1 in segs:
                layer.paths.append(Path("infill", np.array([p0, p1]), closed=False, width=lw))
                total += 1
            ctx.progress((i + 1) / n)
        return f"{total} infill lines ({params['density']:.0f}% {pattern})"
