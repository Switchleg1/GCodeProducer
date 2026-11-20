"""Bounded offline replay of repeated frontier choices against live stock."""
from collections import Counter

from tools.check_cambam_pocket import CLEAR_AREA_MM2
from tools.hsm_front_choice import choose_front_cut


def run_front(pocket, stock, pose, propose, radius, *, max_cuts, contact_limit, sample_step,
              link_handle, link_margin=0., diagnostics=None, waypoints=(), propose_waypoints=None,
              propose_on_stall=None, on_overload=None, require_clear_exit=False, with_three_leg_links=False, min_departure=0., priority_region=None,
              priority_score=None, lookahead_width=1, lookahead_after=0, propose_last_resort=None):
    """Return accepted choices, remaining stock and why the run stopped.

    The callback receives live stock and the current pose. This runner neither
    invents entries nor assumes an uncut residual is unreachable when stalled.
    Optional diagnostics records first-gate counts per attempted selection.
    """
    if not isinstance(max_cuts, int) or max_cuts < 1:
        raise ValueError('max_cuts must be a positive integer')
    if not isinstance(lookahead_width, int) or lookahead_width < 1:
        raise ValueError('lookahead_width must be a positive integer')
    if not isinstance(lookahead_after, int) or lookahead_after < 0:
        raise ValueError('lookahead_after must be a nonnegative integer')
    waypoints = tuple(waypoints)
    choices = []
    while len(choices) < max_cuts:
        if stock.area <= CLEAR_AREA_MM2:
            return choices, stock, 'stock_empty'
        counts = Counter()
        shortlist = []
        preview = lookahead_width > 1 and lookahead_after <= len(choices) < max_cuts - 1

        def keep(key, candidate):
            shortlist.append((key, candidate))
            shortlist.sort(key=lambda item: item[0], reverse=True)
            del shortlist[lookahead_width:]

        def report_overload(path, segment, angle):
            on_overload(len(choices), path, segment, angle)

        def select(factory, live, start, counts, speculative=False):
            routes = waypoints if propose_waypoints is None else (*waypoints, *propose_waypoints(live, start))
            return choose_front_cut(pocket, live, start, factory(live, start), radius,
                                    contact_limit=contact_limit, sample_step=sample_step,
                                    link_handle=link_handle, link_margin=link_margin, diagnostics=counts,
                                    waypoints=routes,
                                    on_overload=report_overload if on_overload is not None and not speculative else None,
                                    require_clear_exit=require_clear_exit, with_three_leg_links=with_three_leg_links,
                                    min_departure=min_departure, priority_region=priority_region,
                                    priority_score=priority_score,
                                    on_eligible=keep if preview and not speculative else None)

        def select_round(live, start, counts, speculative=False):
            choice = select(propose, live, start, counts, speculative)
            if choice is None and propose_on_stall is not None and not counts['origin_clearance']:
                choice = select(propose_on_stall, live, start, counts, speculative)
            if choice is None and propose_last_resort is not None and not counts['origin_clearance']:
                last_counts = Counter()
                choice = select(propose_last_resort, live, start, last_counts, speculative)
                counts.update({f'last_resort_{gate}': n for gate, n in last_counts.items()})
            return choice

        choice = select_round(stock, pose, counts)
        if preview and len(shortlist) > 1:
            best_pair = None
            for _, first in shortlist:
                second = select_round(first.remaining, _end_pose(first), Counter(), speculative=True)
                if second is None:
                    continue
                quality = (first.removed_mm2 + second.removed_mm2) / (first.travel_mm + second.travel_mm)
                key = (priority_score(second.remaining), quality) if priority_score is not None else (quality,)
                if best_pair is None or key > best_pair:
                    best_pair, choice = key, first
        if diagnostics is not None:
            diagnostics.append(dict(counts))
        if choice is None:
            return choices, stock, 'stalled'
        choices.append(choice)
        stock = choice.remaining
        pose = _end_pose(choice)
    return choices, stock, 'stock_empty' if stock.area <= CLEAR_AREA_MM2 else 'cut_budget'


def _end_pose(choice):
    tail = choice.cut[-1]
    previous = next(point for point in reversed(choice.cut[:-1]) if point != tail)
    return tail, tuple(b-a for a, b in zip(previous, tail))
