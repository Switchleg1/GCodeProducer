"""Model-specific, ordered CAM setup. Geometry references survive placement changes.

STL has no CAD topology. Connected coplanar triangles form faces; feature
edges omit triangle seams. Part references use original triangle/vertex indices
and are re-evaluated against the placed mesh. Drawn outlines use stable IDs
and remain in CAM work coordinates; they are not attached mesh topology.
"""
from __future__ import annotations

from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.operation import Operation
from gcodeproducer.core.cam.tool_group import ToolGroup
from gcodeproducer.core.cam.cam_setup import CAMSetup
from gcodeproducer.core.cam.topology import Topology
from gcodeproducer.core.cam.cam_constants import KINDS, KIND_LABELS, SURFACE_KINDS, SURFACE_MIN_RESOLUTION, SURFACE_CELLS_PER_DIAMETER
from dataclasses import asdict
import hashlib, math, numpy as np, gcodeproducer.core.geometry.kernel as geometry


def fingerprint(mesh):
    h = hashlib.sha256()
    h.update(np.ascontiguousarray(mesh.vertices).tobytes())
    h.update(np.ascontiguousarray(mesh.triangles).tobytes())
    return h.hexdigest()


def chains(edges):
    """Vertex-index polylines. Stop at branches; preserve open and closed edges."""
    adjacency = {}
    remaining = set()
    for a, b in edges:
        a, b = int(a), int(b)
        remaining.add(tuple(sorted((a, b))))
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    result = []
    ends = sorted(v for v in adjacency if len(adjacency[v]) != 2)
    while remaining:
        while ends and not any(tuple(sorted((ends[-1], v))) in remaining for v in adjacency[ends[-1]]):
            ends.pop()
        if ends:
            a = ends[-1]
            b = min(v for v in adjacency[a] if tuple(sorted((a, v))) in remaining)
        else:
            a, b = next(iter(remaining))
        path = [a, b]
        remaining.remove(tuple(sorted((a, b))))
        while b != a and len(adjacency[b]) == 2:
            candidates = [v for v in adjacency[b] if tuple(sorted((b, v))) in remaining]
            if not candidates:
                break
            c = min(candidates)
            remaining.remove(tuple(sorted((b, c))))
            path.append(c)
            b = c
        result.append(path)
    return result


def pick_geometry(payload):
    mesh, mode, origin, direction, mvp, viewport, mouse, *stocks = payload
    shapes = stocks[1] if len(stocks) > 1 else ()
    if mode.startswith("reference_"):
        from .reference_geometry import pick
        return pick(shapes, mode.removeprefix("reference_"), origin, direction, mvp, viewport, mouse)
    if mode.startswith("mixed_"):
        base = mode.removeprefix("mixed_")
        part = pick_geometry((mesh, base, origin, direction, mvp, viewport, mouse))
        from gcodeproducer.core.cam.stock_geometry import pick
        material = pick(stocks[0] if stocks else None, "stock_"+base, origin, direction, mvp, viewport, mouse)
        from .reference_geometry import pick as pick_reference
        drawing = pick_reference(shapes, base, origin, direction, mvp, viewport, mouse)
        candidates = [v for v in (part, material, drawing) if v and "reference" in v]
        if not candidates:
            return part
        if base == "edge":
            # Same-pixel ties keep the established part/material priority.
            result = candidates[0]
            for candidate in candidates[1:]:
                if candidate["pick_distance"] < result["pick_distance"]-1e-5:
                    result = candidate
            return result
        return part or drawing or material
    if mode.startswith("stock_"):
        from gcodeproducer.core.cam.stock_geometry import pick
        return pick(stocks[0] if stocks else None, mode, origin, direction, mvp, viewport, mouse)
    topo = cached_topology(mesh)
    distance, tri = geometry.ray_triangles(origin, direction, topo.vertices[topo.triangles])
    ref = None
    if mode == "face" and tri >= 0:
        ref = Reference("face", [min(topo.face(int(tri)))])
    elif mode == "edge":
        # Screen-space tolerance, with visibility checked against the surface ray.
        best = 10.0
        inverse = np.linalg.inv(np.asarray(mvp, dtype=float))
        for chain in topo.feature_chains:
            p = topo.vertices[chain]
            clip = np.column_stack((p, np.ones(len(p)))) @ np.asarray(mvp).T
            valid = clip[:, 3] > 0
            ndc = clip[:, :3] / clip[:, 3:4]
            screen = (ndc[:, :2] * [1, -1] + 1) * np.asarray(viewport) / 2
            for j, (a, b) in enumerate(zip(screen, screen[1:])):
                if not (valid[j] and valid[j + 1]):
                    continue
                d = b - a
                u = np.clip(np.dot(np.asarray(mouse) - a, d) / max(np.dot(d, d), 1e-12), 0, 1)
                delta = np.linalg.norm(np.asarray(mouse) - (a + u * d))
                # Separate visibility ray at the closest edge point (not the mouse).
                point = p[j] + u * (p[j + 1] - p[j])
                # Visibility must follow the candidate edge's pixel, not the mouse
                # pixel: an offset mouse ray incorrectly hides edges in orthographic views.
                projected = np.asarray(mvp) @ np.r_[point, 1]
                near = inverse @ np.r_[projected[:2] / projected[3], -1, 1]
                edge_origin = near[:3] / near[3]
                ray = point - edge_origin
                length = np.linalg.norm(ray)
                if delta < best and length > 0:
                    hit, _ = geometry.ray_triangles(edge_origin, ray / length, topo.vertices[topo.triangles])
                    if hit < length - 1e-4:
                        continue
                    best, ref = delta, Reference("edge", sorted([int(chain[0]), int(chain[1])]))
    if ref is None:
        return None
    z = topo.points(ref)[:, 2]
    result = {"reference": ref, "z_min": float(z.min()), "z_max": float(z.max())}
    if mode == "edge":result["pick_distance"] = float(best)
    return result


