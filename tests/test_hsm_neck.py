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
    assert result['last_selection_counts'] == {'start_clearance': 5, 'link_clearance': 1, 'contact_limit': 3}


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


def test_live_waypoints_match_fixed_detour_coverage_with_less_travel():
    fixed = check_neck(with_corners=True, corner_runoff=.5, with_detours=True)
    live = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True)
    assert live['stop'] == 'stalled' and live['cut_count'] == fixed['cut_count']
    assert live['reachable_residual_mm2'] == pytest.approx(fixed['reachable_residual_mm2'])
    assert live['peak_contact_deg'] == pytest.approx(fixed['peak_contact_deg'])
    assert live['feed_mm'] < fixed['feed_mm'] - 3.


def test_shallow_stall_retry_adds_one_checked_cut():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True)
    assert result['stop'] == 'stalled' and result['cut_count'] == 10
    assert result['removed_mm2'] == pytest.approx(31.4215, abs=.001)
    assert result['peak_contact_deg'] < 60.
    assert result['last_selection_counts'] == {'origin_clearance': 1}


def test_shallow_exit_extension_does_not_bypass_origin_clearance():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=2.5)
    assert result['cut_count'] == 10 and result['stop'] == 'stalled'
    assert result['removed_mm2'] == pytest.approx(31.7965, abs=.001)
    assert result['last_stock_distance_mm'] < 2.
    assert result['last_selection_counts'] == {'origin_clearance': 1}
    assert result['peak_contact_deg'] < 60.


def test_earlier_shallow_rolloff_reaches_a_checked_origin():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1.)
    assert result['cut_count'] == 10 and result['stop'] == 'stalled'
    assert result['last_stock_distance_mm'] > 2.4
    assert result['last_wall_distance_mm'] > 2.
    assert result['peak_contact_deg'] < 60.
    assert 'origin_clearance' not in result['last_selection_counts']
    assert result['last_selection_counts'] == {'start_clearance': 78, 'contact_limit': 5, 'cut_boundary': 1}


def test_shallow_rollon_recovers_one_checked_cut():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.)
    assert result['cut_count'] == 11 and result['stop'] == 'stalled'
    assert result['removed_mm2'] == pytest.approx(33.525, abs=.002)
    assert result['peak_contact_deg'] < 60.
    assert result['last_stock_distance_mm'] > 2.


def test_shifted_joins_reach_cut_budget_with_stock_remaining():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True)
    assert result['cut_count'] == 12 and result['stop'] == 'cut_budget'
    assert result['removed_mm2'] == pytest.approx(36.2043, abs=.002)
    assert result['reachable_residual_mm2'] == pytest.approx(4116.36, abs=.02)
    assert result['peak_contact_deg'] == pytest.approx(56.17, abs=.1)


def test_larger_cut_budget_exposes_shifted_join_stall():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True, max_cuts=48)
    assert result['cut_count'] == 19 and result['stop'] == 'stalled'
    assert result['reachable_residual_mm2'] == pytest.approx(4103.77, abs=.02)
    assert result['last_selection_counts'] == {'start_clearance': 201, 'contact_limit': 34}


def test_clearance_tapers_find_clear_starts_but_do_not_bypass_contact_limit():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True, max_cuts=48, with_clearance_tapers=True)
    assert result['cut_count'] == 19 and result['stop'] == 'stalled'
    assert result['reachable_residual_mm2'] == pytest.approx(4103.77, abs=.02)
    assert result['last_selection_counts'] == {'start_clearance': 201, 'contact_limit': 42}
    assert result['last_taper_contact_failures'] == {'straight': 4, 'exit': 4}


def test_early_exit_trial_stalls_on_origin_clearance_before_matching_baseline_coverage():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True, max_cuts=48, with_clearance_tapers=True, with_early_exits=True)
    assert result['cut_count'] == 15 and result['stop'] == 'stalled'
    assert result['reachable_residual_mm2'] == pytest.approx(4104.81, abs=.02)
    assert result['last_selection_counts'] == {'origin_clearance': 1}
    assert result['last_stock_distance_mm'] < 2.
    assert result['peak_contact_deg'] < 60.
