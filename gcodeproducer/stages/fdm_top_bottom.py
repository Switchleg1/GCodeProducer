"""FDM stage: top / bottom solid infill (surface shells).

A cell is *sparse* only if the region is covered by the part in every one of
the ``top_layers`` layers above **and** every one of the ``bottom_layers``
layers below; otherwise it is a solid surface and gets 100 % fill.  Detection
uses shared-grid :class:`RegionMask` rasters, so it works on real geometry, not
just the first/last N layers.
"""
from __future__ import annotations

import numpy as np

from ..core import geometry, infill_gen
from ..core.job import Path
from .base import AUTO, FDM, Param, SliceStage


class FDMTopBottom(SliceStage):
    id = "fdm_top_bottom"
    name = "Top / bottom shells"
    description = "Fill the top and bottom surfaces with solid infill; detect them per layer."
    workflows = (FDM,)
    category = "Infill"
    params = [
        Param("top_layers", "int", 4, min=0, max=50, group="Shells",
              help="Number of solid top layers (0 = off)."),
        Param("bottom_layers", "int", 4, min=0, max=50, group="Shells",
              help="Number of solid bottom layers (0 = off)."),
        Param("pattern", "choice", "rectilinear", group="Solid fill",
              choices=[("rectilinear", "Rectilinear (alternating 90\u00b0)"),
                       ("lines", "Lines (same direction)"),
                       ("grid", "Grid")]),
        Param("angle", "float", 45.0, unit="\u00b0", min=-180, max=180, decimals=1, group="Solid fill"),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Solid fill", help="auto = wall line width."),
        Param("overlap", "float", 25.0, unit="%", min=-100, max=100, decimals=1, group="Solid fill",
              help="Overlap with the innermost wall (% of line width)."),
        Param("min_length", "float", 0.4, unit="mm", min=0, decimals=2, group="Solid fill"),
    ]

    def run(self, job, params, ctx):
        top_n = params["top_layers"]
        bot_n = params["bottom_layers"]
        if top_n <= 0 and bot_n <= 0:
            return "top/bottom shells off"
        if job.mesh is None or not job.layers:
            return "no layers"

        lw = params["line_width"]
        lw = job.settings.get("perimeter_line_width", job.line_width) if lw in (0, AUTO) else float(lw)
        res = max(0.25, lw * 0.75)
        lo, hi = job.mesh.bounds
        lo2, hi2 = lo[:2], hi[:2]

        # rasterise every layer's innermost (infill) region on a shared grid
        masks = []
        base = geometry.RegionMask(lo2, hi2, res)
        for layer in job.layers:
            rm = base.like()
            rm.fill([np.asarray(c, float) for c in layer.contours if len(c) >= 3])
            masks.append(rm.grid)
        nL = len(masks)
        empty = np.zeros_like(masks[0])

        def stack_and(idxs):
            acc = None
            for idx in idxs:
                g = masks[idx] if 0 <= idx < nL else empty
                acc = g.copy() if acc is None else (acc & g)
            return acc if acc is not None else np.ones_like(empty)

        inset = lw * 0.5 * (1.0 - params["overlap"] / 100.0)
        total = 0
        for i, layer in enumerate(job.layers):
            g = masks[i]
            above = stack_and(range(i + 1, i + 1 + top_n)) if top_n > 0 else np.ones_like(g)
            below = stack_and(range(i - bot_n, i)) if bot_n > 0 else np.ones_like(g)
            top_solid = g & ~above
            bottom_solid = g & ~below & above       # avoid double-classifying
            solid = top_solid | bottom_solid
            layer.solid_mask = base.like(solid)
            if not solid.any():
                ctx.progress((i + 1) / nL)
                continue
            total += self._fill(layer, top_solid, "top_infill", params, lw, inset, res, base)
            total += self._fill(layer, bottom_solid, "solid_infill", params, lw, inset, res, base)
            ctx.progress((i + 1) / nL)
        return f"{total} solid surface lines (top {top_n}, bottom {bot_n})"

    def _fill(self, layer, cell_grid, feature, params, lw, inset, res, base):
        if not cell_grid.any():
            return 0
        regions = [np.asarray(c, float) for c in layer.contours if len(c) >= 3]
        if not regions:
            return 0
        # keep solid lines only where this surface mask is set: block the rest
        block = base.like(~cell_grid)
        spacing = lw           # 100 % solid
        count = 0
        for phi, period, off in infill_gen.pattern_families(params["pattern"], layer.index, layer.z,
                                                            spacing, params["angle"]):
            segs = infill_gen.scan_fill(regions, phi, period, off, inset, params["min_length"])
            if not len(segs):
                continue
            segs = infill_gen.split_by_raster(segs, block, params["min_length"])
            if not len(segs):
                continue
            segs = infill_gen.order_segments(segs, start=(layer_x(layer), 0.0))
            for p0, p1 in segs:
                layer.paths.append(Path(feature, np.array([p0, p1]), closed=False, width=lw))
                count += 1
        return count


def layer_x(layer):
    return 0.0