_cached = (None, None)


def cached_topology(mesh, reference_shapes=()):
    global _cached
    key = fingerprint(mesh)
    if key != _cached[0]:
        _cached = (key, Topology(mesh))
    references = {s.id:s for s in reference_shapes}
    if len(references) != len(reference_shapes):
        raise ValueError("Reference geometry IDs must be unique")
    _cached[1].reference_shapes = references
    return _cached[1]


def highlight_geometry(payload):
    mesh, op, *stocks = payload
    op_stock = stocks[0] if stocks else None
    shapes = stocks[3] if len(stocks) > 3 else ()
    topo = cached_topology(mesh, shapes)
    try:
        refs = [] if op is None else list(op.geometry) + list(op.height_references)
        if op is not None:
            for depth in (op.start, op.end):
                if depth.source == "geometry" and depth.reference is not None and depth.reference not in refs:
                    refs.append(depth.reference)
        out = topo.highlight(refs, op_stock) if op is not None else {"faces": [], "edges": np.empty((0, 3)), "depths": ""}
    except ValueError as exc:
        out = {"faces": [], "edges": np.empty((0, 3)), "depths": str(exc), "geometry_error": str(exc)}
    from .reference_geometry import line_segments, filled_shapes
    try:
        out["reference_geometry"] = line_segments(shapes)
        focus = stocks[4] if len(stocks) > 4 else None
        focused = [s for s in shapes if s.id == focus]
        out["reference_focus"] = line_segments(focused)
        out["reference_focus_fill"] = filled_shapes(focused)
        selected_ids = {ref.indices[0] for ref in refs if ref.kind == "drawing" and ref.indices}
        out["reference_selection_fill"] = filled_shapes([s for s in shapes if s.id in selected_ids])
    except ValueError as exc:
        out["reference_geometry"] = out["reference_focus"] = np.empty((0, 3))
        out["reference_focus_fill"] = out["reference_selection_fill"] = np.empty((0, 3))
        out["geometry_error"] = str(exc)
    out["tabs"] = []
    if len(stocks) > 2 and stocks[2]:
        from gcodeproducer.core.cam.tabs import resolve_bounds
        try:
            out["tabs"] = resolve_bounds(mesh, op_stock, stocks[2])
        except ValueError as exc:
            out["tab_error"] = str(exc)
    if op is None or out.get("geometry_error"):
        return out
    if len(stocks) > 1 and stocks[1]:
        from gcodeproducer.core.cam.cutting import resolve_cutting
        context = stocks[1]
        try:
            data = resolve_cutting(context["machine"],context["tool"],op_stock,op)
            out["cutting_values"] = asdict(data)
            out["cutting_values"]["cut_direction"] = (context["machine"].get("cut_direction", "climb")
                                                       if op.cut_direction == "machine" else op.cut_direction)
            out["cutting"] = data.summary()
        except ValueError as exc:
            out["cutting"] = str(exc)
    try:
        out["depths"] = f"Resolved Z: start {op.start.resolve(mesh, topo, op.geometry, op_stock):.3f}, end {op.end.resolve(mesh, topo, op.geometry, op_stock):.3f} mm"
    except ValueError as exc:
        out["depths"] = str(exc)
    return out


def _drop_air_paths(paths, remaining, radius, name, log=None):
    """Remove pocket paths whose cutter sweep meets no remaining material at this depth.

    A path after a dropped one loses stay-down permission (its expected previous
    endpoint no longer exists); the emitter then enters from safe height.
    """
    from shapely.geometry import LineString
    from shapely.geometry import Point
    from shapely.prepared import prep
    probe = prep(remaining)
    kept, dropped, broken = [], 0, False
    for path in paths:
        p = np.asarray(path.points)[:, :2]
        geom = Point(p[0]).buffer(radius) if len(p) == 1 else LineString(np.vstack((p, p[0])) if path.closed else p).buffer(radius)
        if probe.intersects(geom) and remaining.intersection(geom).area > 1e-9:
            if broken:
                path.stay_down, path.stay_down_from = False, None
                broken = False
            kept.append(path)
        else:
            dropped += 1
            broken = True
    if dropped and log:
        log(f"  {name}: {dropped} air-only paths removed at this depth")
    return kept


