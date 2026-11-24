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

    def level_free(self, run, region, limit, z, above, planning, edge=None, follow=None):
        """(free region, active tabs) of the depth at ``z``.

        Following the surface, the depth works the area free at the depth
        above: where the model rises between the two depths the cutter rides up
        it instead of stopping at its shadow (see lift).
        """
        free, active = self.free_at(run, region, limit, z, planning, edge)
        if follow is None or above <= z+1e-6:
            return free, active
        from shapely.ops import unary_union
        wider, _ = self.free_at(run, region, limit, above, planning, edge)
        if active:
            wider = wider.difference(unary_union(active))
        return wider.union(free).buffer(0), active

    def plan_ahead(self, run, region, limit, surface_top, planning, edge=None, follow=None):
        """Adaptive clearing: plan every depth at once, in worker processes; {z: (material, plan)}.

        A depth's plan needs only that depth's free region and the material there,
        and cutting one depth never changes the material below it, so the depths
        are independent. The loop still checks each plan's material before use.
        """
        from gcodeproducer.core.cam.wavefront import plan_levels
        op = run.op
        if op.strategy != 'adaptive' or run.count < 2:
            return {}
        jobs, above = [], run.start
        for i in range(run.count):
            z = run.depth(i)
            if z >= surface_top-1e-6:
                continue
            # Adaptive plans the flat area only; the slope up to the depth above is a band of its own.
            free, active = self.level_free(run, region, limit, z, above, planning, edge, None)
            above = z
            if active or free.is_empty or free.buffer(-(run.radius+op.stock)).is_empty:
                continue
            jobs.append((z, free, planning.material.planar_at(z), min(run.step, run.start-z)))
        if len(jobs) < 2:
            return {}
        plans = plan_levels(op, [(free, material, step) for _, free, material, step in jobs], run.diameter)
        return {z: (material, plan) for (z, _, material, _), plan in zip(jobs, plans)}

    def level_paths(self, run, region, limit, z, planning, edge=None, ahead=None, above=None, follow=None):
        """(free region, areas) the cutter can clear at ``z``."""
        from gcodeproducer.core.cam.paths import machining_areas
        from .pocket_generator import pocket_paths
        op = run.op
        above = run.start if above is None else above
        # Adaptive engagement is planned in the plane: a front that rode up a slope would leave the next
        # front below it to cut under its whole width. So adaptive clears the flat area only, and the
        # slope up to the depth above is taken afterwards by passes stepping up it (slope_band).
        band_follow = follow if op.strategy == 'adaptive' else None
        free, active = self.level_free(run, region, limit, z, above, planning, edge,
                                       None if band_follow is not None else follow)
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
        areas = machining_areas(paths, "pocket", free) if paths else []
        if band_follow is not None and above > z+1e-6:
            wide, _ = self.level_free(run, region, limit, z, above, planning, edge, band_follow)
            band = self.slope_band(run, free, wide, band_follow, z, above)
            if band:
                for path in band:
                    path.slope = True
                areas.append(band)
        return free, areas

    @staticmethod
    def slope_band(run, flat, wide, follow=None, z=None, ceiling=None):
        """Passes up the slope between this depth and the one above, for adaptive clearing.

        The flat area is cleared first. Its cutter-centre region is then grown
        by one step at a time, each step a width the engagement limit allows,
        and the new edge inside the wider region (free at the depth above) is
        one pass: lifted onto the model, every pass is higher than the one
        before, so it takes only the step beside it and never cuts under a
        pass already made. Edges keep the stock on their right (climb).
        """
        import numpy as np
        from shapely.geometry import LineString
        from shapely.geometry.polygon import orient
        from gcodeproducer.core.jobs.path import Path
        from gcodeproducer.core.geometry.polygon_parts import polygons
        from .operations_constants import SLOPE_PASSES, SLOPE_STEP_MIN
        op = run.op
        offset = run.radius + op.stock
        inner, outer = flat.buffer(-offset), wide.buffer(-offset)
        if inner.is_empty or outer.difference(inner).area < 1e-3:
            return []
        step = max(SLOPE_STEP_MIN, run.diameter*op.adaptive_engagement/100)
        width = outer.hausdorff_distance(inner)
        pieces = []   # (step number, points, closed)
        for k in range(1, min(SLOPE_PASSES, int(width/step) + 2) + 1):
            grown = inner.buffer(k*step, quad_segs=8)
            for part in polygons(grown):
                part = orient(part, sign=1.)
                for ring in (part.exterior, *part.interiors):
                    line = LineString(ring.coords)
                    inside = line.intersection(outer)
                    if inside.is_empty:
                        continue
                    if inside.geom_type == 'LineString' and inside.equals(line):
                        pieces.append((k, np.asarray(line.coords, float)[:-1], True))
                        continue
                    for piece in getattr(inside, 'geoms', [inside]):
                        if piece.geom_type != 'LineString' or piece.length < run.radius:
                            continue
                        # GEOS keeps the line's direction in its pieces: still stock on the right.
                        pieces.append((k, np.asarray(piece.coords, float), False))
            if outer.difference(grown).area < 1e-3:
                break
        if follow is not None:
            pieces = WaterfallGenerator.on_the_slope(pieces, run, follow, ceiling)
        return WaterfallGenerator.chain_band(pieces, outer.difference(inner), step, run.diameter, outer)

    @staticmethod
    def on_the_slope(pieces, run, follow, ceiling):
        """Only the stretches of each pass that lie on the slope, below the depth above.

        Where the model rises past the depth above, a lifted pass would ride at
        that depth through air the pass above has already cleared. A pass round
        a part of the model crosses several such patches of slope; cut whole,
        every pass would visit each patch in turn, lifting off and entering
        again between them. Split there, each patch is climbed and finished
        before the cutter moves on.
        """
        import numpy as np
        from shapely import segmentize
        from shapely.geometry import LineString
        from gcodeproducer.core.cam.surface_paths import follow_heights
        from .operations_constants import SLOPE_AIR
        surface, floors = follow
        kept = []
        for k, points, closed in pieces:
            line = np.vstack((points, points[:1])) if closed else points
            dense = np.asarray(segmentize(LineString(line), surface.resolution).coords)[:, :2]
            low = follow_heights(surface, dense, run.radius, run.op.stock, floors) < ceiling - SLOPE_AIR
            if low.all():
                kept.append((k, points, closed))
                continue
            edges = np.flatnonzero(np.diff(np.r_[False, low, False].astype(int)))
            for first, last in zip(edges[::2], edges[1::2]):
                stretch = dense[first:last]
                if len(stretch) > 1 and LineString(stretch).length >= run.radius:
                    kept.append((k, stretch, False))
        return kept

    @staticmethod
    def chain_band(pieces, band, step, diameter, room=None):
        """Order the slope passes so the cutter finishes one stretch of slope before the next.

        A pass may be cut once every pass one step below it beside it is cut
        (it must never cut under a pass not yet made). Among the passes free
        to go, the nearest to where the cutter is goes next, so the cutter
        climbs the slope in one place and then moves on, instead of making
        each pass all round the model before the next. Each pass joins the last
        by a short step out where they are that close, so a stretch of slope is
        one path - one lead-in and one lead-out. Passes that run the same way
        (stretches of slope, not loops) are joined by riding back along the pass
        before last, which has cleared everything beside it, and stepping up.
        """
        import numpy as np
        from shapely import STRtree
        from shapely.geometry import LineString, Point
        from gcodeproducer.core.jobs.path import Path
        from .operations_constants import SLOPE_JOIN_STEPS, SLOPE_SLANT
        if not pieces:
            return []
        lines = [LineString(np.vstack((points, points[:1])) if closed else points) for _, points, closed in pieces]
        tree = STRtree(lines)
        below = []
        for i, (k, _, _) in enumerate(pieces):
            near = tree.query(lines[i], predicate='dwithin', distance=1.5*step)
            below.append({int(j) for j in near if pieces[int(j)][0] == k - 1})
        done, order, at = set(), [], None
        while len(done) < len(pieces):
            free = [i for i in range(len(pieces)) if i not in done and below[i] <= done]
            if not free:   # cannot happen with a well-formed band; take the lowest left rather than loop
                free = [min((i for i in range(len(pieces)) if i not in done), key=lambda i: pieces[i][0])]
            if at is None:
                pick = min(free, key=lambda i: (pieces[i][0], i))
            else:
                pick = min(free, key=lambda i: lines[i].distance(Point(at)))
            done.add(pick)
            k, points, closed = pieces[pick]
            if closed and at is not None:   # start a loop where it is nearest the cutter
                first = int(np.argmin(np.linalg.norm(points - np.asarray(at), axis=1)))
                points = np.vstack((points[first:], points[:first]))
            if closed:
                points = np.vstack((points, points[:1]))
            order.append(points)
            at = points[-1]
        reach = SLOPE_JOIN_STEPS*step

        def turn_into(here, points, room):
            """A half turn from the ride back into the next pass, so it meets the stock tangentially.

            Stepping straight across into it would drive the cutter's side into the
            face the pass is to cut; turning round behind its start, it comes onto it
            along its own way. Left out where the turn would leave the pocket.
            """
            start = points[0]
            ahead = points[min(len(points)-1, 1)] - start
            gap = start - here
            size, run_ = float(np.linalg.norm(gap)), float(np.linalg.norm(ahead))
            if size < 1e-6 or run_ < 1e-9:
                return []
            u, bulge = gap/size, -ahead/run_
            centre, rho = (here + start)/2, size/2
            turn = [centre + rho*(-u*np.cos(t) + bulge*np.sin(t)) for t in np.linspace(0., np.pi, 9)[1:-1]]
            if room is not None:
                from shapely.geometry import LineString as _Line
                if not room.buffer(1e-6).covers(_Line([here, *turn, start])):
                    return []
            return turn

        paths, chain, made = [], [], []
        for points in order:
            if chain and np.linalg.norm(points[0] - chain[-1]) <= reach:
                chain.extend(points)
                made.append(points)
                continue
            if chain and made:
                # Back to the start along the pass before last: everything beside it is cut, so the
                # cutter rides back through cleared slope and steps up into the next pass. After the
                # first pass of a stretch there is none yet; that pass itself is cut on both sides
                # but the stock it left, which the cutter only grazes going back.
                back = made[-2] if len(made) >= 2 else made[-1]
                a = int(np.argmin(np.linalg.norm(back - chain[-1], axis=1)))
                b = int(np.argmin(np.linalg.norm(back - points[0], axis=1)))
                if (a > b and np.linalg.norm(back[a] - chain[-1]) <= reach
                        and np.linalg.norm(back[b] - points[0]) <= reach):
                    chain.extend(back[b:a+1][::-1])
                    turn = turn_into(back[b], points, room)
                    if turn:
                        chain.extend(turn)
                        chain.extend(points)
                    else:
                        # No room to turn round behind it (it starts against a wall): come onto it at a
                        # slant a little way along, leaving its very start beside the wall.
                        along = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
                        j = min(int(np.searchsorted(along, SLOPE_SLANT*step)), len(points)-1)
                        chain.extend(points[j:])
                    made.append(points)
                    continue
            if len(chain) > 1:
                paths.append(Path('cut', np.asarray(chain, float), width=diameter))
            chain, made = list(points), [points]
        if len(chain) > 1:
            paths.append(Path('cut', np.asarray(chain, float), width=diameter))
        return paths

    def generate(self, run, selection, planning):
        from shapely.geometry import box
        from shapely import BufferJoinStyle
        import numpy as np
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
        produced = reachable = lifted = 0
        follow = self.follow_setup(run, region, planning) if op.follow_surface else None
        ahead = self.plan_ahead(run, region, limit, surface_top, planning, edge, follow)
        above = run.start
        for i in range(run.count):
            z = run.depth(i)
            if z >= surface_top-1e-6:
                continue
            free, areas = self.level_paths(run, region, limit, z, planning, edge, ahead, above, follow)
            ceiling, above = above, z
            if areas is None:
                ctx.log(f"  {op.name}: Z{z:g} has no area the cutter can reach above the model surface; pass skipped")
                continue
            reachable += len(areas)
            remaining = material.planar_at(z)
            for ai, planned in enumerate(areas):
                if follow is not None:
                    # Adaptive's own paths are planned in the flat area, where the model is below this
                    # depth: lifting them would only turn grid round-off at the model's edge into 3D moves,
                    # each split off and entered again on its own. Only its slope passes ride up.
                    planned = [self.lift(path, z, ceiling, follow, run)
                               if op.strategy != 'adaptive' or getattr(path, 'slope', False) else path
                               for path in planned]
                    lifted += sum(np.asarray(path.points).shape[1] == 3 for path in planned)
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
                f"Z{run.start:g} to Z{run.end:g}" + (f"; {lifted} paths follow the surface up to the depth above"
                                                      if follow else ""))

    @staticmethod
    def follow_setup(run, region, planning):
        """(drop-height grid, tab floors) for following the model within each depth."""
        import math
        from shapely.geometry import box
        from .surface_common import drop_surface
        surface = drop_surface(run, region.buffer(run.radius), planning)
        floors = [(box(lo[0], lo[1], hi[0], hi[1]).buffer(run.radius+run.op.stock+surface.resolution),
                   math.ceil(float(hi[2])*1000-1e-9)/1000) for lo, hi in planning.tabs]
        return surface, floors

    @staticmethod
    def lift(path, z, ceiling, follow, run):
        """The path with its depth varied: at ``z``, raised over the model (plus stock to leave) up to ``ceiling``.

        A flat depth stops at the model's shadow and leaves the slope above it
        as a step. Working the area free at the depth above instead, each point
        rides at the model's height under the cutter where that is above this
        depth, so the step is cut down to the surface in the same pass. Paths
        that stay flat are returned unchanged; a lifted closed contour is opened
        at its highest point so its lead ramps in down the slope.
        """
        import numpy as np
        from shapely import segmentize
        from shapely.geometry import LineString
        from gcodeproducer.core.jobs.path import Path
        from gcodeproducer.core.cam.surface_simplifier import simplify3d
        from gcodeproducer.core.cam.surface_paths import follow_heights
        surface, floors = follow
        xy = np.asarray(path.points, float)[:, :2]
        if len(xy) < 2 or ceiling <= z+1e-6:
            return path
        if path.closed:
            xy = np.vstack((xy, xy[:1]))
        dense = np.asarray(segmentize(LineString(xy), surface.resolution).coords)[:, :2]
        depth = np.clip(follow_heights(surface, dense, run.radius, run.op.stock, floors), z, ceiling)
        if depth.max() <= z+1e-6:
            return path
        points = np.column_stack((dense, depth))
        if path.closed:
            top = int(np.argmax(points[:-1, 2]))
            points = np.vstack((points[top:-1], points[:top+1]))
        lifted = Path(path.feature, simplify3d(points), width=path.width, speed=path.speed)
        return lifted


def _same(one, other):
    """Two material regions (or None) are the same, to well under a square micron."""
    if one is None or other is None:
        return one is other
    return one.symmetric_difference(other).area < 1e-6
