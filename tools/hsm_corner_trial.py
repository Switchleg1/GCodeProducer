"""Offline local-profile trial for the pinned sharp-corner fixture."""
import math

from shapely.geometry import LineString

from tools.check_cambam_pocket import BUFFER_SEGMENTS, arc_points, replay_strokes
from tools.hsm_corner_fixtures import corner_slot_fixtures
from tools.hsm_tangent_link import cleared_tangent_link, tangent_chords


def compare_local_cleanup(fillet=.2, contact_step=.05):
    """Return replay reports for the same reference cut with/without cleanup."""
    return compare_staged_cleanup((fillet,), contact_step)


def compare_staged_cleanup(fillets, contact_step=.05, *, blended_returns=False, checked_returns=False):
    """Replay decreasing tangent radii in order against progressively cut stock."""
    fillets = tuple(fillets)
    if not fillets or any(not 0 < current < previous
                          for previous, current in zip((3., *fillets), fillets)):
        raise ValueError('cleanup fillets must decrease strictly from the initial 3 mm turn')
    pocket, stock, start, _ = corner_slot_fixtures()['sharp_corner']
    chord_error = .00025
    rough_arc, rough_length = arc_points((20., 1.), (23., 4.), (0., 3.), 1, chord_error)
    rough = [('G1', [start, (7., 1.)]), ('G1', [(7., 1.), (20., 1.)]),
             ('G3', rough_arc, rough_length), ('G1', [(23., 4.), (23., 10.)])]
    finish = []
    endpoint = (23., 10.)
    approach = (19.9, 1.) if checked_returns else (20., 1.)
    remaining = _after_cut(stock, rough) if checked_returns else None
    for fillet in fillets:
        arc_start, arc_end = (23.-fillet, 1.), (23., 1.+fillet)
        arc, length = arc_points(arc_start, arc_end, (0., fillet), 1, chord_error)
        if checked_returns or blended_returns:
            headings = ((0., 1.), (1., 0.))
            if checked_returns:
                points = cleared_tangent_link(pocket, remaining, 1., endpoint, approach, *headings, .5)
                if points is None:
                    raise ValueError('corner return failed the full-disk clearance check')
            else:
                points = tangent_chords(endpoint, approach, *headings, .5)
            finish.append(('blend', points, sum(math.dist(a, b) for a, b in zip(points, points[1:]))))
        else:
            finish.extend([('G1', [endpoint, (20., 6.)]), ('G1', [(20., 6.), approach])])
        cut = [('G1', [approach, arc_start]), ('G3', arc, length), ('G1', [arc_end, (23., 4.)])]
        finish.extend(cut)
        if checked_returns:
            remaining = _after_cut(remaining, cut)
        endpoint = (23., 4.)

    def evaluate(strokes):
        moves = ((number, mode, points, exact[0] if exact else math.dist(*points), True)
                 for number, (mode, points, *exact) in enumerate(strokes, 1))
        return replay_strokes(pocket, stock, 1., -.5, moves, chord_error, contact_step)

    return evaluate(rough), evaluate(rough + finish)


def _after_cut(stock, strokes):
    for _, points, *_ in strokes:
        stock = stock.difference(LineString(points).buffer(1., quad_segs=BUFFER_SEGMENTS))
    return stock
