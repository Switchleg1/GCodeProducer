"""WaterfallGenerator — full-area clearing at each depth, protecting all model material above it."""
from __future__ import annotations
from .operation_generator import OperationGenerator


class WaterfallGenerator(OperationGenerator):
    kinds = ("waterfall",)
    clearing = True
    needs_closed = True
    allows_sloped = True

    @staticmethod
    def free_at(run, region, limit, z, planning, edge=None):
        """(free region, active tabs) the cutter may work in at ``z``."""
        from shapely.geometry import box
        from shapely.ops import unary_union
        op = run.op
        blocked = planning.shadow.at(z)
        active = [box(lo[0], lo[1], hi[0], hi[1]) for lo, hi in planning.tabs if z < hi[2]-1e-6]
        if active:
            blocked = unary_union([blocked]+active)
        base = region if edge is None else unary_union([region, edge])
        free = base if blocked.is_empty else base.difference(blocked)
        if limit is not None:
            free = free.intersection(limit)
        free = free.buffer(0)
        return free, active

    def plan_ahead(self, run, region, limit, surface_top, planning, edge=None):
        """Adaptive clearing: plan every depth at once, in worker processes; {z: (material, plan)}.

        A depth's plan needs only that depth's free region and the material there,
        and cutting one depth never changes the material below it, so the depths
        are independent. The loop still checks each plan's material before use.
        """
        from gcodeproducer.core.cam.wavefront import plan_levels
        op = run.op
        if op.strategy != 'adaptive' or run.count < 2:
            return {}
        jobs = []
        for i in range(run.count):
            z = run.depth(i)
            if z >= surface_top-1e-6:
                continue
            free, active = self.free_at(run, region, limit, z, planning, edge)
            if active or free.is_empty or free.buffer(-(run.radius+op.stock)).is_empty:
                continue
            jobs.append((z, free, planning.material.planar_at(z), min(run.step, run.start-z)))
        if len(jobs) < 2:
            return {}
        plans = plan_levels(op, [(free, material, step) for _, free, material, step in jobs], run.diameter)
        return {z: (material, plan) for (z, _, material, _), plan in zip(jobs, plans)}

    def level_paths(self, run, region, limit, z, planning, edge=None, ahead=None):
        """(free region, areas) the cutter can clear at ``z``."""
        from gcodeproducer.core.cam.paths import machining_areas
        from .pocket_generator import pocket_paths
        op = run.op
        free, active = self.free_at(run, region, limit, z, planning, edge)
        if free.is_empty or free.buffer(-(run.radius+op.stock)).is_empty:
            return free, None
        try:
            options = {}
            if op.strategy == 'adaptive':
                material = planning.material.planar_at(z)
                options = dict(material=material, cutting=run.cutting,
                               tool_type=run.tool.get('type', 'endmill'), tabs=bool(active),
                               depth_step=min(run.step, run.start-z), warn=planning.mark_partial, depth_label=f'Z{z:g}')
                early = (ahead or {}).get(z)
                if early is not None and _same(early[0], material):
                    options['planned'] = early[1]
            paths = pocket_paths(op, [], free, run.diameter, run.direction,
                                 planning.ctx.log if op.strategy == 'adaptive' else None,
                                 **options)
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
        from .clearing_region import apply_overcut, clearing_part_section, validate_overcut
        from .surface_common import prepare_surface
        op, ctx, material = run.op, planning.ctx, planning.material
        validate_overcut(op)
        region, surface_top = prepare_surface(run, selection, planning)
        limit = edge = None
        setup = planning.setup
        if setup.stock.allocated:
            lo_s, hi_s = setup.stock.bounds
            blank = box(lo_s[0], lo_s[1], hi_s[0], hi_s[1])
            limit = blank
            grow = op.material_limit+op.stock
            if abs(grow) > 1e-12:
                limit = blank.buffer(grow, join_style=BufferJoinStyle.mitre)
        if op.overcut > 0:
            # Expand the selected boundary, not the per-depth holes left by part shadow or tabs.
            region = apply_overcut(region, op, clearing_part_section(run, planning), limit, ctx)
        if setup.stock.allocated and grow > 1e-12:
            # Clearing paths are offset by radius + stock to leave from every boundary. Stock
            # to leave protects the part, not the blank: where the region reaches the blank
            # edge, extend it by the same amount so the cutter edge still meets that edge
            # (plus the material boundary limit) instead of leaving a wall of raw stock.
            edge = limit.difference(blank).intersection(
                region.buffer(grow+1e-6, join_style=BufferJoinStyle.mitre))
            edge = None if edge.is_empty else edge
        if op.area_order == "area":
            ctx.log(f"  {op.name}: the reachable area changes with depth; machining each depth across all areas")
        produced = reachable = slopes = 0
        follow = (self.follow_setup(run, region if limit is None else region.intersection(limit), planning)
                  if op.follow_surface else None)
        ahead = self.plan_ahead(run, region, limit, surface_top, planning, edge)
        for i in range(run.count):
            z = run.depth(i)
            if z >= surface_top-1e-6:
                continue
            free, areas = self.level_paths(run, region, limit, z, planning, edge, ahead)
            if areas is None:
                ctx.log(f"  {op.name}: Z{z:g} has no area the cutter can reach above the model surface; pass skipped")
                continue
            reachable += len(areas)
            remaining = material.planar_at(z)
            for ai, planned in enumerate(areas):
                planned[0].stay_down, planned[0].stay_down_from = False, None
                # Adaptive paths were planned against this same material and only cut where it is;
                # checking them for air again would buffer every long chain for nothing.
                if planning.skip_air and remaining is not None and op.strategy != 'adaptive':
                    planned = drop_air_paths(planned, remaining, run.radius, op.name, ctx.log)
                    if not planned:
                        continue
                planning.add_warnings(plan_engagement(planned, planning.job, op, run.tool, None, remaining))
                material.remove_planar(planned, z, run.radius)
                run.add_layer(planning, planned, z, min(run.step, run.start-z), ai)
                produced += 1
            if follow is not None and not planning.debug_partial:
                slopes += self.follow_down(run, follow, z, i, planning)
            if planning.debug_partial:
                break
        if not produced and reachable:
            ctx.log(f"  {op.name}: selected area already cleared by earlier operations; no cutting needed")
            return
        if not produced:
            raise ValueError(f"{op.name}: no machinable paths between the selection and the model surface "
                             f"from Z{run.start:g} to Z{run.end:g}. Check that End Z is below the surface to machine "
                             "(link it to a lower edge/face) and that the cutter fits.")
        ctx.log(f"  {op.name}: 3D Waterfall limited by the model surface, {produced} area/depth passes, "
                f"Z{run.start:g} to Z{run.end:g}" + (f"; {slopes} surface-following passes between depths" if follow else ""))

    @staticmethod
    def follow_setup(run, region, planning):
        """(drop-height grid, tab floors, simplifier) for following the model between depths."""
        import math
        from shapely.geometry import box
        from gcodeproducer.core.cam.surface_simplifier import SurfaceSimplifier
        from gcodeproducer.core.settings.preferences import pref
        from .surface_common import drop_surface
        surface = drop_surface(run, region, planning)
        floors = [(box(lo[0], lo[1], hi[0], hi[1]).buffer(run.radius+run.op.stock+surface.resolution),
                   math.ceil(float(hi[2])*1000-1e-9)/1000) for lo, hi in planning.tabs]
        return surface, floors, SurfaceSimplifier(float(pref(planning.job, "cam_surface_tolerance"))), region

    def follow_down(self, run, follow, z, i, planning):
        """After the flat pass at ``z``: XYZ passes that follow the model down toward the next depth.

        Where the model slopes, the next depth cannot reach the material
        between this depth and the model, and a flat pass leaves it as a step.
        These passes trace the model (plus stock to leave) only where it lies
        between this depth and the next one, never below the next depth and
        never at or above this one, so they cut that step down to the surface.
        Returns the number of passes added.
        """
        from gcodeproducer.core.jobs.path import Path
        import numpy as np
        from gcodeproducer.core.cam.surface_paths import surface_raster
        from .operations_constants import FOLLOW_MIN_LENGTH
        surface, floors, simplifier, region = follow
        op = run.op
        floor = run.depth(i+1) if i+1 < run.count else run.end
        if floor >= z-1e-6:
            return 0
        lines = surface_raster(region, surface, run.radius, run.diameter*op.stepover/100, floor, op.stock,
                               planning.ctx.log, floors, z, "raster_x", simplifier=simplifier, above_floor=True)
        if not lines:
            return 0
        # Each line is cut from its highest point down the slope both ways, so each piece's lead can
        # ramp in along it from the cleared depth just above; a line climbing away from its start
        # leaves a ramp no room above the surface.
        pieces = []
        for p in lines:
            top = int(np.argmax(p[:, 2]))
            pieces.extend(q for q in (p[:top+1][::-1], p[top:]) if len(q) >= 2
                          and float(np.linalg.norm(np.diff(q[:, :2], axis=0), axis=1).sum()) > FOLLOW_MIN_LENGTH)
        lines = pieces
        if not lines:
            return 0
        low = min(float(p[:, 2].min()) for p in lines)
        run.add_layer(planning, [Path("cut", p, width=run.diameter) for p in lines], low, z-floor, 0)
        return 1


def _same(one, other):
    """Two material regions (or None) are the same, to well under a square micron."""
    if one is None or other is None:
        return one is other
    return one.symmetric_difference(other).area < 1e-6
