"""Offline flat-tool accessibility envelope for one band of model heights."""
import math
import numpy as np


def disk_envelope(tips, allowed, floor, ceiling, dx, dy, radius):
    """For each stock sample find a witness centre and its lowest feasible tip.

    Includes both the flat floor and the slope: a flat pass may already have
    reached a column under a neighbouring raised centre. Inf means no sampled
    placement, not proof of inaccessibility. Indices refer to the input grid.
    """
    tips=np.where(allowed & (tips<=ceiling),np.maximum(floor,tips),np.inf)
    ny,nx=tips.shape
    z=np.full_like(tips,np.inf,dtype=float); witness=np.full(tips.shape,-1,np.int32)
    index=np.arange(nx*ny,dtype=np.int32).reshape(tips.shape)
    for j in range(-min(ny-1,math.floor(radius/dy)),min(ny-1,math.floor(radius/dy))+1):
        k=min(nx-1,math.floor(math.sqrt(max(0,radius**2-(j*dy)**2))/dx))
        for i in range(-k,k+1):
            src=np.s_[max(0,-j):min(ny,ny-j),max(0,-i):min(nx,nx-i)]
            dst=np.s_[max(0,j):min(ny,ny+j),max(0,i):min(nx,nx+i)]
            lower=tips[src]<z[dst]; np.copyto(z[dst],tips[src],where=lower)
            np.copyto(witness[dst],index[src],where=lower)
    return z,witness
