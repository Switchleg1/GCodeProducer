"""FDM stage: top / bottom solid infill (surface shells).

A cell is *sparse* only if the region is covered by the part in every one of
the ``top_layers`` layers above **and** every one of the ``bottom_layers``
layers below; otherwise it is a solid surface and gets 100 % fill.  Detection
uses shared-grid :class:`RegionMask` rasters, so it works on real geometry, not
just the first/last N layers.
"""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMTOPBOTTOM_PARAMS
from functools import partial
from types import SimpleNamespace
import numpy as np, gcodeproducer.core.geometry.kernel as geometry
from gcodeproducer.core.jobs.path import Path
from shapely import union_all
from gcodeproducer.core.fdm.layer_tasks import top_bottom_task
from gcodeproducer.core.fdm.layer_threads import layer_map
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMTopBottom(SliceStage):
    id = "fdm_top_bottom"
    name = "Top / bottom shells"
    description = "Fill the top and bottom surfaces with solid infill; detect them per layer."
    workflows = (FDM,)
    category = "Infill"
    params = FDMTOPBOTTOM_PARAMS

    def run(self, job, params, ctx):
        top_n = params["top_layers"]
        bot_n = params["bottom_layers"]
        bridge_min = job.mat('bridge_min_area', 0.)
        material = job.material.name if job.material is not None else 'no material selected'
        if bridge_min > 0:
            ctx.log(f'  Bridging: {material}, minimum unsupported area {bridge_min:g} mm²')
        else:
            ctx.log(f'  Bridging: off for {material} (minimum unsupported area is 0 mm²)')
        if top_n <= 0 and bot_n <= 0 and not bridge_min:
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
        growth = job.mat('bridge_growth', .8) if bridge_min else 0.
        support_gap = job.settings.get('bridge_support_gap_layers', 0)
        cfg = {"width": lw, "inset": inset, "growth": growth, "bridge_min": bridge_min, "base": base,
               "pattern": params["pattern"], "angle": params["angle"], "min_length": params["min_length"]}
        # the masks need every layer; the bridges and solid lines of a layer need only these
        tasks = []
        for i, layer in enumerate(job.layers):
            g = masks[i]
            above = stack_and(range(i + 1, i + 1 + top_n)) if top_n > 0 else np.ones_like(g)
            below = stack_and(range(i - bot_n, i)) if bot_n > 0 else np.ones_like(g)
            top_solid = g & ~above
            bottom_solid = g & ~below & above       # avoid double-classifying
            layer.solid_mask = base.like(top_solid | bottom_solid)
            supported = support_material = None
            if bridge_min and i > 0 and layer.contours:
                supported = job.layers[i-1].outline
                regions = [previous.support_region for previous in job.layers[max(0, i-support_gap-1):i]
                           if previous.support_region is not None]
                support_material = union_all(regions) if regions else None
            tasks.append(SimpleNamespace(index=layer.index, z=layer.z, contours=layer.contours, supported=supported,
                                         support_material=support_material, top=top_solid, bottom=bottom_solid))
        total = bridge_count = 0
        for i, (layer, (bridges, region, top, bottom)) in enumerate(
                zip(job.layers, layer_map(partial(top_bottom_task, cfg), tasks))):
            layer.bridge_region = region
            for segment in bridges:
                layer.paths.append(Path('bridge', segment, width=lw))
            for feature, segs in (("top_infill", top), ("solid_infill", bottom)):
                for p0, p1 in segs:
                    layer.paths.append(Path(feature, np.array([p0, p1]), closed=False, width=lw))
            bridge_count += len(bridges)
            total += len(top) + len(bottom)
            ctx.progress((i + 1) / nL)
        detail = f', {bridge_count} bridge lines' if bridge_min else ''
        return f"{total} solid surface lines (top {top_n}, bottom {bot_n}){detail}"


def layer_x(layer):
    """Start X of the solid-line ordering (kept for the ``stages.fdm_top_bottom`` facade)."""
    return 0.0
