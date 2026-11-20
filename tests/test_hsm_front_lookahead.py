from collections import Counter

import pytest
from shapely.geometry import box

from tools.hsm_front_run import run_front


def test_lookahead_prefers_checked_successor_and_only_commits_selected_paths():
    pocket = box(0, 0, 30, 12)
    stock = box(5, 5, 9, 7).union(box(14, 3, 18, 5)).union(box(21, 3, 25, 5))
    seed = ((3., 4.25), (1., 0.))
    near = [(4., 4.25), (10., 4.25)]
    far = [(13., 2.25), (19., 2.25)]
    follow = [(20., 2.25), (26., 2.25)]

    def propose(_stock, pose):
        return {seed[0]: [near, far], far[-1]: [follow]}.get(pose[0], [])

    settings = dict(max_cuts=3, contact_limit=60., sample_step=.05, link_handle=.5)
    greedy, _, reason = run_front(pocket, stock, seed, propose, 1., **settings)
    assert [cut.cut for cut in greedy] == [near] and reason == 'stalled'
    diagnostics = []
    choices, remaining, reason = run_front(pocket, stock, seed, propose, 1., lookahead_width=2,
                                          diagnostics=diagnostics, **settings)
    assert [cut.cut for cut in choices] == [far, follow] and reason == 'stalled'
    assert stock.area - remaining.area == pytest.approx(2.)
    assert diagnostics == [dict(Counter(eligible=2)), dict(Counter(eligible=1)), {}]
    delayed, _, reason = run_front(pocket, stock, seed, propose, 1., lookahead_width=2,
                                  lookahead_after=1, **settings)
    assert [cut.cut for cut in delayed] == [near] and reason == 'stalled'
    with pytest.raises(ValueError, match='lookahead_after'):
        run_front(pocket, stock, seed, propose, 1., lookahead_after=-1, **settings)
