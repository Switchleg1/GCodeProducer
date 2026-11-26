"""Replay GCodeProducer metric absolute linear NC against a solid rectangular blank.

Sample XY columns, not timesteps: solve the disk/segment intersection at each
column to include ramps at their actual Z. An absence of hits is not proof.
"""
import argparse
import math
import re
from collections import Counter

import numpy as np


def audit(path, bounds, top, diameter, pitch, axial_limit=None):
    x0, y0, x1, y1 = bounds
    xs = np.arange(x0 + pitch/2, x1, pitch)
    ys = np.arange(y0 + pitch/2, y1, pitch)
    height = np.full((len(ys), len(xs)), float(top))
    r = diameter/2
    pos = dict.fromkeys('XYZ', math.nan)
    hits = Counter()
    worst = {}
    kind = ''
    layer = None
    over = {}    # layer: [feed mm cutting deeper than axial_limit, sampled mm2 of such stock, first line]
    axial = {}   # layer: deepest stock any feed move of that layer cut through (mm above the cutter's tip)
    with open(path) as src:
        for n, raw in enumerate(src, 1):
            if raw.startswith(';LAYER:'):
                layer = int(raw.split(':')[1])
            if raw.startswith(';TYPE:'):
                kind = raw.strip()[6:]
            words = raw.partition(';')[0].split()
            if not words or words[0] in ('G90', 'G21') or not words[0].startswith('G'):
                continue
            if words[0] not in ('G0', 'G1'):
                raise ValueError(f'unsupported motion/mode at line {n}')
            a,b,c = pos.values()
            pos.update((w[0], float(w[1:])) for w in words[1:] if w[0] in 'XYZ')
            x,y,z = pos.values()
            if not all(map(math.isfinite, (a,b,c,x,y,z))) or min(c,z) >= top:
                continue
            i,j = xs.searchsorted([min(a,x)-r, max(a,x)+r], side='left'); j = min(j+1,len(xs))
            k,l = ys.searchsorted([min(b,y)-r, max(b,y)+r], side='left'); l = min(l+1,len(ys))
            h = height[k:l,i:j]; dx,dy = x-a,y-b
            u,v = xs[None,i:j]-a, ys[k:l,None]-b
            length = dx*dx+dy*dy
            if length:
                t = (u*dx+v*dy)/length
                disc = r*r-(u*dy-v*dx)**2/length
                dt = np.sqrt(np.maximum(0,disc)/length)
                mask = (disc>=0)&(t+dt>=0)&(t-dt<=1)
                floor = c+(z-c)*np.clip(t-dt if z>=c else t+dt,0,1)
            else:
                mask = u*u+v*v<=r*r; floor = min(c,z)
            delta = np.where(mask,h-floor,0.)
            tag = 'rapid' if words[0]=='G0' else kind
            if words[0] == 'G1' and layer is not None:
                axial[layer] = max(axial.get(layer, 0.), float(delta.max(initial=0)))
                if axial_limit is not None and delta.max(initial=0) > axial_limit:
                    entry = over.setdefault(layer, [0., 0., n, kind])
                    entry[0] += math.sqrt(length)
                    entry[1] += float((delta > axial_limit).sum())*pitch*pitch
            if tag in ('air','rapid') and delta.max(initial=0) > .001:
                hits[tag]+=1
                peak = float(delta.max())
                if peak>worst.get(tag,(0,))[0]:
                    row,col = np.unravel_index(delta.argmax(),delta.shape)
                    worst[tag]=(peak,n,float(xs[i+col]),float(ys[k+row]))
            np.minimum(h,floor,out=h,where=mask)
    return (dict(hits),worst,axial) if axial_limit is None else (dict(hits),worst,axial,over)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path'); p.add_argument('--bounds',nargs=4,type=float,required=True)
    p.add_argument('--top',type=float,default=0.); p.add_argument('--diameter',type=float,required=True)
    p.add_argument('--pitch',type=float,default=.2)
    p.add_argument('--axial-limit',type=float,help='report feed moves cutting stock that stands more than this above the tip (mm)')
    result = audit(**vars(p.parse_args()))
    hits, worst, axial = result[:3]
    print((hits, worst))
    print('deepest cut per layer (mm):', {k: round(v, 3) for k, v in axial.items()})
    if len(result) > 3:
        print('feed cutting deeper than the limit, per layer [mm of feed, mm2 of stock, first line, type]:',
              {k: [round(v[0], 1), round(v[1], 2), v[2], v[3]] for k, v in result[3].items()})
