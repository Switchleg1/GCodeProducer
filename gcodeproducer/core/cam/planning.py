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
from gcodeproducer.core.cam.cam_constants import KINDS, KIND_LABELS, SURFACE_KINDS
from dataclasses import asdict
import hashlib
import numpy as np
import gcodeproducer.core.geometry.kernel as geometry


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
        focus_group = next((s.group for s in shapes if s.id == focus), None)
        focused = [s for s in shapes if s.id == focus or (focus_group and s.group == focus_group)]
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
            from gcodeproducer.core.cam.value_overrides import operation_overrides
            out["overrides"] = operation_overrides(context["machine"], context["tool"], op_stock, op)
        except ValueError as exc:
            out["cutting"] = str(exc)
    try:
        start, end = op.start.resolve(mesh, topo, op.geometry, op_stock), op.end.resolve(mesh, topo, op.geometry, op_stock)
        out["depths"] = f"Resolved Z: start {start:.3f}, end {end:.3f} mm"
        if len(stocks) > 1 and stocks[1]:
            from gcodeproducer.core.cam.tool_reach import reach_problems
            top = op_stock.top if op_stock is not None and op_stock.allocated else float(mesh.bounds[1][2])
            # Before slicing: the flute check against the top too (earlier cuts are not known yet).
            too_long, too_deep = reach_problems(stocks[1]["tool"], op.name, max(top, start)-end, max(top, start)-end,
                                                stocks[1]["machine"])
            problem = " ".join(m for m in (too_deep, too_long) if m)
            if problem:
                out.setdefault("overrides", {})["end"] = problem
    except ValueError as exc:
        out["depths"] = str(exc)
    return out


# Compatibility exports: the implementations live in the CAM planner and the
# per-kind operation generators (core/cam/planner/, core/cam/operations/).
# Imported lazily: the planner depends on job records that import this package.
def _drop_air_paths(*args, **kwargs):
    from gcodeproducer.core.cam.planner.pass_scheduler import drop_air_paths
    return drop_air_paths(*args, **kwargs)


def _tab_schedule(*args, **kwargs):
    from gcodeproducer.core.cam.planner.pass_scheduler import tab_schedule
    return tab_schedule(*args, **kwargs)


def _pocket_paths(*args, **kwargs):
    from gcodeproducer.core.cam.operations.pocket_generator import pocket_paths
    return pocket_paths(*args, **kwargs)


def generate(job, ctx):
    """Generate the ordered CAM passes (job.layers) for the job's CAM setup.

    Compatibility entry point: runs the planner's :class:`Sequencer`, which
    calls one generator module per operation kind. Fail rather than silently
    machining wrong geometry.
    """
    from gcodeproducer.core.cam.planner.sequencer import Sequencer
    return Sequencer().run(job, ctx)
