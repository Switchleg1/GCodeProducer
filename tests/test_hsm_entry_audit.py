import pytest
from shapely.geometry import box

from tools.check_hsm_entry import audit_entry, check_entry


def test_neck_entry_floor_audit_does_not_treat_descent_as_clearance():
    report = check_entry()
    assert report['contained']
    assert 0 < report['max_ramp_deg'] <= 10.
    assert report['floor_removed_mm2'] == pytest.approx(45.24, abs=.05)
    assert report['end_stock_distance_mm'] > 2.
    assert report['connected_center_mm2'] > 10.
    assert report['floor_start_contact_without_ramp_credit_deg'] == 360.
    assert report['synthetic_preclear_mm2'] == 348.


def test_entry_audit_rejects_missing_floor_and_flags_uncontained_sweep():
    pocket = box(0, 0, 10, 10)
    with pytest.raises(ValueError, match='floor pass'):
        audit_entry(pocket, pocket, [(1., 5., 0.), (1., 6., -1.)], 2., -2.)
    report = audit_entry(pocket, pocket, [(1., 5., 0.), (1., 6., -2.), (1., 7., -2.)], 2., -2.)
    assert not report['contained']
    assert report['floor_chords'] == 1
