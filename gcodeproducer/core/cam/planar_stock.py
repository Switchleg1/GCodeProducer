"""PlanarStock — cam subsystem."""
from __future__ import annotations
import numpy as np
from shapely.geometry import box, LineString, Point
from shapely.ops import unary_union
from gcodeproducer.core.cam.cam_constants import PLANAR_SWEEP_CHUNK

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
                # A long chain that doubles back on itself (an adaptive path) buffers far faster in
                # short stretches: one buffer of the whole chain resolves every self-overlap at once.
                step=PLANAR_SWEEP_CHUNK
                sweeps.extend(LineString(q[i:i+step+1]).buffer(radius) for i in range(0,max(len(q)-1,1),step))
            previous=p[0] if path.closed else p[-1]
        return unary_union(sweeps).normalize()

    def remove(self,paths,z,radius):
        # The projection of a surface-following pass is fully cleared only at
        # its highest tip Z, not at the nominal layer floor. Do not credit the
        # links either when a batch contains lifted moves of unknown link Z.
        if any(np.asarray(p.points).shape[1] == 3 for p in paths):
            for path in paths:
                points = np.asarray(path.points)
                depth = float(points[:, 2].max()) if points.shape[1] == 3 else z
                self._record(self.sweep([path], radius), depth)
            return
        self._record(self.sweep(paths, radius), z)

    def _record(self, swept, z):
        key=swept.wkb
        old=self.removed.get(key)
        self.removed[key]=(min(z,old[0]) if old else z,swept)
