"""FDM stage: slice the mesh into per-layer contours (the *Layers* settings)."""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMSLICE_PARAMS
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMSlice(SliceStage):
    id = "fdm_slice"
    name = "Layers"
    description = "Layer height; slices the placed model into layer contours."
    workflows = (FDM,)
    optional = False
    category = "Layers"
    params = FDMSLICE_PARAMS

    def run(self, job, params, ctx):
        mesh = job.mesh
        if mesh is None:
            raise ValueError("no mesh loaded for this job")

        # an explicit job override (CLI --layer-height) wins over the process value
        lh = float(job.settings.get("layer_height") or params["layer_height"])
        flh = params["first_layer_height"]
        flh = lh if flh == AUTO else float(flh)
        job.settings["layer_height"] = lh
        job.settings["first_layer_height"] = flh

        # every layer from the bed up - empty layers under a model lifted off the bed
        # are kept so support can be built underneath it
        from gcodeproducer.core.fdm.support import slice_layers
        overlaps = []
        merge = params.get("merge_shells", False)
        layers = slice_layers(mesh, lh, flh, merge_shells=merge, overlap_layers=overlaps)
        if overlaps:
            first, last = (layers[i] for i in (overlaps[0], overlaps[-1]))
            msg = (f"Overlapping closed solid shells on {len(overlaps)} sliced layers "
                   f"(first at Z{first.z:g} mm, last at Z{last.z:g} mm).")
            if merge:
                ctx.log(f"  {msg} Merged the overlap for slicing; source STL unchanged.")
            else:
                warning = (f"{msg} The overlap may slice as a hole. To merge the solids, turn on "
                           "Layers → Mesh repair → Merge overlapping shells and slice again. "
                           "Inspect the affected layers in Preview.")
                job.warnings.append(warning)
                ctx.log(f"FDM MESH WARNING: {warning}")
        ctx.progress(1.0)
        job.layers = layers
        empty = sum(1 for layer in layers if not layer.outline)
        lift = float(mesh.bounds[0][2])
        extra = f", model starts at Z{lift:.2f} ({empty} empty layers below)" if lift > flh * 0.5 else ""
        return f"{len(layers)} layers at {lh} mm (first {flh} mm){extra}"
