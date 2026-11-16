"""Model-specific, ordered CAM setup. Geometry references survive placement changes.

STL has no CAD topology. Connected coplanar triangles form faces; feature
edges omit triangle seams. References use original triangle/vertex indices,
never copied world coordinates. Re-evaluate them against the placed mesh.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import math

import numpy as np

from . import geometry
from .stock import Stock
from .cam_tabs import HoldingTab

KINDS = ("pocket", "profile", "drill", "engrave", "slot")


@dataclass
class Reference:
    kind: str
    indices: list


@dataclass
class Depth:
    source: str = "top"  # top, bottom, absolute, geometry
    value: float = 0.0   # absolute Z, or offset from source
    reference: Reference | None = None
    extreme: str = "max"

    def resolve(self, mesh, topology, references=(), stock=None):
        if self.source == "stock_top":
            return float(stock.top if stock is not None and stock.allocated else mesh.bounds[1][2]) + self.value
        if self.source == "selection":
            if not references:
                raise ValueError("Select pocket bounds to resolve machining depth")
            points = np.concatenate([topology.points(ref, stock) for ref in references])
            z = points[:, 2].min() if self.extreme == "min" else points[:, 2].max()
            return float(z) + self.value
        if self.source == "absolute":
            return self.value
        if self.source == "geometry":
            if self.reference is None:
                raise ValueError("Depth has no geometry reference")
            points = topology.points(self.reference, stock)
            z = points[:, 2].min() if self.extreme == "min" else points[:, 2].max()
        else:
            z = mesh.bounds[0 if self.source == "bottom" else 1][2]
        return float(z) + self.value


@dataclass
class Operation:
    name: str = "Profile"
    kind: str = "profile"
    geometry: list[Reference] = field(default_factory=list)
    start: Depth = field(default_factory=Depth)
    end: Depth = field(default_factory=lambda: Depth("bottom"))
    stepdown: float = 1.0
    stepover: float = 40.0
    side: str = "outside"
    stock: float = 0.0
    enabled: bool = True
    strategy: str = "contour"          # pocket: contour-parallel or legacy raster
    cut_direction: str = "machine"     # inherit machine default, climb/conventional/meander
    stay_down: bool = True             # pocket contours: region-validated same-depth feed links
    low_engagement_feed: float = 0.0   # percent of tool feed; 0 = inherit tool defaults
    standard_engagement_feed: float = 0.0
    high_engagement_feed: float = 0.0
    slotting_feed: float = 0.0
    auto_stepdown: bool = False         # new GUI operations use per-material axial defaults
    unlock_rpm: bool = False
    rpm: float = 18000.
    unlock_feed: bool = False
    feed: float = 800.
    unlock_lead_feed: bool = False
    lead_feed: float = 300.
    lead_in: bool = True
    lead_out: bool = True
    lead_length: float = 0.0            # 0 = auto: >= one diameter, with <=10-degree ramp
    overcut: float = 0.0                # pocket: grow the floor region into void material (never the part)
    material_limit: float = 0.0         # cutter edge vs blank edge: 0 touch, <0 leave material, >0 pass beyond
    area_order: str = "area"           # area: each area to full depth; depth: all areas at each depth


@dataclass
class ToolGroup:
    tool_id: str
    operations: list[Operation] = field(default_factory=list)


@dataclass
class CAMSetup:
    groups: list[ToolGroup] = field(default_factory=list)
    fingerprint: str = ""
    stock: Stock = field(default_factory=Stock)
    tabs: list[HoldingTab] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        def depth(d):
            d = dict(d)
            if d.get("reference"):
                d["reference"] = Reference(**d["reference"])
            return Depth(**d)
        groups = []
        for g in data.get("groups", []):
            ops = []
            for item in g.get("operations", []):
                d = dict(item)
                d["geometry"] = [Reference(**r) for r in d.get("geometry", [])]
                d["start"], d["end"] = depth(d["start"]), depth(d["end"])
                ops.append(Operation(**d))
            groups.append(ToolGroup(g["tool_id"], ops))
        return cls(groups, data.get("fingerprint", ""), Stock.from_dict(data.get("stock", {})),
                   [HoldingTab(**t) for t in data.get("tabs", [])])


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


class Topology:
    """Built in the compute process, not on the GUI thread."""
    def __init__(self, mesh):
        self.mesh = mesh
        self.triangles = np.asarray(mesh.triangles)
        self.vertices = np.asarray(mesh.vertices)
        t = self.vertices[self.triangles]
        normals = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        normals /= np.maximum(np.linalg.norm(normals, axis=1)[:, None], 1e-20)
        self.adj = [[] for _ in self.triangles]
        edges = {}
        for ti, tri in enumerate(self.triangles):
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                edges.setdefault(tuple(sorted((int(a), int(b)))), []).append(ti)
        self.edges = edges
        feature = []
        for edge, faces in edges.items():
            if len(faces) == 2:
                a, b = faces
                dot = float(normals[a] @ normals[b])
                if dot > 1 - 1e-8:
                    self.adj[a].append(b)
                    self.adj[b].append(a)
                if dot < math.cos(math.radians(30)):
                    feature.append(edge)
            else:
                feature.append(edge)
        self.feature_chains = chains(feature)

    def face(self, seed):
        if not 0 <= seed < len(self.triangles):
            raise ValueError("Face reference no longer exists; reselect geometry")
        seen, todo = {seed}, [seed]
        while todo:
            for f in self.adj[todo.pop()]:
                if f not in seen:
                    seen.add(f)
                    todo.append(f)
        return sorted(seen)

    def face_edges(self, seed):
        faces = set(self.face(seed))
        return [e for e, fs in self.edges.items() if sum(f in faces for f in fs) == 1]

    def pocket_face_edges(self, seed):
        """Floor bounds: retain raised islands, not holes descending below the floor."""
        boundary = self.face_edges(seed)
        polygons = chains(boundary)
        z = float(self.vertices[self.triangles[self.face(seed)]][:, :, 2].mean())
        holes = geometry.hole_flags([self.vertices[p[:-1], :2] for p in polygons])
        kept = []
        for path, hole in zip(polygons, holes):
            edges = [tuple(sorted((a, b))) for a, b in zip(path, path[1:])]
            raised = any(self.vertices[self.triangles[f], 2].max() > z + 1e-4
                         for e in edges for f in self.edges[e])
            if not hole or raised:
                kept.extend(edges)
        return kept

    def edge_chain(self, ref):
        edge = tuple(sorted(ref.indices))
        for chain in self.feature_chains:
            if any(tuple(sorted((a, b))) == edge for a, b in zip(chain, chain[1:])):
                return chain
        raise ValueError("Edge reference no longer exists; reselect geometry")

    def pocket_boundary(self, ref):
        """In a mixed material/part pocket, one edge can identify a complete
        horizontal rim. Circular feature chains already do; at a rectangular
        corner use the adjacent planar face's boundary containing this edge.
        """
        chain = self.edge_chain(ref)
        if chain[0] == chain[-1]:
            return chain
        edge = tuple(sorted(ref.indices))
        for seed in self.edges.get(edge, []):
            if np.ptp(self.vertices[self.triangles[seed], 2]) > 1e-4:
                continue
            for rim in chains(self.face_edges(seed)):
                if rim[0] == rim[-1] and any(tuple(sorted((a,b))) == edge for a,b in zip(rim,rim[1:])):
                    return rim
        return chain

    def polylines(self, ref, stock=None):
        if ref.kind.startswith("stock_"):
            from .stock_geometry import polylines
            return polylines(stock, ref)
        if ref.kind == "face":
            paths = chains(self.face_edges(ref.indices[0]))
        else:
            paths = [self.edge_chain(ref)]
        return [self.vertices[p] for p in paths]

    def points(self, ref, stock=None):
        return np.concatenate(self.polylines(ref, stock))

    def highlight(self, refs, stock=None):
        faces, edges, material_faces = set(), [], []
        for ref in refs:
            if ref.kind == "face":
                faces.update(self.face(ref.indices[0]))
            for p in self.polylines(ref, stock):
                edges.extend(np.stack((p[:-1], p[1:]), axis=1).reshape(-1, 3))
                if ref.kind == "stock_face":
                    material_faces.extend(p[[0,1,2,0,2,3]])
        return {"faces": sorted(faces), "edges": np.asarray(edges).reshape(-1, 3),
                "stock_faces": np.asarray(material_faces).reshape(-1, 3)}


def pick_geometry(payload):
    mesh, mode, origin, direction, mvp, viewport, mouse, *stocks = payload
    if mode.startswith("mixed_"):
        base = mode.removeprefix("mixed_")
        part = pick_geometry((mesh, base, origin, direction, mvp, viewport, mouse))
        from .stock_geometry import pick
        material = pick(stocks[0] if stocks else None, "stock_"+base, origin, direction, mvp, viewport, mouse)
        if not material or "reference" not in material:
            return part
        if part is None:
            return material
        # Faces prefer the visible part over the transparent blank. For edges,
        # choose the closest pixel candidate across BOTH geometries (part wins ties).
        if base == "edge" and material["pick_distance"] < part["pick_distance"]-1e-5:
            return material
        return part
    if mode.startswith("stock_"):
        from .stock_geometry import pick
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


def cached_topology(mesh):
    global _cached
    key = fingerprint(mesh)
    if key != _cached[0]:
        _cached = (key, Topology(mesh))
    return _cached[1]


def highlight_geometry(payload):
    mesh, op, *stocks = payload
    op_stock = stocks[0] if stocks else None
    topo = cached_topology(mesh)
    try:
        out = topo.highlight(op.geometry, op_stock) if op is not None else {"faces": [], "edges": np.empty((0, 3)), "depths": ""}
    except ValueError as exc:
        out = {"faces": [], "edges": np.empty((0, 3)), "depths": str(exc), "geometry_error": str(exc)}
    out["tabs"] = []
    if len(stocks) > 2 and stocks[2]:
        from .cam_tabs import resolve_bounds
        try:
            out["tabs"] = resolve_bounds(mesh, op_stock, stocks[2])
        except ValueError as exc:
            out["tab_error"] = str(exc)
    if op is None or out.get("geometry_error"):
        return out
    if len(stocks) > 1 and stocks[1]:
        from .cam_cutting import resolve_cutting
        context = stocks[1]
        try:
            data = resolve_cutting(context["machine"],context["tool"],op_stock,op)
            out["cutting_values"] = asdict(data)
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
    from shapely.geometry import LineString, Point
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
    from .cam_tabs import mask_at, clip_paths
    from .cam_paths import machining_areas
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


def generate(job, ctx):
    """Generate ordered 2.5D operations. Fail rather than silently machining wrong geometry."""
    from .job import Layer, Path
    from .infill_gen import scan_fill
    from .cam_paths import (contour_pocket, direction_for, orient_contour, link_contours,
                            pocket_region, part_section, overcut_region, machining_areas)
    from .app_settings import pref
    from shapely.geometry import box as shapely_box
    from shapely import BufferJoinStyle
    skip_air = bool(pref(job, "skip_air_cuts"))
    setup = job.cam_setup
    topo = cached_topology(job.mesh)
    tools = {t.id: t for t in job.tools}
    import copy
    from .cam_material import PlanarStock
    material_history = PlanarStock(setup.stock) if setup.stock.allocated else None
    from .cam_tabs import resolve_tabs
    tabs = resolve_tabs(job.mesh, setup)
    if tabs:
        ctx.log(f"  {len(tabs)} holding tabs protected across all operations")
    layers = []
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
            if (op.kind == "pocket" and op.start.source == "selection" and math.isfinite(start)
                    and math.isfinite(end) and start <= end + 1e-6):
                # A single flat floor selection has no higher edge: begin at the material
                # surface (air-cut removal then drops to the current material top).
                start = Depth("stock_top", op.start.value).resolve(job.mesh, topo, op.geometry, setup.stock)
                ctx.log(f"  {op.name}: flat selection; start taken from the material surface Z{start:g}")
            if not (math.isfinite(start) and math.isfinite(end)) or end > start:
                raise ValueError(f"{op.name}: end Z must be at or below start Z")
            if not op.auto_stepdown and (op.stepdown <= 0 or not math.isfinite(op.stepdown)):
                raise ValueError(f"{op.name}: stepdown must be positive")
            from .cam_cutting import resolve_cutting
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
            selected_edges, stock_edges, keep_edges = set(), set(), set()
            cam_vertices = topo.vertices
            has_stock_bounds = any(ref.kind.startswith("stock_") for ref in op.geometry)
            if has_stock_bounds:
                from .stock_geometry import vertices as stock_vertices
                cam_vertices = np.vstack((topo.vertices, stock_vertices(setup.stock)))
            for ref in op.geometry:
                if ref.kind.startswith("stock_"):
                    from .stock_geometry import indices as stock_indices, FACES
                    local_ids = stock_indices(ref)
                    if ref.kind == "stock_edge" and op.kind == "pocket":
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
                    edges = (topo.pocket_face_edges(ref.indices[0]) if op.kind == "pocket"
                             else topo.face_edges(ref.indices[0]))
                    if op.kind == "pocket" and has_stock_bounds:
                        keep_edges.update(tuple(sorted(e)) for e in edges)
                else:
                    chain = topo.pocket_boundary(ref) if op.kind == "pocket" and has_stock_bounds else topo.edge_chain(ref)
                    edges = list(zip(chain, chain[1:]))
                    if ref.kind == "edge":
                        keep_edges.update(tuple(sorted(e)) for e in edges)
                selected_edges.update(tuple(sorted(e)) for e in edges)
            polys = [cam_vertices[p] for p in chains(selected_edges)]
            if any(np.ptp(p[:, 2]) > 1e-4 for p in polys):
                raise ValueError(f"{op.name}: 2.5D operations require constant-Z edges")
            paths = []
            region = None
            if op.area_order not in ("area", "depth"):
                raise ValueError(f"{op.name}: unknown area order '{op.area_order}'")
            direction = direction_for(job, op)
            if op.kind in ("profile", "pocket", "drill"):
                if any(not np.allclose(p[0], p[-1]) for p in polys):
                    raise ValueError(f"{op.name}: select closed edges or a horizontal face")
            loops = [p[:-1, :2] for p in polys]
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
                if op.strategy == "contour":
                    contours = contour_pocket(loops, diameter/2, op.stock, op.stepover, direction, ctx.log, region=region)
                    linked = link_contours(contours, loops, diameter/2, op.stock, direction, op.stay_down, region=region)
                    paths = [Path("cut", p, closed=True, width=diameter, stay_down=link,
                                  stay_down_from=tuple(linked[i-1][0][0]) if link else None)
                             for i, (p, link) in enumerate(linked)]
                elif op.strategy == "raster":
                    from .cam_paths import boundary_paths
                    centre_region = region.buffer(-(diameter/2+op.stock))
                    regions = [p for p, _ in boundary_paths(centre_region, direction)]
                    if not regions:
                        raise ValueError(f"{op.name}: pocket is too small for this tool")
                    for a, b in scan_fill(regions, 0, diameter * op.stepover / 100, 0, 0, 0.01):
                        pts = np.array([a, b])
                        if direction == "conventional" or (direction == "meander" and len(paths) % 2):
                            pts = pts[::-1]
                        paths.append(Path("cut", pts, width=diameter))
                    paths.extend(Path("cut", p, closed=True, width=diameter) for p in regions)
                else:
                    raise ValueError(f"Unknown pocket strategy '{op.strategy}'")
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
                        from .cam_engagement import plan_engagement
                        for warning in plan_engagement(planned, job, op, tool, ctx.log, remaining):
                            if warning not in job.warnings:job.warnings.append(warning)
                    if op.kind == "pocket" and op.strategy == "contour":
                        ctx.log(f"  {op.name}: {sum(p.stay_down for p in planned)} stay-down links, "
                                f"{sum(not p.stay_down for p in planned)} safe-height entries per depth pass")
                if not planned:
                    continue
                if material_history:material_history.remove(planned,z,diameter/2)
                layer = Layer(len(layers), z, min(step, start - z), paths=planned)
                layer.cam_tool_id = tool.id
                layer.cam_group = gi
                layer.cam_operation = op.name
                layer.cam_operation_key = (gi, oi)
                layer.cam_area = ai
                layer.cam_operation_config = op
                layer.cam_cutting = cutting
                layers.append(layer)
            ctx.log(f"  {op.name}: {len(paths)} base XY paths, {len(layers)-op_layer_start} area/depth passes, Z{start:g} to Z{end:g}")
        ctx.progress((gi + 1) / max(1, len(setup.groups)))
    if not layers:
        raise ValueError("CAM setup has no enabled operations that remove material")
    job.layers = layers
    return f"{len(setup.groups)} tool groups, {len(layers)} depth passes"
