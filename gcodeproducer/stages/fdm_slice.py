"""FDM stage 1: slice the mesh into per-layer contours."""
from __future__ import annotations

from ..core import geometry
from ..core.job import Layer
from .base import FDM, Param, SliceStage


class FDMSlice(SliceStage):
    id = "fdm_slice"
    name = "Slice"
    description = "Position the mesh on the bed and intersect it into layer contours."
    workflows = (FDM,)
    optional = False
    category = "Slicing"
    params = [
        Param("layer_height", "float", 0.0, unit="mm", allow_auto=True,
              help="0 / auto = half the nozzle diameter."),
        Param("first_layer_height", "float", 0.0, unit="mm", allow_auto=True,
              help="0 / auto = layer height."),
        Param("center_on_bed", "bool", True, help="Centre the part on the bed and drop it to Z0."),
    ]

    def run(self, job, params, ctx):
        mesh = job.mesh
        if mesh is None:
            raise ValueError("no mesh loaded for this job")

        lh = params["layer_height"]
        lh = job.layer_height if lh in (0, "auto") else float(lh)
        flh = params["first_layer_height"]
        flh = lh if flh in (0, "auto") else float(flh)
        job.settings["layer_height"] = lh
        job.settings["first_layer_height"] = flh

        if params["center_on_bed"]:
            if job.m("origin_center"):
                cx = cy = 0.0
            else:
                cx, cy = job.m("bed_x", 220) / 2, job.m("bed_y", 220) / 2
            mesh.center_xy_on(cx, cy)

        lo, hi = mesh.bounds
        top = float(hi[2])
        layers = []
        z = flh
        idx = 0
        while z <= top + 1e-6:
            contours = geometry.slice_z(mesh, z - lh * 0.5)   # slice mid-layer
            h = flh if idx == 0 else lh
            if contours:
                layers.append(Layer(index=idx, z=round(z, 4), height=h, contours=contours))
            idx += 1
            z += lh
            ctx.progress(min(1.0, z / max(top, 1e-6)))
        job.layers = layers
        return f"{len(layers)} layers at {lh} mm (first {flh} mm)"