def _tab_schedule(areas, op, region, tabs, start, end, step, count, radius, log=None):
    """Schedule depth bands separated by tab tops, splitting only below each tab.

    Upper passes still cut the stock OVER the tabs normally. Once a tab becomes
    active its interrupted path sections are areas: finish a section to depth,
    or visit every section at each depth, following the operation's Area order.
    """
    from gcodeproducer.core.cam.tabs import mask_at
    from gcodeproducer.core.cam.tabs import clip_paths
    from gcodeproducer.core.cam.paths import machining_areas
    records = []
    next_area = 0
    indices = list(range(count))
    # Roofs round upward to emitted G-code precision, never into the rail.
    roofs = sorted({math.ceil(float(hi[2])*1000-1e-9)/1000 for _, hi in tabs
                    if end < hi[2] < start}, reverse=True)
    for roof in roofs:
        if roof >= start-1e-6:
            continue
        if not any(abs(max(end, start-(i+1)*step)-roof) < 1e-6 for i in indices):
            indices.append((start-roof)/step-1)
            if log:log(f"  {op.name}: added tab-top pass Z{roof:g} before splitting paths below the rail")
    indices.sort()
    for parent, paths in enumerate(areas):
        bands = []
        for i in indices:
            z = float(f"{max(end, start-(i+1)*step):.3f}")
            active = tuple(j for j, (_, hi) in enumerate(tabs) if z < hi[2]-1e-6)
            if bands and bands[-1][0] == active:
                bands[-1][1].append(i)
            else:
                bands.append((active, [i]))
        for active, depths in bands:
            if not active:
                pieces = [paths]
            else:
                z = float(f"{max(end, start-(depths[-1]+1)*step):.3f}")
                mask = mask_at(tabs, z, radius)
                clipped = clip_paths(paths, mask)
                if not clipped:
                    if log:log(f"  {op.name}: tab-protected area {parent+1}, {len(depths)} depth passes omitted")
                    continue
                if op.kind == "pocket":
                    centre = region.buffer(-(radius+op.stock)).difference(mask)
                    pieces = machining_areas(clipped, op.kind, centre)
                else:
                    pieces = [[p] for p in clipped]
                if log:log(f"  {op.name}: holding tabs split area {parent+1} into {len(pieces)} sections below Z"
                           f"{min(tabs[j][1][2] for j in active):g}")
            for piece in pieces:
                if len(records)+len(depths)>100000:
                    raise ValueError(f"{op.name}: too many tab sections/depth passes")
                for i in depths:
                    records.append((next_area, i, active, piece))
                next_area += 1
    if op.area_order == "depth":
        records.sort(key=lambda item: (item[1], item[0]))
    return records


