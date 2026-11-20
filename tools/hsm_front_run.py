"""Bounded offline replay of repeated frontier choices against live stock."""
from collections import Counter

from tools.check_cambam_pocket import CLEAR_AREA_MM2
from tools.hsm_front_choice import choose_front_cut


def run_front(pocket, stock, pose, propose, radius, *, max_cuts, contact_limit, sample_step,
              link_handle, link_margin=0., diagnostics=None):
    """Return accepted choices, remaining stock and why the run stopped.

    The callback receives live stock and the current pose. This runner neither
    invents entries nor assumes an uncut residual is unreachable when stalled.
    Optional diagnostics records first-gate counts per attempted selection.
    """
    if not isinstance(max_cuts, int) or max_cuts < 1:
        raise ValueError('max_cuts must be a positive integer')
    choices = []
    while len(choices) < max_cuts:
        if stock.area <= CLEAR_AREA_MM2:
            return choices, stock, 'stock_empty'
        counts = Counter() if diagnostics is not None else None
        choice = choose_front_cut(pocket, stock, pose, propose(stock, pose), radius,
                                  contact_limit=contact_limit, sample_step=sample_step,
                                  link_handle=link_handle, link_margin=link_margin, diagnostics=counts)
        if diagnostics is not None:
            diagnostics.append(dict(counts))
        if choice is None:
            return choices, stock, 'stalled'
        choices.append(choice)
        stock = choice.remaining
        tail = choice.cut[-1]
        for point in reversed(choice.cut[:-1]):
            if point != tail:
                pose = tail, tuple(b-a for a, b in zip(point, tail))
                break
    return choices, stock, 'stock_empty' if stock.area <= CLEAR_AREA_MM2 else 'cut_budget'
