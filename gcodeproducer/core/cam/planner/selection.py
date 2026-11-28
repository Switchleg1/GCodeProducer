"""Selection — an operation's picked geometry resolved to closed/open XY(Z) polylines."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Selection:
    polys: list                         # (n,3) vertex polylines, closed ones repeat their first point
    cam_vertices: np.ndarray            # mesh + stock + drawn vertices addressed by the edge sets
    stock_edges: set = field(default_factory=set)
    keep_edges: set = field(default_factory=set)

    @property
    def loops(self):
        return [p[:-1, :2] for p in self.polys]

    @property
    def flat(self):
        return all(np.ptp(p[:, 2]) <= 1e-4 for p in self.polys)

    @property
    def closed(self):
        return all(np.allclose(p[0], p[-1]) for p in self.polys)

    @classmethod
    def resolve(cls, op, topo, setup, clearing):
        """Edges of every picked face/edge/material/drawn reference, chained into polylines.

        ``clearing`` operations (Pocket, 3D Pocket) treat a face as its pocket
        boundary and one horizontal material edge as the whole blank rim.
        """
        from gcodeproducer.core.cam.planning import chains
        selected_edges, stock_edges, keep_edges = set(), set(), set()
        cam_vertices = topo.vertices
        has_stock_bounds = any(ref.kind.startswith("stock_") for ref in op.geometry)
        if has_stock_bounds:
            from gcodeproducer.core.cam.stock_geometry import vertices as stock_vertices
            cam_vertices = np.vstack((topo.vertices, stock_vertices(setup.stock)))
        for ref in op.geometry:
            if ref.kind == "drawing":
                points = topo.polylines(ref, setup.stock)[0][:-1]
                ids = list(range(len(cam_vertices), len(cam_vertices)+len(points)))
                cam_vertices = np.vstack((cam_vertices, points))
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
                        raise ValueError(f"{op.name}: 2.5D operations require a horizontal material face; "
                                         "use side faces as height references")
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
        return cls(polys, cam_vertices, stock_edges, keep_edges)

    def edge_loops(self, edges):
        from gcodeproducer.core.cam.planning import chains
        return [self.cam_vertices[p][:-1, :2] for p in chains(edges)]