def _surface_operation(job, ctx, op, tool, loops, start, end, step, count, direction, tabs,
                       material_history, shadow, skip_air, add_layer):
    """Depth-limited model-surface clearing: 3D Waterfall and 3D Contour.

    At each level the cutter stays out of the XY shadow of all model material above
    that level, so sloped and curved floors become terraces and undercuts are never
    entered. Holding tabs standing above a level are treated like model material.
    """
    from shapely.geometry import box
    from shapely.ops import unary_union
    from shapely import BufferJoinStyle
    from gcodeproducer.core.jobs.path import Path
    from gcodeproducer.core.cam.paths import machining_areas
    from gcodeproducer.core.cam.engagement import plan_engagement
    from gcodeproducer.core.cam.surface_paths import selection_region, surface_raster
    from gcodeproducer.core.settings.preferences import pref
    setup = job.cam_setup
    diameter = float(tool.get("diameter", 0))
    radius = diameter/2
    label = KIND_LABELS[op.kind]
    if not 0 < op.stepover <= 100:
        raise ValueError(f"{op.name}: stepover must be between 0 and 100 percent")
    if op.stock < 0 or not math.isfinite(op.stock):
        raise ValueError(f"{op.name}: stock to leave must be zero or positive")
    region = selection_region(loops, ctx.log, op.name)
    surface_top = max(float(job.mesh.bounds[1][2]), setup.stock.top if setup.stock.allocated else -math.inf)
    if start < surface_top-1e-6:
        ctx.log(f"  {op.name}: clearing above selected Start Z{start:g} from material surface Z{surface_top:g}")
        start = surface_top
        count = max(1, math.ceil((start-end)/step))
        if count > 10000:
            raise ValueError(f"{op.name}: too many depth passes from the material surface")
    reach = float(tool.get("length", 0) or 0)
    if reach > 0 and surface_top-end > reach+1e-3:
        warning = (f"{op.name}: {surface_top-end:g} mm below the material surface (Z{surface_top:g}) exceeds the "
                   f"tool cutting length {reach:g} mm; verify reach, shank and holder clearance.")
        if warning not in job.warnings:
            job.warnings.append(warning)
            ctx.log("REACH WARNING: "+warning)
    produced = reachable = 0
    if op.kind == "contour3d":
        from gcodeproducer.core.cam.drop_surface import DropSurface
        wanted = max(SURFACE_MIN_RESOLUTION, min(float(pref(job, "stock_resolution")), diameter/SURFACE_CELLS_PER_DIAMETER))
        minx, miny, maxx, maxy = region.bounds
        pad = radius+3*wanted
        surface = DropSurface(job.mesh, (minx-pad, miny-pad), (maxx+pad, maxy+pad), wanted,
                              int(pref(job, "stock_max_cells")))
        if surface.resolution > wanted+1e-9:
            warning = (f"{op.name}: surface height grid coarsened to {surface.resolution:.3f} mm (cell limit); "
                       "more material is left on slopes.")
            job.warnings.append(warning)
            ctx.log("SURFACE WARNING: "+warning)
        floors = [(box(lo[0], lo[1], hi[0], hi[1]).buffer(radius+op.stock+surface.resolution),
                   math.ceil(float(hi[2])*1000-1e-9)/1000) for lo, hi in tabs]
        for i in range(count):
            z = max(end, start-(i+1)*step)
            if z >= surface_top-1e-6:
                continue
            lines = surface_raster(region, surface, radius, diameter*op.stepover/100, z, op.stock,
                                   ctx.log, floors, min(start, surface_top), strategy=op.strategy)
            if not lines:
                continue
            low = min(float(p[:, 2].min()) for p in lines)
            # Clamp to successive floors: never drop straight to the final
            # surface through uncleared material above it.
            add_layer([Path("cut", p, width=diameter) for p in lines], low, min(step, start-z), 0)
            produced += 1
        if not produced:
            raise ValueError(f"{op.name}: no model surface below Start Z{start:g} that the cutter can reach in the "
                             "selected area. Check Start/End Z and the tool diameter.")
        ctx.log(f"  {op.name}: {label}, {produced} depth-limited surface passes, "
                f"maximum depth per pass {step:g} mm, Z{start:g} to Z{end:g}")
        return
    limit = None
    if setup.stock.allocated:
        lo_s, hi_s = setup.stock.bounds
        limit = box(lo_s[0], lo_s[1], hi_s[0], hi_s[1])
        if abs(op.material_limit+op.stock) > 1e-12:
            limit = limit.buffer(op.material_limit+op.stock, join_style=BufferJoinStyle.mitre)
    if op.area_order == "area":
        ctx.log(f"  {op.name}: the reachable area changes with depth; machining each depth across all areas")
    for i in range(count):
        z = max(end, start-(i+1)*step)
        blocked = shadow.at(z)
        active = [box(lo[0], lo[1], hi[0], hi[1]) for lo, hi in tabs if z < hi[2]-1e-6]
        if active:
            blocked = unary_union([blocked]+active)
        if z >= surface_top-1e-6:
            continue
        free = region if blocked.is_empty else region.difference(blocked)
        if limit is not None:
            free = free.intersection(limit)
        free = free.buffer(0)
        if free.is_empty or free.buffer(-(radius+op.stock)).is_empty:
            ctx.log(f"  {op.name}: Z{z:g} has no area the cutter can reach above the model surface; pass skipped")
            continue
        try:
            paths = _pocket_paths(op, [], free, diameter, direction)
        except ValueError as exc:
            if "too small" not in str(exc):
                raise
            continue
        areas = machining_areas(paths, "pocket", free) if paths else []
        reachable += len(areas)
        remaining = material_history.at(z) if material_history else None
        for ai, planned in enumerate(areas):
            planned[0].stay_down, planned[0].stay_down_from = False, None
            if skip_air and remaining is not None:
                planned = _drop_air_paths(planned, remaining, radius, op.name, ctx.log)
                if not planned:
                    continue
            for warning in plan_engagement(planned, job, op, tool, None, remaining):
                if warning not in job.warnings:
                    job.warnings.append(warning)
            if material_history:
                material_history.remove(planned, z, radius)
            add_layer(planned, z, min(step, start-z), ai)
            produced += 1
    if not produced and reachable:
        ctx.log(f"  {op.name}: selected area already cleared by earlier operations; no cutting needed")
        return
    if not produced:
        raise ValueError(f"{op.name}: no machinable paths between the selection and the model surface "
                         f"from Z{start:g} to Z{end:g}. Check that End Z is below the surface to machine "
                         "(link it to a lower edge/face) and that the cutter fits.")
    kind = "" if op.kind == "pocket" else label+" "
    ctx.log(f"  {op.name}: {kind}limited by the model surface, {produced} area/depth passes, Z{start:g} to Z{end:g}")


