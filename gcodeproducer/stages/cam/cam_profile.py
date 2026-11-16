"""CAM stage: 2.5D profile (contour) toolpath around the part silhouette.

Early/minimal: cuts the outline of the part, offset outward by the tool radius
(plus optional stock-to-leave), stepping down by the tool's max depth of cut.
"""
from __future__ import annotations

from gcodeproducer.stages.cam.cam_constants import CAMPROFILE_PARAMS
import gcodeproducer.core.geometry.kernel as geometry
from gcodeproducer.core.jobs.layer import Layer
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.stages.base.api import CAM
from gcodeproducer.stages.base.slice_stage import SliceStage


class CAMProfile(SliceStage):
    id = "cam_profile"
    name = "Profile"
    description = "Cut around the part outline, offset by the tool radius, in depth steps."
    workflows = (CAM,)
    optional = False
    category = "Milling"
    params = CAMPROFILE_PARAMS

    def run(self, job, params, ctx):
        mesh = job.mesh
        if mesh is None:
            raise ValueError("no mesh loaded")
        if not job.tools:
            raise ValueError("no tool selected (CAM jobs need a tool from the tool library)")
        if job.cam_setup is not None:
            from gcodeproducer.core.cam.planning import generate
            return generate(job, ctx)
        tool = job.tools[0]
        radius = (tool.get("diameter", 6.0) or 6.0) / 2.0

        lo, hi = mesh.bounds
        top = float(hi[2])
        bottom = float(lo[2])
        final = params["final_depth"]
        final = bottom if final in (0, "auto") else max(bottom, top - float(final))
        step = params["stepdown"]
        step = (tool.get("max_doc", 2.0) or 2.0) if step in (0, "auto") else float(step)

        # silhouette near the top
        contours = geometry.slice_z(mesh, top - 1e-3)
        if not contours:
            contours = geometry.slice_z(mesh, (top + bottom) / 2)
        # 'outside' = away from the material: outer contours grow, holes shrink
        off = {"outside": -1, "inside": +1, "on": 0}[params["side"]]
        d = off * (radius + params["stock_to_leave"])
        paths2d = []
        for c, hole in zip(contours, geometry.hole_flags(contours)):
            loops = geometry.offset_into_material(c, d, hole) if d != 0 else [c]
            paths2d.extend(loops)
        if not paths2d:
            return "nothing to profile"

        layers = []
        idx = 0
        z = top - step
        depths = []
        while z > final + 1e-6:
            depths.append(round(z, 4))
            z -= step
        depths.append(round(final, 4))
        from gcodeproducer.core.cam.paths import direction_for
        from gcodeproducer.core.cam.paths import orient_contour
        direction = direction_for(job)
        flags = geometry.hole_flags(paths2d)
        for di, depth in enumerate(depths):
            layer = Layer(index=di, z=depth, height=step)
            for pi, (poly, hole) in enumerate(zip(paths2d, flags)):
                material_inside = (not hole) if params["side"] != "inside" else hole
                poly = orient_contour(poly, direction, material_inside=material_inside, index=pi)
                layer.paths.append(Path("cut", poly, closed=True, width=tool.get("diameter", 6.0)))
            layers.append(layer)
        job.layers = layers
        job.settings["final_depth"] = final
        job.settings["stepdown"] = step
        return f"{len(paths2d)} profile loop(s), {len(depths)} depth passes to Z{final:.2f}"
