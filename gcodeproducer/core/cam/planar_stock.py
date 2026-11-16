"""PlanarStock — cam subsystem."""
from __future__ import annotations
import numpy as np
from shapely.geometry import box, LineString, Point
from shapely.ops import unary_union

class PlanarStock:
    def __init__(self, stock):
        lo,hi=stock.bounds
        self.blank=box(lo[0],lo[1],hi[0],hi[1])
        self.top=float(hi[2])
        self.removed={}

    def at(self,z):
        if z>=self.top-1e-9:return self.blank.difference(self.blank)
        cuts=[g for depth,g in self.removed.values() if depth <= z+1e-6]
        return self.blank.difference(unary_union(cuts)) if cuts else self.blank

    def top_within(self,geom,start,end):
        """Highest Z in [end, start] where ``geom`` still meets material, else None.

        Material is piecewise constant between recorded removal depths, so only
        ``start`` and the depths just below each recorded removal need testing.
        """
        if geom.is_empty:return None
        candidates=[min(start,self.top)]+sorted({d for d,_ in self.removed.values() if end<d<start},reverse=True)
        for z in candidates:
            # ``at`` applies a 1e-6 tolerance of its own; probe clearly below a recorded depth.
            probe=z-1e-4 if z<start or z>=self.top-1e-9 else z
            if self.at(probe).intersection(geom).area>1e-9:
                return float(min(z,start))
        return None

    @staticmethod
    def sweep(paths,radius):
        sweeps=[]
        previous=None
        for path in paths:
            p=np.asarray(path.points)[:,:2]
            if path.stay_down and previous is not None:
                sweeps.append(LineString((previous,p[0])).buffer(radius))
            if len(p)==1:
                sweeps.append(Point(p[0]).buffer(radius))
            else:
                q=np.vstack((p,p[0])) if path.closed else p
                sweeps.append(LineString(q).buffer(radius))
            previous=p[0] if path.closed else p[-1]
        return unary_union(sweeps).normalize()

    def remove(self,paths,z,radius):
        swept=self.sweep(paths,radius)
        key=swept.wkb
        old=self.removed.get(key)
        self.removed[key]=(min(z,old[0]) if old else z,swept)
