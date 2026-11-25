"""Section mesh for the hybrid flat-cutter preview (display only)."""
import numpy as np
from shapely import constrained_delaunay_triangles, get_parts, get_coordinates
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.geometry.polygon import orient


def surface(stock, levels, tolerance, tabs=()):
    """Terrace slopes at the supplied section depths. Preserve sub-cell XY outlines."""
    levels = sorted({stock.top, stock.bottom, *(z for z in levels if stock.bottom < z < stock.top),
                     *(hi[2] for _,hi in tabs if stock.bottom < hi[2] < stock.top)}, reverse=True)
    previous = Polygon()
    chunks = []
    for z, base in zip(levels,levels[1:]):
        # Material whose height is exactly z is part of this terrace.
        region = stock.remaining(np.nextafter(z,-np.inf),tolerance)
        protected = [box(*lo[:2],*hi[:2]).intersection(stock.blank) for lo,hi in tabs if hi[2]>=z]
        if protected: region = unary_union([region,*protected])
        exposed = region.difference(previous)
        triangles = get_parts(constrained_delaunay_triangles(exposed))
        if len(triangles):
            xy = get_coordinates(triangles).reshape(-1,4,2)[:,:3,:].copy()
            a,b = xy[:,1]-xy[:,0], xy[:,2]-xy[:,0]
            flip = a[:,0]*b[:,1]<a[:,1]*b[:,0]
            xy[flip] = xy[flip,::-1]; xy = xy.reshape(-1,2)
            chunks.append(np.column_stack((xy,np.full(len(xy),z))))
        for part in get_parts(region):
            if not isinstance(part,Polygon) or part.is_empty: continue
            part = orient(part,sign=1.)
            for ring in (part.exterior,*part.interiors):
                xy = np.asarray(ring.coords); hi = np.column_stack((xy,np.full(len(xy),z)))
                lo = hi.copy(); lo[:,2] = base
                chunks.append(np.stack((lo[:-1],lo[1:],hi[1:],lo[:-1],hi[1:],hi[:-1]),axis=1).reshape(-1,3))
        previous = region
    return np.ascontiguousarray(np.concatenate(chunks),np.float32) if chunks else np.empty((0,3),np.float32)
