from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon, box

from tools.check_hsm_entry import audit_entry, axial_contact, check_entry, check_first_cut, compare_pitch, east_opening_profile, entry_plane_contact, neck_facing_straight, seed_search_focus


def test_neck_entry_floor_audit_does_not_treat_descent_as_clearance():
    report = check_entry()
    assert report['contained']
    assert 0 < report['max_ramp_deg'] <= 10.
    assert report['floor_removed_mm2'] == pytest.approx(45.24, abs=.05)
    assert report['end_stock_distance_mm'] > 2.
    assert report['connected_center_mm2'] > 10.
    assert report['floor_start_contact_without_ramp_credit_deg'] == 360.
    assert report['synthetic_preclear_mm2'] == 348.
    shallow, _, _, floor = report['slice_contacts']
    assert all(row['arrival_contact_deg'] == 360. for row in report['slice_contacts'])
    assert shallow['floor']['over_limit_xy_mm'] == 0.
    assert floor['descent']['xy_mm'] == 0.
    assert floor['floor']['over_limit_xy_mm'] == pytest.approx(9.41, abs=.02)
    coarse, fine = report['axial_contacts']
    assert fine['floor']['peak_over_limit_height_mm'] == .75
    assert fine['descent']['peak_over_limit_height_mm'] == .875
    assert coarse['floor']['mean_over_limit_height_mm'] == pytest.approx(fine['floor']['mean_over_limit_height_mm'])


def test_axial_sampling_reports_plunge_and_air_separately():
    path = [(5., 5., 0.), (5., 5., -1.), (5.01, 5., -1.)]
    result = axial_contact(box(0, 0, 10, 10), path, 1., bands=4)
    assert result['descent']['peak_over_limit_height_mm'] == 1.
    assert result['descent']['mean_over_limit_height_mm'] is None
    air = axial_contact(Polygon(), path, 1., bands=4)
    assert air['descent']['peak_over_limit_height_mm'] == 0.
    assert air['floor']['mean_over_limit_height_mm'] == 0.


@pytest.mark.parametrize('second', [False, True])
def test_first_cuts_leave_the_actual_entry_seed(tmp_path, second):
    path = tmp_path / 'first.nc'
    report = check_first_cut(review=path, second=second)
    assert report['stop'] == ('two_cuts_checked' if second else 'first_cut_checked')
    assert report['straight_proposals'] == 0
    assert report['entry_removed_mm2'] == pytest.approx(45.23, abs=.02)
    assert report['removed_mm2'] == pytest.approx(.492, abs=.003)
    assert report['peak_deg'] < 60.
    text = path.read_text('ascii')
    assert 'helix omitted' in text
    assert ('(Cut 2: stock removal)' in text) is second
    if second:
        assert report['second']['removed_mm2'] == pytest.approx(.468, abs=.003)
        assert report['second']['peak_deg'] < 60.
        assert report['second']['gates']['contact_limit'] > 0
    assert path.with_suffix('.opening.svg').is_file()


def test_seed_cut_budget_grows_connected_clearance_on_live_stock():
    report = check_first_cut(max_cuts=3)
    assert report['stop'] == 'cut_budget' and report['cut_count'] == 3
    assert report['straight_cut_count'] == 0
    assert report['total_removed_mm2'] > report['removed_mm2'] + report['second']['removed_mm2']
    assert report['connected_area_gain_mm2'] > 0.
    assert report['peak_contact_deg'] <= 60.


def test_fitted_straights_are_rejected_if_the_modeled_seed_cannot_reach_the_start():
    report = check_first_cut(max_cuts=1, fitted_straights=True)
    assert report['straight_proposals'] > 0
    assert report['gates']['start_clearance'] == report['straight_proposals']
    assert report['straight_cut_count'] == 0
    assert report['removed_mm2'] == pytest.approx(.492, abs=.003)


