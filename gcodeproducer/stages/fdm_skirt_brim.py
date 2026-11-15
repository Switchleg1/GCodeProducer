"""FDM stage: skirt and brim (bed adhesion).

* **Skirt** - loops around the convex hull of the first layer, a set distance
  away from the part, to prime the nozzle (optionally several layers tall).
* **Brim** - loops attached to the outside of the first-layer outline to hold
  the part down.  Holes are not brimmed.

Both are printed before anything else on their layer and tagged ``skirt``.
"""
from __future__ import annotations

import math

import numpy as np

from ..core import geometry
from ..core.job import Path
from .base import AUTO, FDM, Param, SliceStage


class FDMSkirtBrim(SliceStage):
    id = "fdm_skirt_brim"
    name = "Skirt / brim"
    description = "Bed adhesion: a skirt around the part and / or a brim attached to it."
    workflows = (FDM,)
    category = "Adhesion"
    params = [
        Param("type", "choice", "skirt", group="Adhesion",
              choices=[("none", "None"), ("skirt", "Skirt"), ("brim", "Brim"), ("both", "Skirt + brim")]),
        Param("skirt_loops", "int", 1, min=1, max=20, group="Skirt"),
        Param("skirt_distance", "float", 3.0, unit="mm", min=0, decimals=2, group="Skirt",
              help="Gap between the part (or brim) and the skirt."),
        Param("skirt_height", "int", 1, label="Skirt layers", min=1, max=1000, group="Skirt",
              help="Number of layers the skirt is printed on (tall skirt = draft shield)."),
        Param("brim_width", "float", 5.0, unit="mm", min=0, decimals=2, group="Brim"),
        Param("brim_gap", "float", 0.0, unit="mm", min=0, decimals=2, group="Brim",
              help="Gap between the part and the brim (makes it easier to remove)."),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Lines", help="auto = nozzle line width."),
    ]

    def run(self, job, params, ctx):
        kind = params["type"]
        if kind == "none" or not job.layers:
            return "no skirt / brim"
        lw = params["line_width"]
        lw = job.line_width if lw in (0, AUTO) else float(lw)
        first = job.layers[0]
        outline = first.outline or first.contours
        outers = geometry.outer_contours([np.asarray(c, float) for c in outline if len(c) >= 3])
        if not outers:
            return "first layer is empty"

        msgs = []
        brim_extent = 0.0
        if kind in ("brim", "both") and params["brim_width"] > 0:
            n = max(1, int(math.ceil(params["brim_width"] / lw)))
            gap = params["brim_gap"]
            loops = []
            for c in outers:
                rings = []
                for k in range(n):
                    got = geometry.offset(c, gap + lw * (0.5 + k))
                    if got:
                        rings.append(got[0])
                loops.extend(reversed(rings))          # outermost first, finish next to the part
            first.paths[0:0] = [Path("skirt", r, closed=True, width=lw) for r in loops]
            brim_extent = gap + n * lw
            msgs.append(f"brim {n} loops")

        if kind in ("skirt", "both"):
            hull = geometry.convex_hull(np.concatenate(outers))
            if len(hull) >= 3:
                base = brim_extent + params["skirt_distance"]
                rings = []
                for k in range(params["skirt_loops"]):
                    got = geometry.offset(hull, base + lw * (0.5 + k))
                    if got:
                        rings.append(got[0])
                rings = list(reversed(rings))         # outermost first
                for layer in job.layers[:params["skirt_height"]]:
                    layer.paths[0:0] = [Path("skirt", r.copy(), closed=True, width=lw) for r in rings]
                msgs.append(f"skirt {len(rings)} loops x {min(params['skirt_height'], len(job.layers))} layers")
        return ", ".join(msgs) or "nothing generated"
