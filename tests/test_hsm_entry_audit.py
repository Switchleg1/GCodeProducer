import pytest
from shapely.geometry import Polygon, box

from tools.check_hsm_entry import audit_entry, axial_contact, check_entry, check_first_cut, compare_pitch, entry_plane_contact


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
