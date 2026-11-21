import pytest
from shapely.geometry import Polygon, box

from tools.check_hsm_entry import audit_entry, axial_contact, check_entry, check_first_cut, compare_pitch, entry_plane_contact, seed_search_focus


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
