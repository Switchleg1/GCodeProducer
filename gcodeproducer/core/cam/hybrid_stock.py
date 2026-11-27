"""Conservative block bounds over an indexed flat-cutter sweep history."""
import math

import numpy as np
from shapely.geometry import LineString, Point, box
from .sweep_stock import SweepStock


class HybridStock(SweepStock):
    def __init__(self, bounds, bottom, top, tile_size, block_size):
        super().__init__(bounds, bottom, top, tile_size)
        self.x0, self.y0, self.x1, self.y1 = bounds
        self.block = block_size
        nx, ny = (math.ceil(d/block_size) for d in (self.x1-self.x0,self.y1-self.y0))
        self.x = self.x0+(np.arange(nx)+.5)*block_size
        self.y = self.y0+(np.arange(ny)+.5)*block_size
        self.low = np.full((ny,nx),float(top)); self.high = self.low.copy()
        self.stamp = np.zeros((ny,nx),dtype=np.int64)
        self.cache = {}  # last exact point per block, tagged by last local cut
        self.sections = {}  # one fixed-depth residual per index tile, versioned by its sweep count
        self.fast = self.detailed = 0

    @classmethod
    def for_height_state(cls, state):
        from .cam_constants import HYBRID_BLOCK_MM, HYBRID_TILE_MM
        lo, hi = state.stock.bounds
        return cls((*lo[:2], *hi[:2]), lo[2], hi[2], HYBRID_TILE_MM,
                   max(HYBRID_BLOCK_MM, state.resolution))

    def _span(self, bounds):
        x,y,X,Y = bounds; s = self.block
        return (slice(max(0,math.floor((y-self.y0)/s)),max(0,math.floor((Y-self.y0)/s)+1)),
                slice(max(0,math.floor((x-self.x0)/s)),max(0,math.floor((X-self.x0)/s)+1)))

    def cut(self,a,b,radius):
        super().cut(a,b,radius)
        sy,sx = self._span((min(a[0],b[0])-radius,min(a[1],b[1])-radius,
                            max(a[0],b[0])+radius,max(a[1],b[1])+radius))
        u = self.x[None,sx]-a[0]; v = self.y[sy,None]-a[1]
        dx,dy = b[0]-a[0],b[1]-a[1]; length2 = dx*dx+dy*dy
        t = np.clip((u*dx+v*dy)/length2,0,1) if length2 else 0.
        dist = np.hypot(u-t*dx,v-t*dy)
        halfdiag = self.block/math.sqrt(2)+1e-10
        # Possible overlap: only lower the lower bound. Guaranteed full
        # coverage: the highest endpoint is a conservative upper bound.
        near = dist <= radius+halfdiag
        for grid,mask,z in ((self.low,near,min(a[2],b[2])),
                            (self.high,dist+halfdiag <= radius,max(a[2],b[2]))):
            h=grid[sy,sx]; np.minimum(h,max(self.bottom,z),out=h,where=mask)
        self.stamp[sy,sx][near] = len(self.sweeps)

    def occupied(self,x,y,z):
        if not (self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1):
            return False
        i=min(len(self.y)-1,math.floor((y-self.y0)/self.block)); j=min(len(self.x)-1,math.floor((x-self.x0)/self.block))
        if self.high[i,j] <= z or self.low[i,j] > z:
            self.fast += 1
            return bool(self.low[i,j] > z)
        token=(x,y,self.stamp[i,j]); entry=self.cache.get((i,j))
        if entry is None or entry[0]!=token:
            entry=(token,self.height(x,y)); self.cache[i,j]=entry
        self.detailed += 1
        return entry[1]>z

    def clear_at_depth(self,a,b,radius,z,tolerance=.001):
        """Test the whole fixed-Z cutter capsule, not just its centre. Mixed blocks use inscribed removal sections."""
        if radius <= 0 or not self.bottom <= z <= self.top or tolerance <= 0:
            raise ValueError('invalid clearance query')
        line=Point(a) if tuple(a)==tuple(b) else LineString([a,b])
        # Circumscribe the queried disk so polygon chords cannot miss a ridge.
        n=max(1,math.ceil(math.pi/(4*math.acos(radius/(radius+tolerance)))))
        footprint=line.buffer(radius/math.cos(math.pi/(4*n)),quad_segs=n).intersection(self.blank)
        if footprint.is_empty: return True
        sy,sx=self._span(footprint.bounds)
        for i,j in zip(*np.nonzero(self.high[sy,sx]>z)):
            i+=sy.start; j+=sx.start
            x=self.x0+j*self.block; y=self.y0+i*self.block
            block = box(x,y,x+self.block,y+self.block)
            if not block.intersects(footprint):
                continue
            if self.low[i,j]>z:
                return False
            # The section of the stock at z is worked out a whole tile at a time (the sweeps are indexed
            # by tile) and kept until a cut touches the tile: one union per tile, not per block.
            for key in self._tiles(block.bounds):
                if self._tile_section(key, z, tolerance).intersects(block.intersection(footprint)):
                    return False
        return True

    def _tile_section(self, key, z, tolerance):
        """The stock left above z within one index tile.

        Kept per tile and depth. Cuts only ever remove stock, so when cuts have
        touched the tile since, only those new sweeps are taken away from the
        section kept, instead of working the whole tile out again.
        """
        from shapely import prepare
        ids = self.index.get(key, ())
        entry = self.sections.get(key)
        if entry is not None and entry[0] == (z, tolerance):
            count, section = entry[1], entry[2]
            if count == len(ids):
                return section
            if not section.is_empty:
                cut = self.cut_at(ids[count:], z, tolerance, section.bounds)
                if cut is not None:
                    section = section.difference(cut)
                    prepare(section)
        else:
            i, j = key
            section = self.remaining(z, tolerance, box(i*self.tile, j*self.tile, (i+1)*self.tile, (j+1)*self.tile))
            prepare(section)
        self.sections[key] = ((z, tolerance), len(ids), section)
        return section
