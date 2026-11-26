"""Offline first-layer comparison for the pinned Mini Yoda blank and linear metric NC."""
import argparse
import sys
import time
import pickle
from pathlib import Path

import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.cam.height_stock import HeightStock
from gcodeproducer.core.cam.sweep_stock import SweepStock
from gcodeproducer.core.cam.hybrid_stock import HybridStock


def moves(path, through_layer=0):
    p = [np.nan]*3
    with path.open() as f:
        for line in f:
            if line.startswith(';LAYER:') and int(line.split(':')[1])>through_layer:
                break
            words = line.partition(';')[0].split()
            if not words or words[0] in ('G21','G90') or not words[0].startswith('G'):
                continue
            if words[0] not in ('G0','G1'):
                raise ValueError('unsupported NC command '+words[0])
            q = p.copy()
            for w in words[1:]:
                if w[0] in 'XYZ':
                    q['XYZ'.index(w[0])] = float(w[1:])
            if words[0]=='G1' and np.isfinite(p).all() and min(p[2],q[2]) < 0:
                yield tuple(p), tuple(q)
            p = q


def compare(path, output):
    blank = Stock(x=118.105244589, y=87.504707605, width=63.789510821, depth=68.623332592, height=41.761627)
    lo,hi = blank.bounds
    grid = HeightStock(blank,.2)
    swept = SweepStock((*lo[:2],*hi[:2]),lo[2],0,4.)
    segs = list(moves(path))
    print('feed segments',len(segs),flush=True)
    hybrid = HybridStock((*lo[:2],*hi[:2]),lo[2],0,4.,.5)
    for state in (grid,swept,hybrid):
        t=time.perf_counter()
        for a,b in segs:
            state.cut(a,b,2.)
        print(type(state).__name__, 'build seconds',round(time.perf_counter()-t,3),'serialized bytes',len(pickle.dumps(state,protocol=5)),flush=True)
    # Compare occupancy of the stored cells, before Preview decimation.
    rects=[]
    for j,row in enumerate(grid.heights > -2):
        cuts=np.flatnonzero(np.diff(np.r_[False,row,False]))
        for i,k in cuts.reshape(-1,2):
            rects.append(box(lo[0]+i*grid.dx,lo[1]+j*grid.dy,lo[0]+k*grid.dx,lo[1]+(j+1)*grid.dy))
    cells=unary_union(rects)
    t=time.perf_counter(); section=swept.remaining(-2,.005); section_time=time.perf_counter()-t
    print('section seconds',round(section_time,2),'remaining mm2 grid/sweep',cells.area,section.area,'grid only/sweep only',cells.difference(section).area,section.difference(cells).area,flush=True)
    rng=np.random.default_rng(42); xy=rng.uniform(lo[:2],hi[:2],size=(1000,2))
    for label,fn in [('grid',lambda x,y:grid.heights[int((y-lo[1])/grid.dy),int((x-lo[0])/grid.dx)]),('sweep',swept.height)]:
        t=time.perf_counter(); vals=[fn(x,y) for x,y in xy];print(label,'1000 queries seconds',round(time.perf_counter()-t,4),'remaining probes',sum(v>-2 for v in vals))
    expected = np.asarray(vals)>-2
    t=time.perf_counter(); actual=np.array([hybrid.occupied(x,y,-2) for x,y in xy]); elapsed=time.perf_counter()-t
    print('hybrid queries seconds', round(elapsed,4),'blocks settled',hybrid.fast,'fallbacks',hybrid.detailed,
          'false clear',sum(expected & ~actual),'false solid',sum(~expected & actual))
    assert np.array_equal(expected,actual)
    # Grey = both, red = material only the sweep retained; blue = only the grid.
    shapes=''.join(g.svg(scale_factor=.02,fill_color=c) for g,c in ((cells.intersection(section),'#777777'),(cells.difference(section),'#2277ff'),(section.difference(cells),'#ff4422')) if not g.is_empty)
    output.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{lo[0]} {-hi[1]} {blank.width} {blank.depth}"><g transform="scale(1,-1)">{shapes}</g></svg>',encoding='utf8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('nc',type=Path);parser.add_argument('overlay',type=Path)
    args=parser.parse_args();compare(args.nc,args.overlay)
