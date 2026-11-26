"""PocketGenerator — planar clearing of a closed region to a flat floor."""
from __future__ import annotations
import math
import numpy as np
from .operation_generator import OperationGenerator


def pocket_paths(op, loops, region, diameter, direction, log=None, **adaptive_options):
    """Clearing paths for one planar pocket region (also used by Waterfall)."""
    from gcodeproducer.core.jobs.path import Path
    from gcodeproducer.core.geometry.infill import scan_fill
    from gcodeproducer.core.cam.paths import contour_pocket, link_contours, boundary_paths
    from gcodeproducer.core.cam.strategy import cutting_strategy
    from shapely.geometry import LineString
    from .operations_constants import RASTER_LINK_STEPS
    strategy = cutting_strategy(op.kind, op.strategy)
    paths = []
    if strategy == "contour":
        contours = contour_pocket(loops, diameter/2, op.stock, op.stepover, direction, log, region=region)
        linked = link_contours(contours, loops, diameter/2, op.stock, direction, op.stay_down, region=region)
        paths = [Path("cut", p, closed=True, width=diameter, stay_down=link,
                      stay_down_from=tuple(linked[i-1][0][0]) if link else None)
                 for i, (p, link) in enumerate(linked)]
    elif strategy == "adaptive":
        from gcodeproducer.core.cam.wavefront import wavefront_paths
        return wavefront_paths(op, region, diameter, direction, log, **adaptive_options)
    elif strategy in ("raster_x", "raster_y"):
        centre_region = region.buffer(-(diameter/2+op.stock))
        regions = [p for p, _ in boundary_paths(centre_region, direction)]
        if not regions:
            raise ValueError(f"{op.name}: pocket is too small for this tool")
        # scan_fill's angle is the line NORMAL, not its travel direction. Its lines step along the
        # normal and run from a to b with the next (uncut) line on their right: climb with M3.
        normal = math.pi/2 if strategy == "raster_x" else 0.
        spacing = diameter * op.stepover / 100
        lines = scan_fill(regions, normal, spacing, 0, 0, 0.01)
        n = np.array([math.cos(normal), math.sin(normal)])
        rows = {}
        for a, b in lines:
            rows.setdefault(round(float(np.dot(a, n))/spacing), []).append(np.array([a, b]))
        room = centre_region.buffer(1e-6)
        for k, row in enumerate(rows[key] for key in sorted(rows)):
            backwards = direction == "conventional" or (direction == "meander" and k % 2)
            if backwards:
                row = [pts[::-1] for pts in row[::-1]]
            for pts in row:
                path = Path("cut", pts, width=diameter)
                if direction == "meander" and paths and not paths[-1].closed:
                    # Meander: carry on to the next line along the area's edge without lifting.
                    end = tuple(paths[-1].points[-1])
                    link = LineString([end, tuple(pts[0])])
                    if link.length <= RASTER_LINK_STEPS*spacing+1e-9 and room.covers(link):
                        path.stay_down, path.stay_down_from = True, end
                paths.append(path)
        paths.extend(Path("cut", p, closed=True, width=diameter) for p in regions)
    else:
        raise ValueError(f"Unknown pocket strategy '{op.strategy}'")
    return paths


class PocketGenerator(OperationGenerator):
    kinds = ("pocket",)
    clearing = True
    needs_closed = True

    def paths(self, run, selection, planning):
        from shapely.geometry import box as shapely_box, Polygon
        from shapely import BufferJoinStyle
        from shapely.ops import unary_union
        from gcodeproducer.core.cam.paths import pocket_region
        from .clearing_region import apply_overcut, clearing_part_section, validate_overcut
        op, setup, ctx = run.op, planning.setup, planning.ctx
        if not 0 < op.stepover <= 100:
            raise ValueError("Pocket stepover must be between 0 and 100 percent")
        validate_overcut(op)
        if not math.isfinite(op.material_limit):
            raise ValueError(f"{op.name}: material boundary limit must be finite")
        loops = selection.loops
        stock_loops = selection.edge_loops(selection.stock_edges) if selection.stock_edges else []
        region = pocket_region(stock_loops if stock_loops else loops)
        limit = None
        if setup.stock.allocated:
            # contour_pocket insets every boundary by radius + roughing clearance. At the blank
            # edge the clearance protects nothing, so add it back: the cutter's outer edge then
            # lands exactly at blank edge + material_limit (0 touches, -1 leaves 1 mm, +1 passes).
            lo_s, hi_s = setup.stock.bounds
            reach_out = op.material_limit + op.stock
            limit = shapely_box(lo_s[0], lo_s[1], hi_s[0], hi_s[1])
            if abs(reach_out) > 1e-12:
                limit = limit.buffer(reach_out, join_style=BufferJoinStyle.mitre)
        if limit is not None and limit.is_empty:
            raise ValueError(f"{op.name}: material boundary limit removes the whole blank")
        protected = None
        if op.overcut > 0 or selection.stock_edges:
            protected = clearing_part_section(run, planning)
        if selection.stock_edges:
            # Material references define the exterior removal envelope, never permission
            # to machine through the model or automatically bore its internal holes.
            # Fill section holes conservatively; use a separate part-selected operation
            # for those features. Part references can still supply the end Z.
            sections = [protected] if protected.geom_type == "Polygon" else list(getattr(protected, "geoms", ()))
            protect = [Polygon(p.exterior) for p in sections if p.geom_type == "Polygon"]
            # Selected part rims/face footprints are retained inner boundaries,
            # not just depth hints. Honour them even above/below that model rim.
            protect.extend(pocket_region([loop]) for loop in selection.edge_loops(selection.keep_edges))
            protected = unary_union(protect)
            region = (limit if limit is not None else region).difference(protected).buffer(0)
            if region.is_empty:
                raise ValueError(f"{op.name}: no material outside the protected part at these depths")
            ctx.log(f"  {op.name}: material-boundary pocket; part sections protected")
        if op.overcut > 0:
            region = apply_overcut(region, op, protected, limit, ctx)
        elif limit is not None and not limit.is_empty and not limit.covers(region):
            region = region.intersection(limit).buffer(0)
            if region.is_empty:
                raise ValueError(f"{op.name}: material boundary limit removes the whole pocket")
        return pocket_paths(op, loops, region, run.diameter, run.direction, ctx.log,
                            cutting=run.cutting, tool_type=run.tool.get('type', 'endmill'),
                            tabs=bool(planning.tabs), depth_step=run.step, warn=planning.mark_partial), region