def _pocket_paths(op, loops, region, diameter, direction, log=None):
    """Wall-parallel or raster clearing paths for one planar pocket region."""
    from gcodeproducer.core.jobs.path import Path
    from gcodeproducer.core.geometry.infill import scan_fill
    from gcodeproducer.core.cam.paths import contour_pocket, link_contours, boundary_paths
    from gcodeproducer.core.cam.strategy import cutting_strategy
    strategy = cutting_strategy(op.kind, op.strategy)
    paths = []
    if strategy == "contour":
        contours = contour_pocket(loops, diameter/2, op.stock, op.stepover, direction, log, region=region)
        linked = link_contours(contours, loops, diameter/2, op.stock, direction, op.stay_down, region=region)
        paths = [Path("cut", p, closed=True, width=diameter, stay_down=link,
                      stay_down_from=tuple(linked[i-1][0][0]) if link else None)
                 for i, (p, link) in enumerate(linked)]
    elif strategy in ("raster_x", "raster_y"):
        centre_region = region.buffer(-(diameter/2+op.stock))
        regions = [p for p, _ in boundary_paths(centre_region, direction)]
        if not regions:
            raise ValueError(f"{op.name}: pocket is too small for this tool")
        # scan_fill's angle is the line NORMAL, not its travel direction.
        normal = math.pi/2 if strategy == "raster_x" else 0.
        for a, b in scan_fill(regions, normal, diameter * op.stepover / 100, 0, 0, 0.01):
            pts = np.array([a, b])
            if direction == "conventional" or (direction == "meander" and len(paths) % 2):
                pts = pts[::-1]
            paths.append(Path("cut", pts, width=diameter))
        paths.extend(Path("cut", p, closed=True, width=diameter) for p in regions)
    else:
        raise ValueError(f"Unknown pocket strategy '{op.strategy}'")
    return paths


