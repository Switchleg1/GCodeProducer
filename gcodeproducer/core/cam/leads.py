"""Contour-constrained lead-in/out, not arbitrary free-space arcs.

Entry follows the selected contour and ramps to depth at no more than the
ramp angle. When the contour is shorter than the ramp needs, the entry keeps
following the *same* path: a closed contour is circled repeatedly (a helix
on the contour), an open path is traversed back and forth (a zigzag ramp).
All XY centres stay on the original validated cut path, so the ramp never
leaves the region the operation already cuts. Exit follows already-cut line.

The same rule serves flat (XY at one depth) and surface-following (XYZ)
paths: points may carry Z, distances are measured in XY, and a ramp is never
below the path it follows (:func:`path_ramp`).
"""

from gcodeproducer.core.cam.cam_constants import MAX_POINTS, RAMP_ANGLE
from gcodeproducer.core.cam.lead_angle import lead_slope
import numpy as np


def _xy_length(a,b):
    return float(np.linalg.norm(np.asarray(b)[:2]-np.asarray(a)[:2]))


def walk(points,closed,distance,entry):
    p=np.asarray(points,float)
    if len(p)<2:return None
    if entry:
        seq=np.vstack((p[0],p[:0:-1],p[0])) if closed else p
    else:
        seq=np.vstack((p,p[0])) if closed else p[::-1]
    result=[seq[0]]
    left=max(0,float(distance))
    for a,b in zip(seq,seq[1:]):
        length=_xy_length(a,b)
        if length<1e-9:continue
        if length>=left:
            result.append(a+(b-a)*left/length)
            left=0;break
        result.append(b);left-=length
    if left>1e-6:return None
    result=np.asarray(result)
    return result[::-1].copy() if entry else result


def exit_path(points,closed,distance):
    """Use the requested cleared-contour exit, shortened to the surviving section.

    A tab may leave a section shorter than the configured lead length. Do not
    silently drop its exit: follow as much already-cut path as is available.
    """
    p=np.asarray(points,float)
    if len(p)<2:return None
    q=np.vstack((p,p[0])) if closed else p
    available=float(np.linalg.norm(np.diff(q[:,:2],axis=0),axis=1).sum())
    if available<1e-9:return None
    return walk(p,closed,min(max(0,float(distance)),available),False)


def _repeat_walk(cycle,distance):
    """Walk ``distance`` along ``cycle`` (closed sequence of points) repeated as often as needed."""
    seg=np.diff(cycle,axis=0)
    lengths=np.linalg.norm(seg[:,:2],axis=1)
    keep=lengths>1e-9
    cycle=np.vstack((cycle[0],cycle[1:][keep]))
    lengths=lengths[keep]
    total=float(lengths.sum())
    if total<1e-6:return None
    laps=int(np.floor(distance/total))
    if (laps+1)*len(lengths)>MAX_POINTS:
        raise ValueError(f"Lead-in would exceed {MAX_POINTS} segments; reduce lead length or depth per pass")
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
    p=np.asarray(points,float)
    if len(p)<2:return None,None
    if closed:
        # Backwards around the loop from the seam, so reversing it arrives at p[0] in cut direction.
        cycle=np.vstack((p[0],p[:0:-1],p[0]))
    else:
        out=p
        # Only the first ``distance`` of the path can be walked before turning back, so a long
        # open path (an adaptive chain of cuts) need not be copied whole into the cycle.
        run=np.r_[0,np.cumsum(np.linalg.norm(np.diff(out[:,:2],axis=0),axis=1))]
        if run[-1]>distance:
            out=out[:int(np.searchsorted(run,distance))+2]
        cycle=np.vstack((out,out[-2::-1]))          # there and back: ends at p[0] again
    perimeter=float(np.linalg.norm(np.diff(cycle[:,:2],axis=0),axis=1).sum())
    xy=_repeat_walk(cycle,distance)
    if xy is None:return None,None
    kind=("linear" if distance<=perimeter*(1 if closed else .5)+1e-9
          else "helix" if closed else "zigzag")
    return xy[::-1].copy(),kind


def ramp(points,closed,depth,entry_z,length,angle=RAMP_ANGLE):
    """(N,3) ramp; see :func:`ramp_entry`."""
    return ramp_entry(points,closed,depth,entry_z,length,angle)[0]


def ramp_entry(points,closed,depth,entry_z,length,angle=RAMP_ANGLE):
    """Ramp from entry_z to depth along an XY path at <= ``angle`` degrees; see :func:`path_ramp`."""
    p=np.asarray(points,float)[:,:2]
    return path_ramp(np.column_stack((p,np.full(len(p),float(depth)))),closed,entry_z,length,angle)


def path_ramp(points,closed,entry_z,length,angle=RAMP_ANGLE):
    """The one lead-in rule: ramp from ``entry_z`` down to the start of an XYZ path, along the path.

    Walks back along the path for the ramp length the drop needs at ``angle``
    (around a closed path - a helix - or back and forth along an open one - a
    zigzag), never skipped for lack of path length. The ramp descends at
    ``angle`` and never goes below the path itself: where the path is higher
    than the ramp (a surface path rising away from its start) the lead follows
    the path, which the feed rule then treats by its own descent angle.
    Returns ((N,3), kind) or (None, None) for a path with no XY length.
    """
    p=np.asarray(points,float)
    drop=max(0.,float(entry_z)-float(p[0,2]))
    needed=max(float(length),drop/lead_slope(angle),.01)
    walked,kind=entry_path(p,closed,needed)
    if walked is None:return None,None
    distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(walked[:,:2],axis=0),axis=1))]
    total=max(distance[-1],1e-12)
    z=np.maximum(float(entry_z)-drop*distance/total,walked[:,2])
    lead=np.column_stack((walked[:,:2],z))
    lead[-1]=p[0]
    return lead,kind
