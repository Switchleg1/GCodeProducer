"""Experimental indexed sweep history for a rectangular blank and flat-ended cutter."""
from collections import defaultdict
import math

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union


class SweepStock:
    def __init__(self, bounds, bottom, top, tile_size):
        self.blank = box(*bounds)
        if bottom >= top or tile_size <= 0:
            raise ValueError('invalid stock dimensions')
        self.bottom, self.top, self.tile = bottom, top, tile_size
        self.sweeps = []
        self.index = defaultdict(list)

    def _tiles(self, bounds):
        i, j, k, l = (math.floor(v/self.tile) for v in bounds)
        return ((x, y) for x in range(i, k+1) for y in range(j, l+1))

    def cut(self, a, b, radius):
        a, b = tuple(a), tuple(b)
        if len(a) != 3 or len(b) != 3 or not all(map(math.isfinite, (*a, *b, radius))) or radius <= 0:
            raise ValueError('expected finite XYZ segment and positive radius')
        n = len(self.sweeps)
        self.sweeps.append((a, b, radius))
        for key in self._tiles((min(a[0], b[0])-radius, min(a[1], b[1])-radius,
                                max(a[0], b[0])+radius, max(a[1], b[1])+radius)):
            self.index[key].append(n)

    def height(self, x, y):
        """Lowest tip Z while the disk covered XY; None outside the original blank."""
        if not self.blank.covers(Point(x, y)):
            return None
        h = self.top
        for n in self.index.get((math.floor(x/self.tile), math.floor(y/self.tile)), ()):
            a, b, r = self.sweeps[n]
            dx, dy = b[0]-a[0], b[1]-a[1]
            u, v = x-a[0], y-a[1]
            length = math.hypot(dx, dy)
            if not length:
                if math.hypot(u, v) <= r:
                    h = min(h, a[2], b[2])
                continue
            along, across = (u*dx+v*dy)/length, (u*dy-v*dx)/length
            if abs(across) > r:
                continue
            half = math.sqrt((r-abs(across))*(r+abs(across)))
            lo, hi = max(0., along-half), min(length, along+half)
            if lo <= hi:
                t = lo if b[2] >= a[2] else hi
                h = min(h, a[2]+(b[2]-a[2])*t/length)
        return max(self.bottom, h)

    def remaining(self, z, tolerance, window=None):
        """XY section of stock above Z. Inscribed arcs under-credit clearance by <= tolerance."""
        if not self.bottom <= z <= self.top or tolerance <= 0:
            raise ValueError('invalid section or tolerance')
        window = self.blank if window is None else self.blank.intersection(window)
        if window.is_empty or z == self.top:
            return window.difference(window)
        x0,y0,x1,y1 = window.bounds
        cuts = []
        for n in sorted({n for k in self._tiles(window.bounds) for n in self.index.get(k, ())}):
            a, b, r = self.sweeps[n]
            if (max(a[0],b[0])+r<x0 or min(a[0],b[0])-r>x1 or
                    max(a[1],b[1])+r<y0 or min(a[1],b[1])-r>y1): continue
            if a[2] > b[2]:
                a, b = b, a
            if a[2] > z:
                continue
            t = 1 if b[2] <= z else (z-a[2])/(b[2]-a[2])
            end = tuple(a[i]+t*(b[i]-a[i]) for i in (0, 1))
            line = Point(*end) if end == a[:2] else LineString([a[:2], end])
            segments = max(1, math.ceil(math.pi/(8*math.asin(math.sqrt(min(1., tolerance/r)/2)))))
            cuts.append(line.buffer(r, quad_segs=segments))
        return window.difference(unary_union(cuts))
