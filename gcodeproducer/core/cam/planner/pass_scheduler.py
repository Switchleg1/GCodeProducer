"""Shared pass scheduling for planar operations.

After an operation generator has produced its base XY paths, every planar
operation is scheduled the same way: reach check against current material,
air-depth skipping, machining areas, area/depth order, holding-tab bands,
air-path removal, engagement planning on the planar sampler and the
planar-history update.
"""
from __future__ import annotations
import copy
import math
import numpy as np


def drop_air_paths(paths, remaining, radius, name, log=None):
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



def tab_schedule(areas, op, region, tabs, start, end, step, count, radius, log=None):
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


def schedule_planar(run, paths, region, planning):
    """Turn an operation's base XY paths into area/depth layers (shared by all planar kinds)."""
    from gcodeproducer.core.cam.planar_stock import PlanarStock
    from gcodeproducer.core.cam.paths import machining_areas
    from gcodeproducer.core.cam.engagement import plan_engagement
    op, material, ctx = run.op, planning.material, planning.ctx
    start, end, step, count = run.start, run.end, run.step, run.count
    diameter = run.diameter
    if not paths:
        raise ValueError(f"{op.name}: no machinable paths")
    setup = planning.setup
    surface = setup.stock.top if setup.stock.allocated else float(planning.job.mesh.bounds[1][2])
    if material.allocated:
        # Current material top where this operation actually cuts: material already
        # removed by earlier operations does not consume flute length.
        current_top = material.top_within(PlanarStock.sweep(paths, diameter/2), surface, end)
        if current_top is not None:
            surface = current_top
    planning.reach(run, surface)
    if planning.skip_air and material.allocated:
        # Earlier operations already removed material here: begin at the first
        # depth that still holds stock instead of air-cutting from the requested start.
        effective = material.top_within(PlanarStock.sweep(paths, diameter/2), start, end)
        if effective is None:
            ctx.log(f"  {op.name}: entire depth range Z{start:g}..Z{end:g} is already removed; operation skipped")
            return
        if effective < start - 1e-6:
            ctx.log(f"  {op.name}: start lowered from Z{start:g} to Z{effective:g} (material above is already removed)")
            start = run.start = effective
            count = run.count = max(1, math.ceil((start - end) / step))
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
    tabs = planning.tabs
    if tabs:
        schedule = tab_schedule(areas, op, region, tabs, start, end, step, count, diameter/2, ctx.log)
    else:
        schedule = [(ai, i, None, area_paths) for ai, i in schedule for area_paths in [areas[ai]]]
    label = "each area to full depth" if op.area_order == "area" else "each depth across all areas"
    ctx.log(f"  {op.name}: {len(areas)} machining areas, {label}")
    first_layer = len(planning.layers)
    cached_key, planned = None, None
    for ai, i, tab_key, area_paths in schedule:
        z = max(end, start - (i + 1) * step)
        remaining = material.planar_at(z)
        key = (ai, tab_key, remaining.normalize().wkb if remaining is not None else b"unallocated")
        if key != cached_key:
            planned = copy.deepcopy(area_paths)
            if planning.skip_air and remaining is not None and op.kind == "pocket":
                planned = drop_air_paths(planned, remaining, diameter/2, op.name, ctx.log)
            cached_key = key
            if not planned:
                ctx.log(f"  {op.name}: depth pass Z{z:g} lies entirely in removed material; pass skipped")
                continue
            if op.kind != "drill":
                planning.add_warnings(plan_engagement(planned, planning.job, op, run.tool, ctx.log, remaining))
            if op.kind == "pocket" and op.strategy in ("contour", "trochoidal"):
                ctx.log(f"  {op.name}: {sum(p.stay_down for p in planned)} stay-down links, "
                        f"{sum(not p.stay_down for p in planned)} safe-height entries per depth pass")
        if not planned:
            continue
        material.remove_planar(planned, z, diameter/2)
        run.add_layer(planning, planned, z, min(step, start - z), ai)
    ctx.log(f"  {op.name}: {len(paths)} base XY paths, {len(planning.layers)-first_layer} area/depth passes, "
            f"Z{start:g} to Z{end:g}")
