"""Per-layer planning for the FDM output stage, so layers can be planned in parallel.

Writing G-code is sequential (the head, extruder and fan carry over from one
layer to the next), but almost all of its cost is not: the print order, path
simplification, seam choice and the travel routes between paths depend only on
the layer itself once its first path is known. :func:`plan_layer` does that
work for one layer, in a worker process; the output stage then only routes the
first travel of each layer from wherever the previous layer really ended and
writes the lines.

The planner assumes the layer starts at ``head``: first an estimate (the seam
target for a fixed seam, else where the generated order begins), then, where
that guess was poor, the end of the previous layer's plan (see
:func:`plan_layers`). Only the first travel of a layer can differ from a fully
sequential plan.
"""
from __future__ import annotations

import math
from functools import partial

import numpy as np

from gcodeproducer.core.fdm.fdm_constants import EMIT_REPLAN_DISTANCE, EMIT_REPLAN_PASSES, WALL_FEATURES
from gcodeproducer.core.fdm.layer_order import order_layer
from gcodeproducer.core.fdm.layer_threads import layer_map
from gcodeproducer.core.fdm.path_order import closed_loop, ordered_paths
from gcodeproducer.core.fdm.travel_router import TravelRouter
from gcodeproducer.core.fdm.wall_regions import slice_region
from gcodeproducer.core.geometry.decimate import decimate
from gcodeproducer.core.geometry.polygon_parts import polygons


def orient_path(pts, closed, feature, widths, head, seam, target):
    """Points in print order (closed loops repeat their start) and matching widths or None."""
    head = np.asarray(head, float)
    if closed:
        if feature in WALL_FEATURES and seam != "origin":
            aim = np.asarray(target, float) if seam == "xy" else head
            if widths is None:
                pts = closed_loop(pts, aim)
            else:
                pts, widths = closed_loop(pts, aim, widths)
        elif seam != "origin":
            # Do not aim skirt or support seams at the perimeter XY target.
            s = int(np.argmin(((pts - head)**2).sum(axis=1)))
            pts = np.roll(pts, -s, axis=0)
            if widths is not None:
                widths = np.roll(widths, -s)
        loop = np.vstack([pts, pts[0]])
        if widths is not None:
            widths = np.append(widths, widths[0])
        return loop, widths
    loop = pts
    # start from the closer end
    if ((loop[-1] - head)**2).sum() < ((loop[0] - head)**2).sum():
        loop = loop[::-1]
        if widths is not None:
            widths = widths[::-1]
    return loop, widths


def travel_to(head, start, router, detour, cfg):
    """Travel waypoints from ``head`` to ``start`` and whether to retract for it."""
    route = router.route(head, start, detour) if router is not None else [start]
    dist = sum(math.dist(a, q) for a, q in zip([head, *route], route))
    mode = cfg["retraction_mode"]
    retract = False
    if mode != "off" and cfg["retract_length"] > 0 and dist > 1e-9:
        inside = mode in ("open", "separate") and router is not None and not router.crosses_open(head, route)
        if inside:
            retract = mode == "separate" and dist >= cfg["inside_travel_retract"]
        else:
            retract = dist >= cfg["min_travel_retract"]
    return route, retract


def make_router(outline, cfg):
    if not cfg["route_or_classify"]:
        return None
    return TravelRouter(outline, cfg["decimals"], simplification=cfg["simplification"])


def plan_layer(cfg, data):
    """Plan one layer: ``{"steps": [(path index, points, widths, route, retract)], "stats": (...)}``.

    ``data`` is ``(paths, outline, head)``. The first step's route and retract
    are None: the output stage routes it from the real head position.
    """
    paths, outline, head = data
    head = np.asarray(head, float)
    router = make_router(outline, cfg)
    target = (cfg["seam_x"], cfg["seam_y"])
    if cfg["travel_order"]:
        islands = router.islands if router is not None else list(polygons(slice_region(outline)))
        ordered = order_layer(paths, head, islands, cfg["seam"], target, cfg["mixed"])
    elif cfg["mixed"]:
        position = [head]
        ordered = []
        for path in ordered_paths(paths, lambda: tuple(position[0])):
            ordered.append(path)
            pts = np.asarray(path.points, float)
            position[0] = pts[0, :2] if path.closed else pts[-1, :2]
    else:
        ordered = list(paths)
    index = {id(p): i for i, p in enumerate(paths)}
    steps = []
    first = True
    for path in ordered:
        pts, widths = decimate(np.asarray(path.points, float), path.closed, cfg["min_segment"],
                               cfg["deviation"], path.widths)
        if len(pts) < 2:
            continue
        widths = None if widths is None else np.asarray(widths, float)
        loop, widths = orient_path(pts, path.closed, path.feature, widths, head, cfg["seam"], target)
        if first:
            route = retract = None
            first = False
        else:
            route, retract = travel_to(head, loop[0], router, cfg["detour"], cfg)
        steps.append((index[id(path)], loop, widths, route, retract))
        head = loop[-1]
    stats = (0, 0, 0, 0) if router is None else (router.detours, router.fallbacks, router.outside, router.bridges)
    start = steps[0][1][0] if steps else None
    return {"steps": steps, "stats": stats, "start": start, "end": head if steps else None,
            "head": np.asarray(data[2], float)}


def plan_layers(layers, cfg, target):
    """Plans of all layers, in order.

    First every layer is planned in parallel from an estimated start. A layer
    planned from a start far from where the previous layer's plan ends is
    planned again from that end, also in parallel; a few such passes settle
    every layer on its predecessor's real end.
    """
    first = list(layer_map(partial(plan_layer, cfg),
                           [(layer.paths, layer.outline, start_estimate(layer.paths, cfg["seam"], target))
                            for layer in layers]))
    for _ in range(EMIT_REPLAN_PASSES):
        redo, heads = [], []
        end = None
        for i, plan in enumerate(first):
            if end is not None and plan["start"] is not None and                     math.dist(end, plan["head"]) > EMIT_REPLAN_DISTANCE:
                redo.append(i)
                heads.append(end)
            if plan["end"] is not None:
                end = plan["end"]
        if not redo:
            break
        again = layer_map(partial(plan_layer, cfg),
                          [(layers[i].paths, layers[i].outline, head) for i, head in zip(redo, heads)])
        for i, plan in zip(redo, again):
            first[i] = plan
    return first


def start_estimate(paths, seam, target):
    """Where a layer is assumed to start before the previous one is written."""
    if seam == "xy":
        return np.asarray(target, float)
    for path in paths:
        return np.asarray(path.points, float)[0, :2]
    return np.zeros(2)