def generate(job, ctx):
    """Generate ordered 2.5D operations. Fail rather than silently machining wrong geometry."""
    from gcodeproducer.core.jobs.layer import Layer
    from gcodeproducer.core.jobs.path import Path
    from gcodeproducer.core.cam.paths import direction_for
    from gcodeproducer.core.cam.paths import orient_contour
    from gcodeproducer.core.cam.paths import pocket_region
    from gcodeproducer.core.cam.paths import part_section
    from gcodeproducer.core.cam.paths import overcut_region
    from gcodeproducer.core.cam.paths import machining_areas
    from gcodeproducer.core.settings.preferences import pref
    from shapely.geometry import box as shapely_box
    from shapely import BufferJoinStyle
    skip_air = bool(pref(job, "skip_air_cuts"))
    setup = job.cam_setup
    topo = cached_topology(job.mesh, setup.reference_shapes)
    tools = {t.id: t for t in job.tools}
    import copy
    from gcodeproducer.core.cam.planar_stock import PlanarStock
    material_history = PlanarStock(setup.stock) if setup.stock.allocated else None
    from gcodeproducer.core.cam.tabs import resolve_tabs
    tabs = resolve_tabs(job.mesh, setup)
    if tabs:
        ctx.log(f"  {len(tabs)} holding tabs protected across all operations")
    layers = []
    model_shadow = None
    from gcodeproducer.core.cam.model_shadow import ModelShadow
    job.warnings = []
    numbers={}
    for group in setup.groups:
        t=tools.get(group.tool_id)
        if t is not None:
            number=int(t.get("tool_number",1))
            if number in numbers and numbers[number]!=t.id:
                warning=f"Tool number T{number} is shared by different tool profiles; verify the physical tool change."
                if warning not in job.warnings:
                    job.warnings.append(warning)
                    ctx.log("TOOL WARNING: "+warning)
            numbers[number]=t.id
    for gi, group in enumerate(setup.groups):
        if group.tool_id not in tools:
            raise ValueError(f"CAM tool '{group.tool_id}' is missing or not allowed by the machine")
        tool = tools[group.tool_id]
        diameter = float(tool.get("diameter", 0))
        if diameter <= 0:
            raise ValueError("Tool diameter must be positive")
        for oi, op in enumerate(group.operations):
            if not op.enabled:
                continue
            if op.kind not in KINDS or not op.geometry:
                raise ValueError(f"{op.name}: select machining geometry first")
            start = op.start.resolve(job.mesh, topo, op.geometry, setup.stock)
            end = op.end.resolve(job.mesh, topo, op.geometry, setup.stock)
            if ((op.kind == "pocket" or op.kind in SURFACE_KINDS) and op.start.source == "selection" and math.isfinite(start)
                    and math.isfinite(end) and start <= end + 1e-6):
                # A single flat floor selection has no higher edge: begin at the material
                # surface (air-cut removal then drops to the current material top).
                start = Depth("stock_top", op.start.value).resolve(job.mesh, topo, op.geometry, setup.stock)
                ctx.log(f"  {op.name}: flat selection; start taken from the material surface Z{start:g}")
            if not (math.isfinite(start) and math.isfinite(end)) or end > start:
                raise ValueError(f"{op.name}: end Z must be at or below start Z")
            if not op.auto_stepdown and (op.stepdown <= 0 or not math.isfinite(op.stepdown)):
                raise ValueError(f"{op.name}: stepdown must be positive")
            from gcodeproducer.core.cam.cutting import resolve_cutting
            cutting = resolve_cutting(job.machine, tool, setup.stock, op)
            step = cutting.stepdown
            if step <= 0 or not math.isfinite(step):
                raise ValueError(f"{op.name}: tool depth per pass must be positive")
            count = max(1, math.ceil((start - end) / step))
            if count > 10000:
                raise ValueError(f"{op.name}: too many depth passes")
            safe = float(job.m("safe_z", 15))
            if safe <= max(float(job.mesh.bounds[1][2]), start,
                           setup.stock.top if setup.stock.allocated else -math.inf):
                raise ValueError("Safe Z must be above the model and all operation start heights")
            clearing = op.kind in ("pocket", "waterfall")
            selected_edges, stock_edges, keep_edges = set(), set(), set()
            cam_vertices = topo.vertices
            has_stock_bounds = any(ref.kind.startswith("stock_") for ref in op.geometry)
            if has_stock_bounds:
                from gcodeproducer.core.cam.stock_geometry import vertices as stock_vertices
                cam_vertices = np.vstack((topo.vertices, stock_vertices(setup.stock)))
            for ref in op.geometry:
                if ref.kind == "drawing":
                    points = topo.polylines(ref, setup.stock)[0][:-1]
                    ids = list(range(len(cam_vertices),len(cam_vertices)+len(points)))
                    cam_vertices = np.vstack((cam_vertices,points))
                    edges = list(zip(ids, ids[1:]+ids[:1]))
                    keep_edges.update(tuple(sorted(e)) for e in edges)
                elif ref.kind.startswith("stock_"):
                    from gcodeproducer.core.cam.stock_geometry import indices as stock_indices
                    from gcodeproducer.core.cam.cam_constants import FACES
                    local_ids = stock_indices(ref)
                    if ref.kind == "stock_edge" and clearing:
                        if np.ptp(cam_vertices[[len(topo.vertices)+i for i in local_ids], 2]) > 1e-4:
                            raise ValueError(f"{op.name}: select a horizontal material edge for a pocket rim")
                        # One straight stock edge identifies the whole top/bottom rim.
                        local_ids = FACES[1 if local_ids[0] >= 4 else 0]
                    ids = [len(topo.vertices)+i for i in local_ids]
                    if ref.kind == "stock_face" or len(ids) == 4:
                        if np.ptp(cam_vertices[ids, 2]) > 1e-4:
                            raise ValueError(f"{op.name}: 2.5D operations require a horizontal material face; use side faces as height references")
                        ids.append(ids[0])
                    edges = list(zip(ids, ids[1:]))
                    stock_edges.update(tuple(sorted(e)) for e in edges)
                elif ref.kind == "face":
                    pts = topo.vertices[topo.triangles[topo.face(ref.indices[0])]].reshape(-1, 3)
                    if np.ptp(pts[:, 2]) > 1e-4:
                        raise ValueError(f"{op.name}: 2.5D operations require a horizontal face")
                    edges = (topo.pocket_face_edges(ref.indices[0]) if clearing
                             else topo.face_edges(ref.indices[0]))
                    if clearing and has_stock_bounds:
                        keep_edges.update(tuple(sorted(e)) for e in edges)
                else:
                    chain = topo.pocket_boundary(ref) if clearing and has_stock_bounds else topo.edge_chain(ref)
                    edges = list(zip(chain, chain[1:]))
                    if ref.kind == "edge":
                        keep_edges.update(tuple(sorted(e)) for e in edges)
                selected_edges.update(tuple(sorted(e)) for e in edges)
            polys = [cam_vertices[p] for p in chains(selected_edges)]
            flat = all(np.ptp(p[:, 2]) <= 1e-4 for p in polys)
            # Surface clearing is explicit, not a hidden Pocket mode.
            surface_mode = op.kind in SURFACE_KINDS
            if not flat and not surface_mode:
                raise ValueError(f"{op.name}: {KIND_LABELS[op.kind]} needs constant-Z edges; 3D Waterfall "
                                 "and 3D Contour accept sloped boundaries; use 3D Waterfall for surface-limited clearing")
            paths = []
            region = None
            if op.area_order not in ("area", "depth"):
                raise ValueError(f"{op.name}: unknown area order '{op.area_order}'")
            direction = direction_for(job, op)
            if op.kind in ("profile", "pocket", "drill") or surface_mode:
                if any(not np.allclose(p[0], p[-1]) for p in polys):
                    raise ValueError(f"{op.name}: select closed edges or a horizontal face")
            loops = [p[:-1, :2] for p in polys]

            def add_layer(planned, z, height, area):
                layer = Layer(len(layers), z, height, paths=planned)
                layer.cam_tool_id = tool.id
                layer.cam_group = gi
                layer.cam_operation = op.name
                layer.cam_operation_key = (gi, oi)
                layer.cam_area = area
                layer.cam_operation_config = op
                layer.cam_cutting = cutting
                layers.append(layer)

            if surface_mode:
                if model_shadow is None:
                    model_shadow = ModelShadow(job.mesh)
                _surface_operation(job, ctx, op, tool, loops, start, end, step, count, direction, tabs,
                                   material_history, model_shadow, skip_air, add_layer)
                continue
            if op.kind == "pocket":
                if not 0 < op.stepover <= 100:
                    raise ValueError("Pocket stepover must be between 0 and 100 percent")
                if op.overcut < 0 or not math.isfinite(op.overcut):
                    raise ValueError(f"{op.name}: overcut must be zero or positive")
                if not math.isfinite(op.material_limit):
                    raise ValueError(f"{op.name}: material boundary limit must be finite")
                stock_loops = [cam_vertices[p][:-1, :2] for p in chains(stock_edges)] if stock_edges else []
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
                if op.overcut > 0 or stock_edges:
                    depths = [max(end, start - (i + 1) * step) for i in range(count)] + [start]
                    depths.extend(math.ceil(float(hi[2])*1000-1e-9)/1000 for _, hi in tabs
                                  if end < hi[2] < start)
                    # No extra clearance here: the contour inset already leaves op.stock on part walls.
                    protected = part_section(job.mesh, depths, 0.0)
                if stock_edges:
                    # Material references define the exterior removal envelope, never permission
                    # to machine through the model or automatically bore its internal holes.
                    # Fill section holes conservatively; use a separate part-selected operation
                    # for those features. Part references can still supply the end Z.
                    from shapely.geometry import Polygon
                    from shapely.ops import unary_union
                    sections = [protected] if protected.geom_type == "Polygon" else list(getattr(protected, "geoms", ()))
                    protect = [Polygon(p.exterior) for p in sections if p.geom_type == "Polygon"]
                    # Selected part rims/face footprints are retained inner boundaries,
                    # not just depth hints. Honour them even above/below that model rim.
                    protect.extend(pocket_region([cam_vertices[p][:-1, :2]]) for p in chains(keep_edges))
                    protected = unary_union(protect)
                    region = (limit if limit is not None else region).difference(protected).buffer(0)
                    if region.is_empty:
                        raise ValueError(f"{op.name}: no material outside the protected part at these depths")
                    ctx.log(f"  {op.name}: material-boundary pocket; part sections protected")
                if op.overcut > 0:
                    grown = overcut_region(region, op.overcut, protected, limit)
                    ctx.log(f"  {op.name}: overcut {op.overcut:g} mm into void material adds "
                            f"{grown.area - region.area:.1f} mm² (part sections protected, "
                            f"material limit {op.material_limit:+g} mm)")
                    region = grown
                elif limit is not None and not limit.is_empty and not limit.covers(region):
                    region = region.intersection(limit).buffer(0)
                    if region.is_empty:
                        raise ValueError(f"{op.name}: material boundary limit removes the whole pocket")
                paths = _pocket_paths(op, loops, region, diameter, direction, ctx.log)
            elif op.kind == "profile":
                sign = {"outside": -1, "inside": 1, "on": 0}[op.side]
                for p, hole in zip(loops, geometry.hole_flags(loops)):
                    out = geometry.offset_into_material(p, sign * (diameter / 2 + op.stock), hole) if sign else [p]
                    for q in out:
                        inside = not hole if op.side != "inside" else hole
                        q = orient_contour(q, direction, material_inside=inside, index=len(paths))
                        paths.append(Path("cut", q, closed=True, width=diameter))
            elif op.kind in ("engrave", "slot"):
                if any(np.ptp(p[:, 2]) > 1e-4 for p in polys):
                    raise ValueError(f"{op.name}: only constant-Z engraving is supported")
                paths = [Path("cut", p[:, :2], width=diameter) for p in polys]
            else:
                for p in loops:
                    # A circular rim, not an arbitrary face centroid, defines a drill position.
                    if len(p) < 8:
                        raise ValueError(f"{op.name}: select circular hole rims (at least 8 segments)")
                    A = np.column_stack((2 * p, np.ones(len(p))))
                    x, y, c = np.linalg.lstsq(A, (p * p).sum(axis=1), rcond=None)[0]
                    radii = np.linalg.norm(p - [x, y], axis=1)
                    if np.ptp(radii) > max(0.01, radii.mean() * 0.01):
                        raise ValueError(f"{op.name}: selected rim is not circular")
                    if diameter > 2 * radii.mean() + 0.02:
                        raise ValueError(f"{op.name}: drill is larger than the selected hole")
                    paths.append(Path("drill", np.array([[x, y]]), width=diameter))
            if not paths:
                raise ValueError(f"{op.name}: no machinable paths")
            surface = setup.stock.top if setup.stock.allocated else float(job.mesh.bounds[1][2])
            if material_history is not None:
                # Current material top where this operation actually cuts: material already
                # removed by earlier operations does not consume flute length.
                current_top = material_history.top_within(PlanarStock.sweep(paths, diameter/2), surface, end)
                if current_top is not None:
                    surface = current_top
            reach = float(tool.get("length", 0) or 0)
            if reach > 0 and surface - end > reach + 1e-3:
                warning = (f"{op.name}: {surface - end:g} mm below the current material surface (Z{surface:g}) exceeds the "
                           f"tool cutting length {reach:g} mm; verify reach, shank and holder clearance.")
                if warning not in job.warnings:
                    job.warnings.append(warning)
                    ctx.log("REACH WARNING: " + warning)
            if skip_air and material_history is not None:
                # Earlier operations already removed material here: begin at the first
                # depth that still holds stock instead of air-cutting from the requested start.
                effective = material_history.top_within(PlanarStock.sweep(paths, diameter/2), start, end)
                if effective is None:
                    ctx.log(f"  {op.name}: entire depth range Z{start:g}..Z{end:g} is already removed; operation skipped")
                    continue
                if effective < start - 1e-6:
                    ctx.log(f"  {op.name}: start lowered from Z{start:g} to Z{effective:g} (material above is already removed)")
                    start = effective
                    count = max(1, math.ceil((start - end) / step))
            areas = machining_areas(paths, op.kind, region)
            # The first path of an area must enter independently: stay-down metadata
            # from the combined XY plan cannot cross an area or depth boundary.
            for area in areas:
                area[0].stay_down, area[0].stay_down_from = False, None
            if len(areas) * count > 100000:
                raise ValueError(f"{op.name}: too many area/depth passes")
            schedule = [(ai, i) for ai in range(len(areas)) for i in range(count)]
            if op.area_order == "depth":
                schedule.sort(key=lambda item: (item[1], item[0]))
            if tabs:
                schedule = _tab_schedule(areas, op, region, tabs, start, end, step, count, diameter/2, ctx.log)
            else:
                schedule = [(ai, i, None, area_paths) for ai, i in schedule for area_paths in [areas[ai]]]
            label = "each area to full depth" if op.area_order == "area" else "each depth across all areas"
            ctx.log(f"  {op.name}: {len(areas)} machining areas, {label}")
            op_layer_start = len(layers)
            cached_key, planned = None, None
            for ai, i, tab_key, area_paths in schedule:
                z = max(end, start - (i + 1) * step)
                remaining = material_history.at(z) if material_history else None
                key = (ai, tab_key, remaining.normalize().wkb if remaining is not None else b"unallocated")
                if key != cached_key:
                    planned = copy.deepcopy(area_paths)
                    if skip_air and remaining is not None and op.kind == "pocket":
                        planned = _drop_air_paths(planned, remaining, diameter/2, op.name, ctx.log)
                    cached_key = key
                    if not planned:
                        ctx.log(f"  {op.name}: depth pass Z{z:g} lies entirely in removed material; pass skipped")
                        continue
                    if op.kind != "drill":
                        from gcodeproducer.core.cam.engagement import plan_engagement
                        for warning in plan_engagement(planned, job, op, tool, ctx.log, remaining):
                            if warning not in job.warnings:job.warnings.append(warning)
                    if op.kind == "pocket" and op.strategy == "contour":
                        ctx.log(f"  {op.name}: {sum(p.stay_down for p in planned)} stay-down links, "
                                f"{sum(not p.stay_down for p in planned)} safe-height entries per depth pass")
                if not planned:
                    continue
                if material_history:material_history.remove(planned,z,diameter/2)
                add_layer(planned, z, min(step, start - z), ai)
            ctx.log(f"  {op.name}: {len(paths)} base XY paths, {len(layers)-op_layer_start} area/depth passes, Z{start:g} to Z{end:g}")
        ctx.progress((gi + 1) / max(1, len(setup.groups)))
    if not layers:
        raise ValueError("CAM setup has no enabled operations that remove material")
    job.layers = layers
    return f"{len(setup.groups)} tool groups, {len(layers)} depth passes"
