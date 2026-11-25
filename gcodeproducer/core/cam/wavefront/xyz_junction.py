"""Experimental XYZ front meeting: check quantized proposals against ordered sweep history.

Only flat cutters, one initially rectangular blank, and one straight cutting
span per endpoint proposal. Not an NC entry planner. No writes on refusal.
"""
import math

import numpy as np
from shapely.geometry import LineString, Point


def join_front(stock, allowed, here, proposals, radius, width_limit, hand, tolerance=.002):
    """Select shortest verified link to a useful one-sided cut; else leave stock unchanged.

    allowed is an already-inset tool-centre zone. Test the complete capsule
    at the lowest tip Z on each segment: this overestimates contact on ramps.
    Compare transverse projection of fresh stock (including the end caps),
    not just sampled centre chords. Air before a cut is never credited as stock removal.
    """
    if hand not in ('climb','conventional') or not 0 < width_limit <= 2*radius:
        raise ValueError('expected one-sided cut and positive width limit')
    here = np.round(here,3)
    candidates = sorted(((np.round(a,3),np.round(b,3)) for a,b in proposals),
                        key=lambda ab:np.linalg.norm(ab[0]-here))
    n = max(1,math.ceil(math.pi/(4*math.acos(radius/(radius+tolerance)))))
    for a,b in candidates:
        travel = LineString([here[:2],a[:2]]) if np.any(here[:2]!=a[:2]) else Point(*a[:2])
        line = LineString([a[:2],b[:2]])
        if line.length<=0 or not allowed.covers(travel) or not allowed.covers(line): continue
        # No travel exists between consecutive verified cutting segments. Do
        # not test a circumscribed travel disk against an inscribed cut end.
        last = stock.sweeps[-1] if stock.sweeps else None
        continuous = (np.array_equal(here,a) and last is not None and
                      tuple(a)==last[1] and radius==last[2])
        if not continuous and not stock.clear_at_depth(here[:2],a[:2],radius,min(here[2],a[2]),tolerance): continue
        cap=line.buffer(radius/math.cos(math.pi/(4*n)),quad_segs=n)
        fresh=stock.remaining(min(a[2],b[2]),tolerance,cap)
        if fresh.is_empty: continue
        # Convex hull preserves projection extrema even for disconnected contacts.
        hull=fresh.convex_hull
        if hull.geom_type!='Polygon': continue
        normal=np.array([a[1]-b[1],b[0]-a[0]])/line.length
        offsets=(np.asarray(hull.exterior.coords)-a[:2])@normal
        if offsets.max()-offsets.min()>width_limit: continue
        if hand=='climb' and offsets.max()>0 or hand=='conventional' and offsets.min()<0: continue
        # Require actual material even at the higher tip. Remaining sections
        # under-credit previous cuts: confirm a point with the analytic height.
        inside=line.buffer(radius,quad_segs=n)
        region=stock.remaining(max(a[2],b[2]),tolerance,inside)
        if region.is_empty: continue
        probe=region.representative_point(); height=stock.height(probe.x,probe.y)
        if height is None or height<=max(a[2],b[2]): continue
        stock.cut(a,b,radius)
        return a,b,float(offsets.max()-offsets.min())
    return None
