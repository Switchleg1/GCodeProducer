"""FDM stage: automatic support.

Overhangs are found per layer on a shared raster: cells of layer *i* that are
further than ``layer_height * tan(overhang_angle)`` from layer *i-1* need
support.  Support columns are grown downward from those overhangs (leaving a
Z gap under the part), kept ``xy_distance`` away from the model, and either

* **touching build plate** - a column stops (and is dropped) as soon as the
  model is below it, so support only ever stands on the bed; or
* **everywhere** - a column may rest on top of the model (one-layer gap).

The top ``interface_layers`` of each column are printed denser
(``support_interface``) to give the overhang a flat surface.
"""
from __future__ import annotations

import math

import numpy as np

from ..core import geometry, infill_gen
from ..core.job import Path
from .base import AUTO, FDM, Param, SliceStage


class FDMSupport(SliceStage):
    id = "fdm_support"
    name = "Support"
    description = "Automatic support under overhangs (touching the build plate or everywhere)."
    workflows = (FDM,)
    category = "Support"
    params = [
        Param("placement", "choice", "buildplate", label="Support placement", group="Support",
              choices=[("buildplate", "Touching build plate"), ("everywhere", "Everywhere")]),
        Param("overhang_angle", "float", 50.0, unit="\u00b0", min=0, max=89, decimals=1, group="Support",
              help="Overhangs steeper than this (measured from vertical) get support."),
        Param("density", "float", 15.0, unit="%", min=1, max=100, decimals=1, group="Pattern"),
        Param("pattern", "choice", "lines", group="Pattern",
              choices=[("lines", "Lines"), ("grid", "Grid")]),
        Param("xy_distance", "float", 0.8, unit="mm", min=0, decimals=2, group="Distances",
              help="Horizontal gap between support and the model."),
        Param("z_gap_layers", "int", 1, label="Top Z gap (layers)", min=0, max=10, group="Distances",
              help="Empty layers between the top of the support and the overhang."),
        Param("interface_layers", "int", 2, min=0, max=20, group="Interface",
              help="Dense layers at the top of the support (0 = off)."),
        Param("interface_density", "float", 70.0, unit="%", min=5, max=100, decimals=1, group="Interface"),
        Param("min_area", "float", 1.0, unit="mm\u00b2", min=0, decimals=2, group="Distances",
              help="Ignore overhang specks smaller than this."),
        Param("line_width", "float", AUTO, unit="mm", min=0.05, max=3, allow_auto=True, hint=0.45,
              group="Pattern", help="auto = nozzle line width."),
    ]

    def run(self, job, params, ctx):
        layers = job.layers
        if job.mesh is None or len(layers) < 2:
            return "nothing to support"
        lw = params["line_width"]
        lw = job.line_width if lw in (0, AUTO) else float(lw)
        res = max(0.2, min(0.5, lw * 0.75))
        lo, hi = job.mesh.bounds
        base = geometry.RegionMask(lo[:2], hi[:2], res)
        n = len(layers)

        masks = []
        for layer in layers:
            rm = base.like()
            rm.fill([np.asarray(c, float) for c in (layer.outline or layer.contours) if len(c) >= 3])
            masks.append(rm.grid)
        ctx.progress(0.2)

        # ---- overhangs
        tan_a = math.tan(math.radians(params["overhang_angle"]))
        min_cells = params["min_area"] / (res * res)
        over = [np.zeros_like(masks[0])]
        for i in range(1, n):
            reach = max(1, int(round(layers[i].height * tan_a / res)))
            o = masks[i] & ~geometry.dilate(masks[i - 1], reach)
            o = geometry.dilate(geometry.erode(o, 1), 1)          # drop raster noise
            if o.sum() < min_cells:
                o[:] = False
            over.append(o)
        ctx.progress(0.4)

        # ---- grow columns downward from the overhangs
        xy = max(1, int(math.ceil(params["xy_distance"] / res)))
        gap = params["z_gap_layers"]
        everywhere = params["placement"] == "everywhere"
        # below_any[i]: cells with model on any layer under layer i
        below_any = [np.zeros_like(masks[0])]
        for i in range(1, n):
            below_any.append(below_any[-1] | masks[i - 1])
        acc = np.zeros_like(masks[0])
        sup = [None] * n
        for i in range(n - 1, -1, -1):
            j = i + 1 + gap
            if j < n:
                acc |= over[j]
            acc &= ~masks[i]                     # a column stops where it meets the model
            s = acc & ~geometry.dilate(masks[i], xy)
            if not everywhere:
                s &= ~below_any[i]               # build plate only: nothing of the model underneath
            if everywhere and i > 0:
                s &= ~masks[i - 1]               # one layer gap on top of the model
            sup[i] = s
        ctx.progress(0.6)

        # ---- toolpaths
        ni = params["interface_layers"]
        body_spacing = lw / (params["density"] / 100.0)
        roof_spacing = lw / (params["interface_density"] / 100.0)
        n_body = n_roof = 0
        used = 0
        for i, layer in enumerate(layers):
            s = sup[i]
            if not s.any():
                continue
            used += 1
            above = np.ones_like(s)
            for k in range(1, ni + 1):
                above &= sup[i + k] if i + k < n else np.zeros_like(s)
            roof = s & ~above if ni > 0 else np.zeros_like(s)
            body = s & ~roof
            segs_body = []
            if body.any():
                m = base.like(body)
                segs_body.append(geometry.raster_lines(m, body_spacing, True, 0.0, lw, lw * 0.25))
                if params["pattern"] == "grid":
                    segs_body.append(geometry.raster_lines(m, body_spacing, False, 0.0, lw, lw * 0.25))
            segs_roof = []
            if roof.any():
                segs_roof.append(geometry.raster_lines(base.like(roof), roof_spacing, i % 2 == 1,
                                                       0.0, lw, lw * 0.25))
            new = []
            for segs, feat in ((segs_body, "support"), (segs_roof, "support_interface")):
                segs = [x for x in segs if len(x)]
                if not segs:
                    continue
                arr = infill_gen.order_segments(np.concatenate(segs))
                for p0, p1 in arr:
                    new.append(Path(feat, np.array([p0, p1]), closed=False, width=lw))
                if feat == "support":
                    n_body += len(arr)
                else:
                    n_roof += len(arr)
            # print support right after any skirt / brim on the layer
            at = 0
            while at < len(layer.paths) and layer.paths[at].feature == "skirt":
                at += 1
            layer.paths[at:at] = new
            ctx.progress(0.6 + 0.4 * (i + 1) / n)
        if not used:
            if any(o.any() for o in over):
                return "overhangs found, but none can be supported from the build plate (try 'everywhere')"
            return "no overhangs need support"
        return (f"support on {used} layers: {n_body} lines + {n_roof} interface lines "
                f"({'everywhere' if everywhere else 'touching build plate'})")
