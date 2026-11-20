"""Offline local-profile trial for the pinned sharp-corner fixture."""
import math

from tools.check_cambam_pocket import arc_points, replay_strokes
from tools.hsm_corner_fixtures import corner_slot_fixtures


def compare_local_cleanup(fillet=.2, contact_step=.05):
    """Return replay reports for the same reference cut with/without cleanup."""
    return compare_staged_cleanup((fillet,), contact_step)


def compare_staged_cleanup(fillets, contact_step=.05):
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
    for fillet in fillets:
        arc_start, arc_end = (23.-fillet, 1.), (23., 1.+fillet)
        arc, length = arc_points(arc_start, arc_end, (0., fillet), 1, chord_error)
        finish.extend([('G1', [endpoint, (20., 6.)]), ('G1', [(20., 6.), (20., 1.)]),
                       ('G1', [(20., 1.), arc_start]), ('G3', arc, length),
                       ('G1', [arc_end, (23., 4.)])])
        endpoint = (23., 4.)

    def evaluate(strokes):
        moves = ((number, mode, points, exact[0] if exact else math.dist(*points), True)
                 for number, (mode, points, *exact) in enumerate(strokes, 1))
        return replay_strokes(pocket, stock, 1., -.5, moves, chord_error, contact_step)

    return evaluate(rough), evaluate(rough + finish)
