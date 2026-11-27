"""FDM stage: skirt and brim (bed adhesion).

* **Skirt** - loops around the convex hull of the first layer, a set distance
  away from the part, to prime the nozzle (optionally several layers tall).
* **Brim** - loops attached to the outside of the first-layer outline to hold
  the part down.  Holes are not brimmed.

Both are printed before anything else on their layer and tagged ``skirt``.
"""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMSKIRTBRIM_PARAMS
import math, numpy as np, gcodeproducer.core.geometry.kernel as geometry
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMSkirtBrim(SliceStage):
    id = "fdm_skirt_brim"
    name = "Skirt / brim"
    description = "Bed adhesion: a skirt around the part and / or a brim attached to it."
    workflows = (FDM,)
    category = "Adhesion"
    optional = False          # always runs; Type = None turns it off
    params = FDMSKIRTBRIM_PARAMS

    def run(self, job, params, ctx):
        kind = params["type"]
        if kind == "none" or not job.layers:
            return "no skirt / brim"
        lw = params["line_width"]
        lw = job.line_width if lw in (0, AUTO) else float(lw)
        first = job.layers[0]
        outline = first.outline or first.contours
        on_bed = bool(outline)
        if not on_bed:          # model lifted off the bed: skirt around its lowest layer
            outline = next((layer.outline for layer in job.layers if layer.outline), [])
        outers = geometry.outer_contours([np.asarray(c, float) for c in outline if len(c) >= 3])
        if not outers:
            return "model is empty"

        msgs = []
        brim_extent = 0.0
        if kind in ("brim", "both") and params["brim_width"] > 0 and not on_bed:
            msgs.append("no brim (the model does not touch the bed)")
        elif kind in ("brim", "both") and params["brim_width"] > 0:
            n = max(1, int(math.ceil(params["brim_width"] / lw)))
            gap = params["brim_gap"]
            # The brim goes round the first layer as a whole: parts (or teeth) closer together than
            # the brim is wide share its loops instead of each getting rings that cross the others.
            # Each loop is the true offset of that union, so the innermost touches the outer wall.
            from shapely import BufferJoinStyle
            from shapely.geometry import Polygon
            from shapely.geometry.polygon import orient
            from shapely.ops import unary_union
            part = unary_union([Polygon(c).buffer(0) for c in outers])
            loops = []
            for k in reversed(range(n)):                 # outermost first, finish next to the part
                grown = part.buffer(gap + lw * (0.5 + k), join_style=BufferJoinStyle.round, quad_segs=8)
                for g in sorted(getattr(grown, "geoms", [grown]), key=lambda g: -g.area):
                    if g.geom_type != "Polygon" or g.is_empty:
                        continue
                    g = orient(g, 1.)
                    # Rings inside the grown outline lie between parts: brim there too.
                    for ring in (g.exterior, *g.interiors):
                        loop = np.asarray(ring.coords, float)[:-1]
                        if len(loop) >= 3:
                            loops.append(loop)
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
