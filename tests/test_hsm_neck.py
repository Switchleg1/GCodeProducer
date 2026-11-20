import pytest

from tools.check_hsm_neck import check_neck


def test_straight_only_two_lobe_baseline_preserves_residual_on_stall():
    result = check_neck()
    assert result['regions'] == 1
    assert result['stop'] == 'stalled' and result['cut_count'] == 1
    assert result['removed_mm2'] == pytest.approx(3.)
    assert result['reachable_residual_mm2'] == pytest.approx(4149.56, abs=.02)
    assert result['peak_contact_deg'] < 60.
    assert result['last_xy_mm'] == (22., 28.5)
    assert result['last_selection_counts'] == {'link_clearance': 6, 'contact_limit': 3}


def test_corner_proposals_improve_coverage_but_do_not_hide_a_stall():
    baseline = check_neck()
    trial = check_neck(with_corners=True)
    assert trial['initial_stock_mm2'] == baseline['initial_stock_mm2']
    assert trial['corner_cut_count'] == 2 and trial['cut_count'] == 3
    assert trial['removed_mm2'] > baseline['removed_mm2'] + 7.
    assert trial['reachable_residual_mm2'] == pytest.approx(4142.28, abs=.02)
    assert trial['peak_contact_deg'] < 60.
    assert trial['stop'] == 'stalled' and trial['last_selection_counts'] == {'origin_clearance': 1}
    assert trial['last_stock_distance_mm'] == pytest.approx(1.9998494)


def test_corner_runoff_reaches_a_clear_origin_without_relaxing_cut_checks():
    trial = check_neck(with_corners=True, corner_runoff=.5)
    assert trial['last_stock_distance_mm'] > 2.
    assert trial['last_wall_distance_mm'] > 2.
    assert trial['peak_contact_deg'] < 60.
    assert trial['reachable_residual_mm2'] == pytest.approx(4141.60, abs=.02)
    assert trial['stop'] == 'stalled'
    assert 'origin_clearance' not in trial['last_selection_counts']
    assert trial['last_selection_counts']['link_clearance'] > 0


def test_checked_detours_advance_beyond_direct_link_stall():
    baseline = check_neck(with_corners=True, corner_runoff=.5)
    trial = check_neck(with_corners=True, corner_runoff=.5, with_detours=True)
    assert trial['cut_count'] == 9 and trial['stop'] == 'stalled'
    assert trial['removed_mm2'] - baseline['removed_mm2'] == pytest.approx(18.)
    assert trial['reachable_residual_mm2'] == pytest.approx(4123.60, abs=.02)
    assert trial['peak_contact_deg'] == pytest.approx(baseline['peak_contact_deg'])
