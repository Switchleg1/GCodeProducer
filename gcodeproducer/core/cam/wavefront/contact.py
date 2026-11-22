"""Cutting a path through planar stock while measuring the cutter contact angle."""
import math
import numpy as np

from shapely import contains_xy, distance, dwithin, points, prepare
from shapely.geometry import LineString, box

from gcodeproducer.core.geometry.polygon_parts import polygons
from .links import heading
from .wavefront_constants import (CUT_SEGMENTS)


def cutting_pieces(path, stock, radius, *, run_out=1., closed=False):
    """Keep the stretches of a dense path that touch stock, with a short run in and out through air."""
    if stock.is_empty or len(path) < 2:
        return []
    xy = np.asarray(path, float)[:, :2]
    lo, hi = xy.min(axis=0) - radius, xy.max(axis=0) + radius
    near = stock.intersection(box(lo[0], lo[1], hi[0], hi[1]))  # far faster than measuring the whole stock
    if near.is_empty:
        return []
    prepare(near)
    touching = dwithin(near, points(xy), radius - 1e-6).tolist()
    if not any(touching):
        return []
    if closed and not all(touching):
        # Start in the middle of the longest stretch of air so no piece straddles the seam.
        n, best, i = len(path)-1, (0, 0), 0
        while i < n:
            if touching[i]:
                i += 1
                continue
            j = i
            while j-i < n and not touching[(j+1) % n]:
                j += 1
            best = max(best, (j-i+1, i))
            i = j+1
        first = (best[1] + best[0]//2) % n
        path, touching = path[first:] + path[1:first+1], touching[first:] + touching[1:first+1]
    along = [0.]
    for a, b in zip(path, path[1:]):
        along.append(along[-1] + math.dist(a, b))
    spans, i = [], 0
    while i < len(path):
        if touching[i]:
            j = i
            while j+1 < len(path) and touching[j+1]:
                j += 1
            lo, hi = along[i]-run_out, along[j]+run_out
            if spans and lo <= spans[-1][1]:
                spans[-1][1] = hi
            else:
                spans.append([lo, hi])
            i = j
        i += 1
    pieces = []
    for lo, hi in spans:
        piece = [q for q, d in zip(path, along) if lo <= d <= hi]
        if len(piece) > 1 and LineString(piece).length >= .3:
            pieces.append(piece)
    return pieces


def chunk_contact(chunk, stock, radius, step, *, widths=None):
    """Contact angle in degrees at each sample along a short stretch of path: (angles, distances).

    widths, if a list, receives the engaged width at each sample, as a share of
    the cutter diameter: how far across the cutter, square to its travel, the
    material it touches reaches. A straight cut of radial depth a has width
    a/2r; a slot has 1. A thin crescent deep in a corner has a large angle but
    a small width.

    stock is the material before this stretch. The cutter has swept
    everything behind it, so only the half of its edge facing forward can
    touch material; that half is measured against stock, and the path's own
    sweep never has to be subtracted sample by sample. The window reaches a
    little past the half, by the angle the previous sample's disc leaves
    uncovered, which is what a replay that subtracts each step would see. This
    holds where the path turns no tighter than the cutter radius; a tighter
    turn reads high, never low. hsm_contact_replay.indexed_contact is the
    reference this is checked against.
    """
    poses, headings, lengths = [], [], []
    for start, end in zip(chunk, chunk[1:]):
        span = math.dist(start, end)
        if not span:
            continue
        count = math.ceil(span/step)
        heading = math.atan2(end[1]-start[1], end[0]-start[0])
        for k in range(1, count+1):
            t = k/count
            poses.append((start[0] + (end[0]-start[0])*t, start[1] + (end[1]-start[1])*t))
            headings.append(heading)
            lengths.append(span/count)
    angles = np.zeros(len(poses))
    if widths is not None:
        widths[:] = [0.]*len(poses)
    if stock.is_empty or not poses:
        return angles.tolist(), lengths
    a, b = [], []
    for part in polygons(stock):
        for ring in (part.exterior, *part.interiors):
            coords = np.asarray(ring.coords)[:, :2]
            a.append(coords[:-1])
            b.append(coords[1:])
    if not a:
        return angles.tolist(), lengths
    a, b = np.concatenate(a), np.concatenate(b)
    delta = (b - a)/radius
    norm2 = (delta*delta).sum(axis=1)
    a, delta, norm2 = a[norm2 > 0], delta[norm2 > 0], norm2[norm2 > 0]
    centres, heading = np.asarray(poses), np.asarray(headings)
    half = math.pi/2 + np.arcsin(np.minimum(1., np.asarray(lengths)/(2*radius)))
    # Every sample against every edge at once: where the cutter circle crosses the stock outline.
    p = (a[None, :, :] - centres[:, None, :])/radius
    t = -(p*delta[None, :, :]).sum(axis=2)/norm2[None, :]
    closest = p + t[:, :, None]*delta[None, :, :]
    h2 = 1. - (closest*closest).sum(axis=2)
    reach = np.sqrt(np.maximum(0., h2)/norm2[None, :])
    sample, angle = [np.arange(len(poses)), np.arange(len(poses))], [-half, half]
    for sense in (-1, 1):
        at = t + sense*reach
        on = (h2 >= -1e-12) & (at >= -1e-12) & (at <= 1.+1e-12)
        rows, cols = np.nonzero(on)
        q = p[rows, cols] + np.clip(at[rows, cols], 0., 1.)[:, None]*delta[cols]
        phi = (np.arctan2(q[:, 1], q[:, 0]) - heading[rows] + math.pi) % math.tau - math.pi
        inside = np.abs(phi) < half[rows]
        sample.append(rows[inside])
        angle.append(phi[inside])
    sample, angle = np.concatenate(sample), np.concatenate(angle)
    order = np.lexsort((angle, sample))
    sample, angle = sample[order], angle[order]
    # Between neighbouring crossings the edge is either all in stock or all out: test the middle.
    pair = (sample[1:] == sample[:-1]) & (angle[1:] - angle[:-1] > 1e-12)
    owner, lo, hi = sample[:-1][pair], angle[:-1][pair], angle[1:][pair]
    middle = heading[owner] + (lo+hi)/2
    inside = contains_xy(stock, centres[owner, 0] + radius*np.cos(middle), centres[owner, 1] + radius*np.sin(middle))
    np.add.at(angles, owner[inside], np.degrees((hi-lo)[inside]))
    if widths is not None:
        # Across the cutter: sin of the angle from the heading. Over each touched stretch of edge the
        # extremes are at its ends, or at a quarter turn either side where the stretch passes one.
        owner, lo, hi = owner[inside], lo[inside], hi[inside]
        top = np.maximum(np.sin(lo), np.sin(hi))
        top = np.where((lo < math.pi/2) & (hi > math.pi/2), 1., top)
        low = np.minimum(np.sin(lo), np.sin(hi))
        low = np.where((lo < -math.pi/2) & (hi > -math.pi/2), -1., low)
        high = np.full(len(poses), -np.inf)
        least = np.full(len(poses), np.inf)
        np.maximum.at(high, owner, top)
        np.minimum.at(least, owner, low)
        widths[:] = np.where(np.isfinite(high), (high - least)/2, 0.).tolist()
    return angles.tolist(), lengths


def cut(path, stock, radius, sample_step, *, where=None, tally=None, stop_above=None, measure='angle',
        ends=None):
    """Sampled peak contact and updated stock; chunked so each replay stays local.

    where, if given, receives the distance along the path of the peak sample.
    tally, if given, is [angle x distance, distance, distance in contact] and is added to.
    stop_above, if given, ends the replay at the first sample over it: the cut is refused
    anyway, and the returned stock is then not the stock after the cut.
    measure is what the peak (and stop_above) is: the contact 'angle' in degrees, or the
    engaged 'width' as a share of the cutter diameter. The tally is always of angles.
    ends, if given as (mm, factor), lets the first and last mm of the path reach factor times
    the limit: the peak is then reported scaled to the limit that applies where it occurs,
    so comparing it with stop_above still decides the cut.
    """
    total = sum(math.dist(a, b) for a, b in zip(path, path[1:])) if ends else 0.
    peak, chunk, length, travelled = 0., [path[0]], 0., 0.
    for i in range(1, len(path)):
        chunk.append(path[i])
        length += math.dist(path[i-1], path[i])
        if length >= 6. or i == len(path)-1:
            xs, ys = zip(*chunk)
            reach = radius + .01
            local = stock.intersection(box(min(xs)-reach, min(ys)-reach, max(xs)+reach, max(ys)+reach))
            across = [] if measure == 'width' else None
            angles, steps = chunk_contact(chunk, local, radius, sample_step, widths=across)
            for angle, step, value in zip(angles, steps, across if across is not None else angles):
                travelled += step
                if tally is not None:
                    tally[0] += angle*step
                    tally[1] += step
                    tally[2] += step if angle > 0 else 0.
                if ends and (travelled < ends[0] or total - travelled < ends[0]):
                    value = value/ends[1]  # A short transient where the cut starts or ends.
                if value > peak:
                    peak = value
                    if where is not None:
                        where[:] = [travelled]
                    if stop_above is not None and peak > stop_above:
                        return peak, stock
            stock = stock.difference(LineString(chunk).buffer(radius, quad_segs=CUT_SEGMENTS))
            chunk, length = [path[i]], 0.
    return peak, stock
