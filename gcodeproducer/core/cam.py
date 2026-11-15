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

KINDS = ("pocket", "profile", "drill", "engrave")


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
            points = np.concatenate([topology.points(ref) for ref in references])
            z = points[:, 2].min() if self.extreme == "min" else points[:, 2].max()
            return float(z) + self.value
        if self.source == "absolute":
            return self.value
        if self.source == "geometry":
            if self.reference is None:
                raise ValueError("Depth has no geometry reference")
            points = topology.points(self.reference)
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


@dataclass
class ToolGroup:
    tool_id: str
    operations: list[Operation] = field(default_factory=list)


@dataclass
class CAMSetup:
    groups: list[ToolGroup] = field(default_factory=list)
    fingerprint: str = ""
    stock: Stock = field(default_factory=Stock)

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
        return cls(groups, data.get("fingerprint", ""), Stock.from_dict(data.get("stock", {})))


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

    def polylines(self, ref):
        if ref.kind == "face":
            paths = chains(self.face_edges(ref.indices[0]))
        else:
            paths = [self.edge_chain(ref)]
        return [self.vertices[p] for p in paths]

    def points(self, ref):
        return np.concatenate(self.polylines(ref))

    def highlight(self, refs):
        faces, edges = set(), []
        for ref in refs:
            if ref.kind == "face":
                faces.update(self.face(ref.indices[0]))
            for p in self.polylines(ref):
                edges.extend(np.stack((p[:-1], p[1:]), axis=1).reshape(-1, 3))
        return {"faces": sorted(faces), "edges": np.asarray(edges).reshape(-1, 3)}


def pick_geometry(payload):
    mesh, mode, origin, direction, mvp, viewport, mouse = payload
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
    return {"reference": ref, "z_min": float(z.min()), "z_max": float(z.max())}


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
    out = topo.highlight(op.geometry)
    try:
        out["depths"] = f"Resolved Z: start {op.start.resolve(mesh, topo, op.geometry, op_stock):.3f}, end {op.end.resolve(mesh, topo, op.geometry, op_stock):.3f} mm"
    except ValueError as exc:
        out["depths"] = str(exc)
    return out


def generate(job, ctx):
    """Generate ordered 2.5D operations. Fail rather than silently machining wrong geometry."""
    from .job import Layer, Path
    from .infill_gen import scan_fill
    from .cam_paths import contour_pocket, direction_for, orient_contour, link_contours
    setup = job.cam_setup
    topo = cached_topology(job.mesh)
    tools = {t.id: t for t in job.tools}
    layers = []
    job.warnings = []
    for gi, group in enumerate(setup.groups):
        if group.tool_id not in tools:
            raise ValueError(f"CAM tool '{group.tool_id}' is missing or not allowed by the machine")
        tool = tools[group.tool_id]
        diameter = float(tool.get("diameter", 0))
        if diameter <= 0:
            raise ValueError("Tool diameter must be positive")
        for op in group.operations:
            if not op.enabled:
                continue
            if op.kind not in KINDS or not op.geometry:
                raise ValueError(f"{op.name}: select machining geometry first")
            start = op.start.resolve(job.mesh, topo, op.geometry, setup.stock)
            end = op.end.resolve(job.mesh, topo, op.geometry, setup.stock)
            if not (math.isfinite(start) and math.isfinite(end)) or end > start:
                raise ValueError(f"{op.name}: end Z must be at or below start Z")
            if op.stepdown <= 0 or not math.isfinite(op.stepdown):
                raise ValueError(f"{op.name}: stepdown must be positive")
            step = min(op.stepdown, float(tool.get("max_doc", op.stepdown) or op.stepdown))
            if step <= 0 or not math.isfinite(step):
                raise ValueError(f"{op.name}: tool depth per pass must be positive")
            count = max(1, math.ceil((start - end) / step))
            if count > 10000:
                raise ValueError(f"{op.name}: too many depth passes")
            safe = float(job.m("safe_z", 15))
            if safe <= max(float(job.mesh.bounds[1][2]), start,
                           setup.stock.top if setup.stock.allocated else -math.inf):
                raise ValueError("Safe Z must be above the model and all operation start heights")
            selected_edges = set()
            for ref in op.geometry:
                if ref.kind == "face":
                    pts = topo.vertices[topo.triangles[topo.face(ref.indices[0])]].reshape(-1, 3)
                    if np.ptp(pts[:, 2]) > 1e-4:
                        raise ValueError(f"{op.name}: 2.5D operations require a horizontal face")
                    edges = (topo.pocket_face_edges(ref.indices[0]) if op.kind == "pocket"
                             else topo.face_edges(ref.indices[0]))
                else:
                    chain = topo.edge_chain(ref)
                    edges = zip(chain, chain[1:])
                selected_edges.update(tuple(sorted(e)) for e in edges)
            polys = [topo.vertices[p] for p in chains(selected_edges)]
            if any(np.ptp(p[:, 2]) > 1e-4 for p in polys):
                raise ValueError(f"{op.name}: 2.5D operations require constant-Z edges")
            paths = []
            direction = direction_for(job, op)
            if op.kind in ("profile", "pocket", "drill"):
                if any(not np.allclose(p[0], p[-1]) for p in polys):
                    raise ValueError(f"{op.name}: select closed edges or a horizontal face")
            loops = [p[:-1, :2] for p in polys]
            if op.kind == "pocket":
                if not 0 < op.stepover <= 100:
                    raise ValueError("Pocket stepover must be between 0 and 100 percent")
                if op.strategy == "contour":
                    contours = contour_pocket(loops, diameter/2, op.stock, op.stepover, direction, ctx.log)
                    linked = link_contours(contours, loops, diameter/2, op.stock, direction, op.stay_down)
                    paths = [Path("cut", p, closed=True, width=diameter, stay_down=link,
                                  stay_down_from=tuple(linked[i-1][0][0]) if link else None)
                             for i, (p, link) in enumerate(linked)]
                elif op.strategy == "raster":
                    from .cam_paths import pocket_region, boundary_paths
                    region = pocket_region(loops).buffer(-(diameter/2+op.stock))
                    regions = [p for p, _ in boundary_paths(region, direction)]
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
            elif op.kind == "engrave":
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
            if op.kind != "drill":
                from .cam_engagement import plan_engagement
                job.warnings.extend(plan_engagement(paths, job, op, tool, ctx.log))
            if op.kind == "pocket" and op.strategy == "contour":
                ctx.log(f"  {op.name}: {sum(p.stay_down for p in paths)} stay-down links, "
                        f"{sum(not p.stay_down for p in paths)} safe-height entries per depth pass")
            for i in range(count):
                z = max(end, start - (i + 1) * step)
                layer = Layer(len(layers), z, min(step, start - z), paths=paths)
                layer.cam_tool_id = tool.id
                layer.cam_group = gi
                layer.cam_operation = op.name
                layers.append(layer)
            ctx.log(f"  {op.name}: {len(paths)} paths, {count} passes, Z{start:g} to Z{end:g}")
        ctx.progress((gi + 1) / max(1, len(setup.groups)))
    if not layers:
        raise ValueError("CAM setup has no enabled operations")
    job.layers = layers
    return f"{len(setup.groups)} tool groups, {len(layers)} depth passes"