@pytest.mark.parametrize('longer', [False, True])
def test_clearance_shaped_turns_unlock_a_straight_body_from_the_seed(longer):
    report = check_first_cut(max_cuts=1, fitted_straights=True, turned_straights=True, longer_straights=longer)
    if longer:
        assert report['long_variant_counts']['endpoint_blocked'] > 0
        assert report['cuts_with_chord_at_least_225_mm'] == 0
    assert report['longest_cut_chord_mm'] == pytest.approx(1.25)  # First cut, not the 24-cut maximum.
    assert report['cut_count'] == 1 and report['cuts_with_chord_at_least_075_mm'] == 1
    assert report['straight_cut_count'] == 0  # Rounded ends, not a single chord.
    assert report['total_removed_mm2'] == pytest.approx(.820, abs=.003)
    assert report['total_feed_mm'] == pytest.approx(report['feed_mm'])
    assert report['connected_east_x_mm'] == pytest.approx(15.86694 + report['connected_east_gain_mm'], abs=.00001)
    assert report['peak_contact_deg'] < 60.
    assert report['gates']['start_clearance'] > 0


@pytest.mark.parametrize('neighbor', [False, True])
def test_parallel_face_probe_removes_stock_on_the_straight_body(tmp_path, neighbor):
    path = tmp_path / 'face.nc'
    report = check_first_cut(review=path, second=True, fitted_straights=True, turned_straights=True,
                             face_probe=True, face_after_neighbor=neighbor)
    trial = report['parallel_face_probe']
    assert trial['gates'] == {'eligible': 3, 'contact_limit': 1}
    assert trial['body_mm'] > trial['prior_body_mm']
    assert 0. < trial['approximate_body_removal_mm2'] < trial['removed_mm2'] < report['second']['removed_mm2']
    assert trial['link_mm'] + trial['cut_mm'] > report['second']['feed_mm']
    text = path.read_text('ascii')
    if neighbor:
        returning = report['face_after_neighbor']
        assert returning['removed_mm2'] == pytest.approx(trial['removed_mm2'])
        assert returning['link_mm'] > trial['link_mm']
        assert 'neighbor then parallel-face probe; helix omitted, 3 accepted cuts' in text
    else:
        assert 'parallel-face probe; helix omitted, 2 accepted cuts' in text


def test_repeated_face_pairs_use_last_live_pose_and_never_commit_partial_pairs(monkeypatch):
    from tools import check_hsm_entry as audit_tool

    first = SimpleNamespace(cut=[(1., 3.), (1., 2.)], remaining='first stock')
    neighbor = SimpleNamespace(cut=[(2., 3.), (2., 2.)], remaining='neighbor stock')
    final = SimpleNamespace(cut=[(3., 3.), (3., 2.)], remaining='returned stock')
    seen = []

    def propose(live, pose):
        seen.append((live, pose))
        return [neighbor]

    def choose(_pocket, _live, _pose, paths, _radius, *, on_eligible):
        for cut in paths:
            on_eligible((), cut)

    def search(_pocket, body, options, *_args, **_kwargs):
        assert options == [neighbor]
        return ([neighbor, final], {}) if body == tuple(first.cut) else ([], {})

    monkeypatch.setattr(audit_tool, 'choose_front_cut', choose)
    monkeypatch.setattr(audit_tool, 'search_face_neighbor', search)
    monkeypatch.setattr(audit_tool, 'connected_clearance', lambda *_: box(0, 0, 4, 4))
    accepted, trace, stop = audit_tool.extend_face_pairs(None, (0, 0), 2., {}, propose, [first], 2)
    assert accepted == [first, neighbor, final]
    assert seen == [('first stock', ((1., 2.), (0., -1.))), ('returned stock', ((3., 2.), (0., -1.)))]
    assert stop == 'no_checked_pair' and trace == [{'cut_count': 3, 'east_x_mm': 4.}]


def test_neck_facing_straight_preserves_stock_left_direction():
    assert neck_facing_straight([(1., 4.), (1., 3.), (1.1, 2.9)])
    assert not neck_facing_straight([(1., 3.), (1., 4.)])
    assert not neck_facing_straight([(1., 4.), (2., 3.9)])
    assert not neck_facing_straight([(1., 4.), (1., 3.9)])


