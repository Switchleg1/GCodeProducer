"""FDM stage: automatic support.

Overhangs are found per layer on a shared raster: cells of layer *i* that are
further than ``layer_height * tan(overhang_angle)`` from layer *i-1* need
support.  Support columns are grown downward from those overhangs (leaving a
Z gap under the part), kept ``xy_distance`` away from the model, and either

* **touching build plate** - only columns with no model underneath, so
  support only ever stands on the bed;
* **everywhere** - a column may rest on top of the model (one-layer gap); or
* **manual blocks** - support is generated inside the user's support blocks
  (``job.support_blocks``) wherever the model is above them.  The GUI can
  create the blocks from the automatic result and the user edits them.

The top ``interface_layers`` of each column are printed denser
(``support_interface``) to give the overhang a flat surface.
"""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMSUPPORT_PARAMS
import numpy as np, gcodeproducer.core.geometry.kernel as geometry, gcodeproducer.core.geometry.infill as infill_gen, gcodeproducer.core.fdm.support as support
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMSupport(SliceStage):
    id = "fdm_support"
    name = "Support"
    description = ("How support is printed: pattern, gaps and interfaces. Where support goes (none / "
                   "build plate / everywhere / manual blocks), the overhang angle, how far it extends past "
                   "the edges and hole filling are set per model in Model > Support.")
    workflows = (FDM,)
    optional = False          # always runs; the model's support mode decides whether there is support
    category = "Support"
    params = FDMSUPPORT_PARAMS

    def run(self, job, params, ctx):
        ms = job.support or support.ModelSupport()        # the model's support settings
        multi = len(job.plate_models) > 1
        sources = [model.support for model in job.plate_models if model.support.enabled] if multi else [ms] if ms.enabled else []
        if not sources:
            return "no support (Model > Support: None)"
        layers = job.layers
        if job.mesh is None or len(layers) < 2:
            return "nothing to support"
        lw = params["line_width"]
        lw = job.line_width if lw in (0, AUTO) else float(lw)
        lo, hi = job.mesh.bounds
        margin = max(source.extend for source in sources)
        base = support.make_grid(lo, hi, lw, margin)
        n = len(layers)
        mode = ms.mode
        if multi:
            from gcodeproducer.core.fdm.plate_support import plate_columns
            sup = plate_columns(job, params, base, lw, ctx)
        else:
            masks = support.model_masks(layers, base, ms.fill_holes)
            ctx.progress(0.2)
            gap = params["z_gap_layers"]
            bgap = params["bottom_z_gap_layers"]
            if mode == "blocks":
                blocks = list(job.support_blocks or [])
                if not blocks:
                    return "manual support: no support blocks"
                sup = support.block_columns(masks, layers, base, blocks, params["xy_distance"], gap, margin, lw,
                                            bgap)
            else:
                over = support.overhangs(masks, layers, base.res, ms.overhang_angle, params["min_area"])
                ctx.progress(0.4)
                sup = support.auto_columns(masks, over, base.res, params["xy_distance"], gap,
                                           mode == "everywhere", margin, lw, bgap)
        ctx.progress(0.6)

        # ---- toolpaths
        ni = params["interface_layers"]
        nb = params["bottom_interface_layers"]
        body_spacing = lw / (params["density"] / 100.0)
        roof_spacing = lw / (params["interface_density"] / 100.0)
        n_body = n_roof = 0
        used = 0
        track_bridges = job.mat('bridge_min_area', 0.) > 0
        if track_bridges:
            from gcodeproducer.core.fdm.bridges import support_footprint
            job.settings['bridge_support_gap_layers'] = params['z_gap_layers']
        for i, layer in enumerate(layers):
            s = sup[i]
            if not s.any():
                continue
            used += 1
            above = np.ones_like(s)
            for k in range(1, ni + 1):
                above &= sup[i + k] if i + k < n else np.zeros_like(s)
            roof = s & ~above if ni > 0 else np.zeros_like(s)
            if nb > 0:
                # floor: where the column started within nb layers - on the model or on the bed
                below = np.ones_like(s)
                for k in range(1, nb + 1):
                    if i - k < 0:
                        below[:] = False     # the bed: the first nb layers are a floor too
                        break
                    below &= sup[i - k]
                roof |= s & ~below
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
            if track_bridges and new:
                layer.support_region = support_footprint(base, s)
            # print support right after any skirt / brim on the layer
            at = 0
            while at < len(layer.paths) and layer.paths[at].feature == "skirt":
                at += 1
            layer.paths[at:at] = new
            ctx.progress(0.6 + 0.4 * (i + 1) / n)
        if multi:
            return f"plate support on {used} layers: {n_body} lines + {n_roof} interface lines"
        if not used:
            if mode == "blocks":
                return "manual support: the blocks are not under the model"
            if any(o.any() for o in over):
                return "overhangs found, but none can be supported from the build plate (try 'everywhere')"
            return "no overhangs need support"
        label = {"everywhere": "everywhere", "blocks": f"{len(job.support_blocks)} manual blocks"}.get(
            mode, "touching build plate")
        return f"support on {used} layers: {n_body} lines + {n_roof} interface lines ({label})"
