import pytest
from shapely.geometry import box

from tools.check_hsm_entry import audit_entry, check_entry, entry_plane_contact


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
