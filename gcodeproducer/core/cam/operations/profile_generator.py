"""ProfileGenerator — closed boundaries offset outside/inside by the cutter radius."""
from __future__ import annotations
from .operation_generator import OperationGenerator


class ProfileGenerator(OperationGenerator):
    kinds = ("profile",)
    needs_closed = True

    def paths(self, run, selection, planning):
        import gcodeproducer.core.geometry.kernel as geometry
        from gcodeproducer.core.jobs.path import Path
        from gcodeproducer.core.cam.paths import orient_contour
        op, diameter = run.op, run.diameter
        loops = selection.loops
        sign = {"outside": -1, "inside": 1, "on": 0}[op.side]
        paths = []
        for p, hole in zip(loops, geometry.hole_flags(loops)):
            out = geometry.offset_into_material(p, sign * (diameter / 2 + op.stock), hole) if sign else [p]
            for q in out:
                inside = not hole if op.side != "inside" else hole
                q = orient_contour(q, run.direction, material_inside=inside, index=len(paths))
                paths.append(Path("cut", q, closed=True, width=diameter))
        return paths, None