def test_fitted_neighbor_ranks_verified_pairs_not_shortest_return(monkeypatch):
    from tools import check_hsm_entry as audit_tool

    def cut(area, travel):
        return SimpleNamespace(cut=[(0., 0.), (1., 0.)], removed_mm2=area, travel_mm=travel)

    short, efficient, blocked = cut(.5, 3.), cut(1.5, 2.), cut(1., 2.)
    returning = cut(.5, 2.)

    def probe(_p, _b, neighbor, *_args):
        if neighbor is blocked:
            return None, {}
        return returning, {'link_mm': .5 if neighbor is short else 1.}

    monkeypatch.setattr(audit_tool, 'probe_parallel_face', probe)
    pair, result = audit_tool.search_face_neighbor(None, None, [short, efficient, blocked], None, 2., {})
    assert pair == [efficient, returning]
    assert result['checked_neighbors'] == 3 and result['checked_pairs'] == 2
    assert result['shortest_return_link_mm'] == .5
    assert result['pair_removed_per_feed_mm'] == .5


def test_east_opening_compares_fixed_stations_and_does_not_sum_split_spans():
    initial = box(0., 0., 4., 4.)
    current = initial.union(box(3., 0., 4.4, 1.)).union(box(3., 2., 4.4, 3.5))
    profile = east_opening_profile([box(0., 0., 8., 8.)], initial, current)
    quarter = next(row for row in profile if row['offset_mm'] == .25)
    assert quarter['x_mm'] == 4.25
    assert quarter['connected_y_mm'] == [(0., 1.), (2., 3.5)]
    assert quarter['width_mm'] == 1.5
    assert profile[-1]['width_mm'] == 0.
    assert east_opening_profile([], Polygon(), current) == []


def test_live_seed_focus_keeps_old_search_and_reaches_new_clearance():
    fixed = box(0., 0., 5., 5.)
    current = box(4., 2., 6., 3.)
    assert seed_search_focus(fixed, current, 2.) is fixed
    assert seed_search_focus(fixed, Polygon(), 2., follow=True) is fixed
    expanded = seed_search_focus(fixed, current, 2., follow=True)
    assert expanded.covers(fixed)
    assert expanded.bounds[2] == pytest.approx(8.35)


def test_pitch_comparison_preserves_floor_and_accounts_for_added_travel():
    baseline, middle, shallow = compare_pitch(bands=8, step=.1)
    assert all(row['contained'] and row['same_floor_and_exit'] for row in (baseline, middle, shallow))
    assert shallow['floor_removed_mm2'] == baseline['floor_removed_mm2']
    assert shallow['actual_max_angle_deg'] < middle['actual_max_angle_deg'] < baseline['actual_max_angle_deg']
    assert shallow['contact']['descent']['xy_mm'] == pytest.approx(2.5*baseline['contact']['descent']['xy_mm'])
    assert shallow['contact']['descent']['peak_over_limit_height_mm'] < baseline['contact']['descent']['peak_over_limit_height_mm']


def test_entry_slice_clips_first_crossing_and_excludes_above_slice_travel():
    stock = box(0, 0, 20, 20)
    path = [(4., 6., 0.), (8., 6., -2.), (12., 6., -2.)]
    result = entry_plane_contact(stock, path, 1., -2., -1.)
    assert result['arrival_xy_mm'] == [6., 6.]
    assert result['arrival_contact_deg'] == 360.
    assert result['descent']['xy_mm'] == pytest.approx(2.)
    assert result['floor']['xy_mm'] == pytest.approx(4.)
    with pytest.raises(ValueError, match='slice'):
        entry_plane_contact(stock, path, 1., -2., -3.)


def test_entry_audit_rejects_missing_floor_and_flags_uncontained_sweep():
    pocket = box(0, 0, 10, 10)
    with pytest.raises(ValueError, match='floor pass'):
        audit_entry(pocket, pocket, [(1., 5., 0.), (1., 6., -1.)], 2., -2.)
    report = audit_entry(pocket, pocket, [(1., 5., 0.), (1., 6., -2.), (1., 7., -2.)], 2., -2.)
    assert not report['contained']
    assert report['floor_chords'] == 1
