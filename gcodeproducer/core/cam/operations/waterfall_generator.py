"""WaterfallGenerator — full-area clearing at each depth, protecting all model material above it."""
from __future__ import annotations
from .operation_generator import OperationGenerator


class WaterfallGenerator(OperationGenerator):
    kinds = ("waterfall",)
    clearing = True
    needs_closed = True
    allows_sloped = True

    def level_paths(self, run, region, limit, z, planning):
        """(free region, areas) the cutter can clear at ``z`` — pure geometry, no material history."""
        from shapely.geometry import box
        from shapely.ops import unary_union
        from gcodeproducer.core.cam.paths import machining_areas
        from .pocket_generator import pocket_paths
        op = run.op
        blocked = planning.shadow.at(z)
        active = [box(lo[0], lo[1], hi[0], hi[1]) for lo, hi in planning.tabs if z < hi[2]-1e-6]
        if active:
            blocked = unary_union([blocked]+active)
        free = region if blocked.is_empty else region.difference(blocked)
        if limit is not None:
            free = free.intersection(limit)
        free = free.buffer(0)
        if free.is_empty or free.buffer(-(run.radius+op.stock)).is_empty:
            return free, None
        try:
            paths = pocket_paths(op, [], free, run.diameter, run.direction)
        except ValueError as exc:
            if "too small" not in str(exc):
                raise
            return free, []
        return free, machining_areas(paths, "pocket", free) if paths else []

    def generate(self, run, selection, planning):
        from shapely.geometry import box
        from shapely import BufferJoinStyle
        from gcodeproducer.core.cam.engagement import plan_engagement
        from gcodeproducer.core.cam.planner.pass_scheduler import drop_air_paths
        from .surface_common import prepare_surface
        op, ctx, material = run.op, planning.ctx, planning.material
        region, surface_top = prepare_surface(run, selection, planning)
        limit = None
        setup = planning.setup
        if setup.stock.allocated:
            lo_s, hi_s = setup.stock.bounds
            limit = box(lo_s[0], lo_s[1], hi_s[0], hi_s[1])
            if abs(op.material_limit+op.stock) > 1e-12:
                limit = limit.buffer(op.material_limit+op.stock, join_style=BufferJoinStyle.mitre)
        if op.area_order == "area":
            ctx.log(f"  {op.name}: the reachable area changes with depth; machining each depth across all areas")
        produced = reachable = 0
        for i in range(run.count):
            z = run.depth(i)
            if z >= surface_top-1e-6:
                continue
            free, areas = self.level_paths(run, region, limit, z, planning)
            if areas is None:
                ctx.log(f"  {op.name}: Z{z:g} has no area the cutter can reach above the model surface; pass skipped")
                continue
            reachable += len(areas)
            remaining = material.planar_at(z)
            for ai, planned in enumerate(areas):
                planned[0].stay_down, planned[0].stay_down_from = False, None
                if planning.skip_air and remaining is not None:
                    planned = drop_air_paths(planned, remaining, run.radius, op.name, ctx.log)
                    if not planned:
                        continue
                planning.add_warnings(plan_engagement(planned, planning.job, op, run.tool, None, remaining))
                material.remove_planar(planned, z, run.radius)
                run.add_layer(planning, planned, z, min(run.step, run.start-z), ai)
                produced += 1
        if not produced and reachable:
            ctx.log(f"  {op.name}: selected area already cleared by earlier operations; no cutting needed")
            return
        if not produced:
            raise ValueError(f"{op.name}: no machinable paths between the selection and the model surface "
                             f"from Z{run.start:g} to Z{run.end:g}. Check that End Z is below the surface to machine "
                             "(link it to a lower edge/face) and that the cutter fits.")
        ctx.log(f"  {op.name}: 3D Waterfall limited by the model surface, {produced} area/depth passes, "
                f"Z{run.start:g} to Z{run.end:g}")
