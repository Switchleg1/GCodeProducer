"""Conservative cutter approximations used for material display, not feed selection."""
import math
from types import SimpleNamespace

import numpy as np
from ..gcode.toolpath import _arc_points
from .cam_constants import HYBRID_SECTION_TOLERANCE, HYBRID_PROFILE_BANDS


def profile(tool, radius):
    """Inscribed cylinders (height above tip, radius); None for unknown geometry."""
    kind = tool.get('type','endmill')
    if kind == 'endmill': return [(0.,radius)]
    if kind == 'ballnose':
        return [(h, math.sqrt(h*(2*radius-h))) for h in np.linspace(0,radius,HYBRID_PROFILE_BANDS+1)[1:]]
    angle = tool.get('vangle',0)
    if kind in ('vbit','engraver') and 0 < angle < 180:
        return [(r/math.tan(math.radians(angle/2)),r) for r in np.linspace(0,radius,HYBRID_PROFILE_BANDS+1)[1:]]
    return None


def arc_segments(a,b,params,cw,scale):
    """Incremental IJ or signed R in XY. Bound deviation rather than treating an arc as its chord."""
    p = {k:params[k]*scale for k in ('I','J','R') if k in params}
    if not p or ('R' in p and len(p)!=1) or 'P' in params: return None
    r = abs(p['R']) if 'R' in p else math.hypot(p.get('I',0),p.get('J',0))
    if not r: return None
    mismatch = 0.
    if 'R' not in p:
        mismatch = abs(math.hypot(b[0]-a[0]-p.get('I',0),b[1]-a[1]-p.get('J',0))-r)
        if mismatch > HYBRID_SECTION_TOLERANCE: return None
    pts = _arc_points(*a[:2],*b[:2],SimpleNamespace(params=p),cw,
                      max_seg=math.sqrt(8*r*HYBRID_SECTION_TOLERANCE))
    if any(len(q)!=3 for q in pts): return None
    # The display tessellator caps segment count. Compute its actual error.
    prev=a; out=[]
    for x,y,t in pts:
        end=np.array([x,y,a[2]+t*(b[2]-a[2])]); chord=math.dist(prev[:2],end[:2])+mismatch
        error=r-math.sqrt(max(0.,r*r-(chord/2)**2))+mismatch
        out.append((prev,end,error)); prev=end
    return out
