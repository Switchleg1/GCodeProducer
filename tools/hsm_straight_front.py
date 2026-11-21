"""Offline straight side-cut proposals along a live-stock frontier."""
import math

from shapely.geometry import LineString
from shapely.geometry.polygon import orient

from gcodeproducer.core.geometry.polygon_parts import polygons
from tools.check_cambam_pocket import BUFFER_SEGMENTS, CLEAR_AREA_MM2
from tools.hsm_contact_replay import indexed_contact


def frontier_edges(pocket, stock, *, focus=None):
    """Yield stock-left frontier edges, optionally clipped to a mapped focus."""
    walls = pocket.boundary
    for part in polygons(stock.intersection(pocket)):
        oriented = orient(part, sign=1.)
        for ring in (oriented.exterior, *oriented.interiors):
            vertices = list(ring.coords)
            for start, end in zip(vertices, vertices[1:]):
                if start == end:
                    continue
                edge = LineString((start, end))
                exposed = edge.difference(walls)
                if focus is not None:
                    exposed = exposed.intersection(focus)
                pieces = exposed.geoms if exposed.geom_type == 'MultiLineString' else (exposed,)
                for piece in pieces:
                    if piece.is_empty or piece.geom_type != 'LineString':
                        continue
                    a, b = piece.coords[0], piece.coords[-1]
                    aligned = sum((q-p)*(v-u) for p, q, u, v in zip(a, b, start, end)) > 0
                    yield (a, b) if aligned else (b, a)


def straight_advance(pocket, edge, radius, immersion, *, lead=0., runoff=0.):
    """Propose a parallel cut, offset into clearance by radius minus immersion.

    Lead and runoff extend the line past either end of the edge. Only the
    pocket boundary is checked here; replay must verify contact and access.
    """
    if (not all(map(math.isfinite, (radius, immersion, lead, runoff)))
            or not 0 < immersion < radius or min(lead, runoff) < 0):
        raise ValueError('expected 0 < immersion < radius and nonnegative lead/runoff')
    (ax, ay), (bx, by) = edge
    length = math.hypot(bx-ax, by-ay)
    if not length:
        raise ValueError('expected a nonzero frontier edge')
    tx, ty = (bx-ax)/length, (by-ay)/length
    offset = radius - immersion
    points = [(ax + ty*offset - tx*lead, ay - tx*offset - ty*lead),
              (bx + ty*offset + tx*runoff, by - tx*offset + ty*runoff)]
    axis = LineString(points)
    return points if pocket.covers(axis) and axis.distance(pocket.boundary) >= radius else None


def straight_front_candidates(pocket, stock, radius, immersion, *, min_edge, lead=0., runoff=0.):
    """Propose cuts from every sufficiently long exposed edge of live stock."""
    if not math.isfinite(min_edge) or min_edge <= 0:
        raise ValueError('expected a positive minimum edge length')
    for edge in frontier_edges(pocket, stock):
        if math.dist(*edge) >= min_edge:
            points = straight_advance(pocket, edge, radius, immersion, lead=lead, runoff=runoff)
            if points is not None:
                yield points


def fitted_front_candidates(pocket, stock, radius, *, focus=None, extensions=(1.25, 2.)):
    """Fit straight proposals across short stock edges; replay against unsimplified stock."""
    seen = set()
    for tolerance in (.15, .30):
        for edge in frontier_edges(pocket, stock.simplify(tolerance), focus=focus):
            if edge in seen or math.dist(*edge) < 2.:
                continue
            seen.add(edge)
            for immersion in (.10, .20):
                for extension in extensions:
                    cut = straight_advance(pocket, edge, radius, immersion, lead=extension, runoff=extension)
                    if cut is not None:
                        yield cut


def eased_front_bite(edge, radius, immersion, clearance, chord_error, *, ramp_fraction=.5):
    """Ease in and out of a stock-left edge, optionally holding full immersion between ramps."""
    if (not all(map(math.isfinite, (radius, immersion, clearance, chord_error)))
            or not 0 < immersion < radius or clearance <= 0 or chord_error <= 0
            or not 0 < ramp_fraction <= .5):
        raise ValueError('expected positive bite dimensions with immersion below cutter radius')
    (ax, ay), (bx, by) = edge
    length = math.hypot(bx-ax, by-ay)
    if not length:
        raise ValueError('expected a nonzero frontier edge')
    tx, ty = (bx-ax)/length, (by-ay)/length
    amplitude = immersion + clearance
    chords = max(2, math.ceil(math.pi*math.sqrt(amplitude/(4*chord_error))))
    if ramp_fraction == .5:
        samples = ((i/chords, math.sin(math.pi*(i/chords))**2) for i in range(chords+1))
    else:
        # Each ramp has half the phase span of the original full bite.
        halves = math.ceil(chords/2)
        ramp = [(ramp_fraction*i/halves, math.sin(math.pi*i/(2*halves))**2) for i in range(halves+1)]
        samples = [*ramp, *((1-t, depth) for t, depth in reversed(ramp))]
    points = []
    for t, depth in samples:
        lateral = radius + clearance - amplitude*depth
        points.append((ax + (bx-ax)*t + ty*lateral, ay + (by-ay)*t - tx*lateral))
    return points


def try_front_cut(pocket, stock, points, radius, *, contact_limit, sample_step, reject=None, on_overload=None):
    """Return (updated stock, sampled peak) only for a contained, useful cut.

    This trial commits one candidate, not the motion to reach its start. The
    sampled limit is a diagnostic; resolution must be checked separately.
    """
    if (not math.isfinite(radius) or radius <= 0 or not 0 < contact_limit <= 360
            or not math.isfinite(sample_step) or sample_step <= 0):
        raise ValueError('invalid cutter radius, contact limit, or sample spacing')
    axis = LineString(points)
    if not axis.length or not pocket.covers(axis) or axis.distance(pocket.boundary) < radius:
        if reject is not None:
            reject('cut_boundary')
        return None
    sweep = axis.buffer(radius, quad_segs=BUFFER_SEGMENTS)
    if stock.intersection(sweep).area <= CLEAR_AREA_MM2:
        if reject is not None:
            reject('no_removal')
        return None
    peak = 0.
    for segment, angle, _ in indexed_contact(points, stock, radius, sample_step, BUFFER_SEGMENTS):
        if angle > contact_limit:
            if on_overload is not None:
                on_overload(points, segment, angle)
            if reject is not None:
                reject('contact_limit')
            return None
        peak = max(peak, angle)
    return stock.difference(sweep), peak
