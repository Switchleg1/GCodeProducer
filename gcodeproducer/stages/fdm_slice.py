"""FDM stage: slice the mesh into per-layer contours (the *Layers* settings)."""
from __future__ import annotations

from ..core import geometry
from ..core.job import Layer
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

        lo, hi = mesh.bounds
        top = float(hi[2])
        layers = []
        z = flh
        idx = 0
        while z <= top + 1e-6:
            h = flh if idx == 0 else lh
            contours = geometry.slice_z(mesh, z - h * 0.5)   # slice mid-layer
            if contours:
                layers.append(Layer(index=len(layers), z=round(z, 4), height=h,
                                    contours=list(contours), outline=list(contours)))
            idx += 1
            z += lh
            ctx.progress(min(1.0, z / max(top, 1e-6)))
        job.layers = layers
        return f"{len(layers)} layers at {lh} mm (first {flh} mm)"
