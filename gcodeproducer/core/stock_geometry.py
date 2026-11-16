"""Stable references to the six faces / twelve edges of the original allocated blank.

Ids describe box corners/faces, not copied coordinates or triangles of the
part. Resizing/repositioning the material therefore re-evaluates references.
"""
import numpy as np

EDGES = ((0,1),(1,3),(3,2),(2,0),(4,5),(5,7),(7,6),(6,4),(0,4),(1,5),(2,6),(3,7))
FACES = ((0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3))
FACE_NAMES = ("bottom", "top", "Y minimum", "Y maximum", "X minimum", "X maximum")


def vertices(stock):
    if stock is None or not stock.allocated:
        raise ValueError("Allocate material before selecting its boundaries")
    lo, hi = stock.bounds
    return np.array([[x,y,z] for z in (lo[2],hi[2]) for y in (lo[1],hi[1]) for x in (lo[0],hi[0])])


def indices(ref):
    table = FACES if ref.kind == "stock_face" else EDGES if ref.kind == "stock_edge" else ()
    if len(ref.indices) != 1 or not isinstance(ref.indices[0], (int, np.integer)) or not 0 <= ref.indices[0] < len(table):
        raise ValueError("Invalid material boundary reference; reselect it")
    return table[ref.indices[0]]


def polylines(stock, ref):
    p = vertices(stock)[list(indices(ref))]
    return [np.vstack((p,p[0])) if ref.kind == "stock_face" else p]


def pick(stock, mode, origin, direction, mvp, viewport, mouse):
    from .cam import Reference
    from .geometry import ray_triangles
    try:
        v = vertices(stock)
    except ValueError as exc:
        return {"error": str(exc)}
    ref = None
    if mode == "stock_face":
        triangles = np.array([v[list(t)] for f in FACES for t in ((f[0],f[1],f[2]),(f[0],f[2],f[3]))])
        _, tri = ray_triangles(origin, direction, triangles)
        if tri >= 0:ref = Reference("stock_face", [int(tri)//2])
    else:
        # The blank is transparent; use all projected edges, never the part's
        # depth buffer. Explicit Part/Material targeting avoids intercepting part picks.
        clip = np.column_stack((v,np.ones(8))) @ np.asarray(mvp).T
        ndc = clip[:,:3]/np.where(abs(clip[:,3:4]) > 1e-12, clip[:,3:4], 1e-12)
        screen = (ndc[:,:2]*[1,-1]+1)*np.asarray(viewport)/2
        best, best_depth = 10., float("inf")
        for i,(a,b) in enumerate(EDGES):
            if clip[a,3] <= 0 or clip[b,3] <= 0:continue
            d = screen[b]-screen[a]
            u = np.clip(np.dot(np.asarray(mouse)-screen[a],d)/max(d@d,1e-12),0,1)
            distance = np.linalg.norm(np.asarray(mouse)-(screen[a]+u*d))
            depth = ndc[a,2]+u*(ndc[b,2]-ndc[a,2])
            if distance < best-1e-5 or (abs(distance-best) <= 1e-5 and depth < best_depth):
                ref, best, best_depth = Reference("stock_edge",[i]), distance, depth
    if ref is None:return None
    z = polylines(stock,ref)[0][:,2]
    result = {"reference": ref, "z_min": float(z.min()), "z_max": float(z.max())}
    if mode == "stock_edge":result["pick_distance"] = float(best)
    return result
