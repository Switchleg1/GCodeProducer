"""Contour-constrained lead-in/out, not arbitrary free-space arcs.

Entry follows the selected contour and ramps to depth at no more than the
ramp angle. When the contour is shorter than the ramp needs, the entry keeps
following the *same* path: a closed contour is circled repeatedly (a helix
on the contour), an open path is traversed back and forth (a zigzag ramp).
All XY centres stay on the original validated cut path, so the ramp never
leaves the region the operation already cuts. Exit follows already-cut line.
"""
import numpy as np

MAX_POINTS = 20000          # guard against absurdly many laps on a microscopic contour


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


def _repeat_walk(cycle,distance):
    """Walk ``distance`` along ``cycle`` (closed sequence of points) repeated as often as needed."""
    seg=np.diff(cycle,axis=0)
    lengths=np.linalg.norm(seg,axis=1)
    keep=lengths>1e-9
    cycle=np.vstack((cycle[0],cycle[1:][keep]))
    lengths=lengths[keep]
    total=float(lengths.sum())
    if total<1e-6:return None
    laps=int(np.floor(distance/total))
    if (laps+1)*len(lengths)>MAX_POINTS:return None
    pieces=[cycle[:1]]+[cycle[1:]]*laps        # complete laps, then the partial remainder
    rest=distance-laps*total
    result=np.vstack(pieces)
    acc=0.0
    tail=[]
    for a,b,l in zip(cycle,cycle[1:],lengths):
        if acc+l>=rest-1e-12:
            tail.append(a+(b-a)*(rest-acc)/l)
            break
        tail.append(b);acc+=l
    return np.vstack((result,tail)) if tail else result


def entry_path(points,closed,distance):
    """XY sequence of total length ``distance`` ending at the path start, along the path itself.

    Returns (xy, kind) with kind 'linear', 'helix' (closed contour circled more than once)
    or 'zigzag' (open path traversed back and forth), or (None, None) for a degenerate path.
    """
    p=np.asarray(points,float)[:,:2]
    if len(p)<2:return None,None
    if closed:
        # Backwards around the loop from the seam, so reversing it arrives at p[0] in cut direction.
        cycle=np.vstack((p[0],p[:0:-1],p[0]))
    else:
        out=p
        cycle=np.vstack((out,out[-2::-1]))          # there and back: ends at p[0] again
    perimeter=float(np.linalg.norm(np.diff(cycle,axis=0),axis=1).sum())
    xy=_repeat_walk(cycle,distance)
    if xy is None:return None,None
    kind=("linear" if distance<=perimeter*(1 if closed else .5)+1e-9
          else "helix" if closed else "zigzag")
    return xy[::-1].copy(),kind


def ramp(points,closed,depth,entry_z,length,angle=10.0):
    """(N,3) ramp; see :func:`ramp_entry`."""
    return ramp_entry(points,closed,depth,entry_z,length,angle)[0]


def ramp_entry(points,closed,depth,entry_z,length,angle=10.0):
    """Ramp from entry_z to depth along the path at <= ``angle`` degrees; never skipped
    for lack of contour length. Returns ((N,3), kind) or (None, None) only for a degenerate path."""
    needed=max(float(length),abs(entry_z-depth)/np.tan(np.deg2rad(angle)),.01)
    xy,kind=entry_path(points,closed,needed)
    if xy is None:return None,None
    distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
    z=entry_z+(depth-entry_z)*distance/max(distance[-1],1e-12)
    return np.column_stack((xy,z)),kind
