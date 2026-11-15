"""CAM stage: 2.5D profile (contour) toolpath around the part silhouette.

Early/minimal: cuts the outline of the part, offset outward by the tool radius
(plus optional stock-to-leave), stepping down by the tool's max depth of cut.
"""
from __future__ import annotations

from ..core import geometry
from ..core.job import Layer, Path
from .base import AUTO, CAM, Param, SliceStage


class CAMProfile(SliceStage):
    id = "cam_profile"
    name = "Profile"
    description = "Cut around the part outline, offset by the tool radius, in depth steps."
    workflows = (CAM,)
    optional = False
    category = "Milling"
    params = [
        Param("side", "choice", "outside", group="Contour",
              choices=[("outside", "Outside the part"), ("inside", "Inside (pocket wall)"),
                       ("on", "On the line")]),
        Param("stock_to_leave", "float", 0.0, unit="mm", min=0, decimals=2, group="Contour"),
        Param("stepdown", "float", AUTO, unit="mm", min=0.01, decimals=2, allow_auto=True, hint=1.0,
              group="Depth", help="auto = tool max depth per pass."),
        Param("final_depth", "float", AUTO, unit="mm", min=0.01, decimals=2, allow_auto=True, hint=5.0,
              group="Depth", help="Depth below the top of the part; auto = through the whole part."),
    ]

    def run(self, job, params, ctx):
        mesh = job.mesh
        if mesh is None:
            raise ValueError("no mesh loaded")
        if not job.tools:
            raise ValueError("no tool selected (CAM jobs need a tool from the tool library)")
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
        off = {"outside": +1, "inside": -1, "on": 0}[params["side"]]
        d = off * (radius + params["stock_to_leave"])
        paths2d = []
        for c in contours:
            loops = geometry.offset(c, d) if d != 0 else [c]
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
        for di, depth in enumerate(depths):
            layer = Layer(index=di, z=depth, height=step)
            for poly in paths2d:
                layer.paths.append(Path("cut", poly, closed=True, width=tool.get("diameter", 6.0)))
            layers.append(layer)
        job.layers = layers
        job.settings["final_depth"] = final
        job.settings["stepdown"] = step
        return f"{len(paths2d)} profile loop(s), {len(depths)} depth passes to Z{final:.2f}"
