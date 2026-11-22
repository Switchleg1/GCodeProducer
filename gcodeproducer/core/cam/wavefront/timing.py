"""Machine time of a wavefront plan with a trapezoidal motion planner."""
import math
import numpy as np

from shapely import points

from .wavefront_constants import (MACHINE_DEFAULTS)


def motion_time(points, feeds, accel, junction):
    """Seconds to follow a polyline from a stop to a stop: (total, per segment).

    feeds are mm/min per segment. A trapezoidal planner as in a controller:
    each segment speeds up and slows down at accel (mm/s²); corners are taken
    at the speed the junction deviation model allows, and a forward and a
    backward pass keep every speed reachable. The same model as
    gcodeproducer.core.gcode.time_estimate, for XY paths before G-code exists.
    """
    pts = np.asarray(points, float)
    if len(pts) < 2:
        return 0., np.zeros(0)
    delta = np.diff(pts, axis=0)
    length = np.linalg.norm(delta, axis=1)
    keep = length > 1e-9
    delta, length, vmax = delta[keep], length[keep], np.asarray(feeds, float)[keep]/60.
    if not len(length):
        return 0., np.zeros(0)
    unit = delta/length[:, None]
    m = len(length)
    speeds = np.zeros(m+1)
    if m > 1:
        cos_theta = -(unit[1:]*unit[:-1]).sum(axis=1)
        sin_half = np.sqrt(np.clip(.5*(1.-cos_theta), 0., 1.))
        with np.errstate(divide='ignore', invalid='ignore'):
            v = np.sqrt(accel*junction*sin_half/np.maximum(1.-sin_half, 1e-9))
        v = np.where(sin_half >= 1.-1e-9, np.inf, v)
        speeds[1:m] = np.minimum(v, np.minimum(vmax[1:], vmax[:-1]))
    reach = 2.*accel*length
    sp = speeds.tolist()
    for i in range(m):
        sp[i+1] = min(sp[i+1], math.sqrt(sp[i]*sp[i] + reach[i]))
    for i in range(m-1, -1, -1):
        sp[i] = min(sp[i], math.sqrt(sp[i+1]*sp[i+1] + reach[i]))
    v0, v1 = np.asarray(sp[:-1]), np.asarray(sp[1:])
    up, down = (vmax*vmax - v0*v0)/(2*accel), (vmax*vmax - v1*v1)/(2*accel)
    cruise = up + down <= length
    peak = np.where(cruise, vmax, np.minimum(np.sqrt(np.maximum((reach + v0*v0 + v1*v1)/2., 0.)), vmax))
    t = (peak-v0)/accel + (peak-v1)/accel + np.where(cruise, (length-up-down)/vmax, 0.)
    t = np.maximum(t, length/vmax)
    return float(t.sum()), t


def machine_time(strokes, islands, *, top, depth, machine=None):
    """Estimated seconds for one depth: {'total_s', 'cutting_s', 'links_s', 'helix_s', 'rapids_s'}.

    Cuts, corner moves and links run as one stay-down chain wherever each
    starts where the last ended, so the machine does not stop between them;
    a lift breaks the chain. A lift is a rapid up to RETRACT above the top,
    across and down again. Helices run at the plunge feed. The feeds and
    accelerations are MACHINE_DEFAULTS unless machine overrides them.
    """
    settings = dict(MACHINE_DEFAULTS, **(machine or {}))
    accel, junction = settings['acceleration_mm_s2'], settings['junction_deviation_mm']
    feed = {'link': settings['link_feed_mm_min']}
    out = {'cutting_s': 0., 'links_s': 0., 'helix_s': 0., 'rapids_s': 0.}
    chain, kinds = [], []

    def flush():
        if len(chain) > 1:
            total, each = motion_time(chain, [feed.get(k, settings['cut_feed_mm_min']) for k in kinds],
                                      accel, junction)
            for k, t in zip([k for k, a, b in zip(kinds, chain, chain[1:]) if math.dist(a, b) > 1e-9], each):
                out['links_s' if k == 'link' else 'cutting_s'] += float(t)
        chain.clear()
        kinds.clear()

    lift = (top + settings['retract_mm']) - depth
    for stroke in strokes:
        pts = [tuple(q) for q in stroke.points]
        if chain and math.dist(chain[-1], pts[0]) > 1e-6:
            across = math.dist(chain[-1], pts[0])
            flush()
            hop = [(0., 0.), (0., lift)]
            out['rapids_s'] += 2*motion_time(hop, [settings['rapid_mm_min']], accel, junction)[0]
            out['rapids_s'] += motion_time([(0., 0.), (across, 0.)], [settings['rapid_mm_min']], accel, junction)[0]
        if not chain:
            chain.append(pts[0])
        chain.extend(pts[1:])
        kinds.extend([stroke.kind]*(len(pts)-1))
    flush()
    for island in islands:
        out['helix_s'] += 60.*island.get('helix_mm', 0.)/settings['plunge_feed_mm_min']
        out['rapids_s'] += motion_time([(0., 0.), (0., lift)], [settings['rapid_mm_min']], accel, junction)[0]
    out['total_s'] = sum(out.values())
    out['machine'] = settings
    return out
