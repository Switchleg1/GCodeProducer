"""Topology — cam subsystem."""
from __future__ import annotations
import math, numpy as np, gcodeproducer.core.geometry.kernel as geometry

class Topology:
    """Built in the compute process, not on the GUI thread."""
    def __init__(self, mesh):
        from gcodeproducer.core.cam.planning import chains
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
        from gcodeproducer.core.cam.planning import chains
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
        from gcodeproducer.core.cam.planning import chains
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
        from gcodeproducer.core.cam.planning import chains
        if ref.kind.startswith("stock_"):
            from gcodeproducer.core.cam.stock_geometry import polylines
            return polylines(stock, ref)
        if ref.kind == "face":
            paths = chains(self.face_edges(ref.indices[0]))
        else:
            paths = [self.edge_chain(ref)]
        return [self.vertices[p] for p in paths]

    def points(self, ref, stock=None):
        return np.concatenate(self.polylines(ref, stock))

    def highlight(self, refs, stock=None):
        faces, edges, material_faces, part_edges, material_edges = set(), [], [], [], []
        for ref in refs:
            if ref.kind == "face":
                faces.update(self.face(ref.indices[0]))
            for p in self.polylines(ref, stock):
                segments = np.stack((p[:-1], p[1:]), axis=1).reshape(-1, 3)
                edges.extend(segments)
                (material_edges if ref.kind.startswith("stock_") else part_edges).extend(segments)
                if ref.kind == "stock_face":
                    material_faces.extend(p[[0,1,2,0,2,3]])
        return {"faces": sorted(faces), "edges": np.asarray(edges).reshape(-1, 3),
                "stock_faces": np.asarray(material_faces).reshape(-1, 3),
                "part_edges": np.asarray(part_edges).reshape(-1, 3),
                "stock_edges": np.asarray(material_edges).reshape(-1, 3)}
