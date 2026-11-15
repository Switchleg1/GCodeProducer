"""Contour-constrained linear/segmented lead-in/out, not arbitrary free-space arcs.

Entry follows a portion of the selected contour (closing edge backwards from
its seam for a closed loop) and ramps to depth. Exit follows already-cut line.
All XY centres stay on the original validated cut path.
"""
import numpy as np


def walk(points,closed,distance,entry):
    p=np.asarray(points,float)[:,:2]
    if len(p)<2:return None
    if entry:
        seq=np.vstack((p[0],p[:0:-1],p[0])) if closed else p
    else:
        seq=np.vstack((p,p[0])) if closed else p[::-1]
    result=[seq[0]]
    left=max(0,float(distance))
    for a,b in zip(seq,seq[1:]):
        length=float(np.linalg.norm(b-a))
        if length<1e-9:continue
        if length>=left:
            result.append(a+(b-a)*left/length)
            left=0;break
        result.append(b);left-=length
    if left>1e-6:return None
    result=np.asarray(result)
    return result[::-1].copy() if entry else result


def ramp(points,closed,depth,entry_z,length):
    """Use <=10° slope where sufficient contour length exists; otherwise no lead."""
    needed=max(float(length),abs(entry_z-depth)/np.tan(np.deg2rad(10)),.01)
    xy=walk(points,closed,needed,True)
    if xy is None:return None
    distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
    z=entry_z+(depth-entry_z)*distance/max(distance[-1],1e-12)
    return np.column_stack((xy,z))
