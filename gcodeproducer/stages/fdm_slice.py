"""FDM stage: slice the mesh into per-layer contours (the *Layers* settings)."""
from __future__ import annotations

from .base import AUTO, FDM, Param, SliceStage


class FDMSlice(SliceStage):
    id = "fdm_slice"
    name = "Layers"
    description = "Layer height; slices the placed model into layer contours."
    workflows = (FDM,)
    optional = False
    category = "Layers"
    params = [
        Param("layer_height", "float", 0.2, unit="mm", min=0.01, max=2.0, step=0.02,
              group="Layer height", help="Height of every layer after the first."),
        Param("first_layer_height", "float", AUTO, unit="mm", min=0.01, max=2.0, step=0.02,
              allow_auto=True, hint=0.25, group="Layer height",
              help="auto = same as the layer height."),
    ]

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
        from ..core.support import slice_layers
        layers = slice_layers(mesh, lh, flh)
        ctx.progress(1.0)
        job.layers = layers
        empty = sum(1 for layer in layers if not layer.outline)
        lift = float(mesh.bounds[0][2])
        extra = f", model starts at Z{lift:.2f} ({empty} empty layers below)" if lift > flh * 0.5 else ""
        return f"{len(layers)} layers at {lh} mm (first {flh} mm){extra}"
