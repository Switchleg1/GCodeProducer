"""FDM stage 3: fill the inside of each layer with an infill pattern."""
from __future__ import annotations

import numpy as np

from ..core import infill_gen
from ..core.job import Path
from .base import FDM, Param, SliceStage


class FDMInfill(SliceStage):
    id = "fdm_infill"
    name = "Infill"
    description = "Fill the region inside the innermost perimeter with a pattern."
    workflows = (FDM,)
    category = "Infill"
    params = [
        Param("density", "float", 20.0, unit="%", min=0, max=100),
        Param("pattern", "choice", "grid",
              choices=[p for p in infill_gen.PATTERNS]),
        Param("angle", "float", 45.0, unit="\u00b0"),
        Param("line_width", "float", 0.0, unit="mm", allow_auto=True),
        Param("min_length", "float", 0.5, unit="mm"),
    ]

    def run(self, job, params, ctx):
        density = params["density"] / 100.0
        if density <= 0:
            return "infill off"
        lw = params["line_width"]
        lw = job.settings.get("perimeter_line_width", job.line_width) if lw in (0, "auto") else float(lw)
        spacing = lw / max(density, 1e-3)
        pattern = params["pattern"]
        angle = params["angle"]
        inset = lw * 0.5

        total = 0
        n = max(1, len(job.layers))
        for i, layer in enumerate(job.layers):
            regions = [np.asarray(c, float) for c in layer.contours if len(c) >= 3]
            if not regions:
                ctx.progress((i + 1) / n)
                continue
            segs_all = []
            for phi, period, off in infill_gen.pattern_families(pattern, layer.index, layer.z,
                                                                spacing, angle):
                s = infill_gen.scan_fill(regions, phi, period, off, inset, params["min_length"])
                if len(s):
                    segs_all.append(s)
            if not segs_all:
                ctx.progress((i + 1) / n)
                continue
            segs = np.concatenate(segs_all)
            segs = infill_gen.order_segments(segs, start=(0.0, 0.0))
            for p0, p1 in segs:
                layer.paths.append(Path("infill", np.array([p0, p1]), closed=False, width=lw))
                total += 1
            ctx.progress((i + 1) / n)
        return f"{total} infill lines ({params['density']:.0f}% {pattern})"
