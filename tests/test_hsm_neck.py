import pytest
from shapely.geometry import Point, Polygon, box

from tools.check_hsm_neck import (bounded_small_section_cuts, check_neck, clearance_delta, clearance_sections, section_bite_spans, section_bites,
                                  section_follow_cuts, small_section_cuts, overload_summary, relieve_contour, wider_sections, widest_span)


def test_wider_sections_use_nearest_sample_for_each_target():
    component = Polygon([(0, 0), (4, 0), (6, 2), (4, 4), (0, 4)])
    rows = wider_sections([box(0, 0, 8, 6)], component)
    assert [r['target_width_mm'] for r in rows] == [2., 2.5, 3.]
    assert [r['x_mm'] for r in rows] == [5., 4.75, 4.5]
    assert [widest_span(r) for r in rows] == [2., 2.5, 3.]
    assert widest_span({'connected_y_mm': [(1., 2.), (3., 4.5)]}) == 1.5
    assert not wider_sections([box(0, 0, 8, 6)], box(0, 0, 4, 1))


def test_clearance_delta_separates_area_gain_from_eastward_progress():
    before = box(0, 0, 2, 1)
    assert clearance_delta(before, box(0, 0, 2, 2)) == {'new_connected_mm2': 2., 'east_shift_mm': 0.}
    assert clearance_delta(before, box(0, 0, 3, 1)) == {'new_connected_mm2': 1., 'east_shift_mm': 1.}
    assert clearance_delta(before, Polygon()) == {'new_connected_mm2': 0., 'east_shift_mm': None}


def test_contour_relief_preserves_endpoints_and_tapers_locally():
    path = [(4., y) for y in (2., 1.5, 1.25, 1., .75, .5, 0.)]
    result = relieve_contour(path, .75, 1.25, .2, shoulder=.5)
    assert [y for _, y in result] == [y for _, y in path]
    assert [x for x, _ in result] == pytest.approx([4., 3.9, 3.8, 3.8, 3.8, 3.9, 4.])
    assert all(x == 4. for x, _ in path)


def test_overload_summary_bounds_whole_chords_and_counts_phases():
    rows = [{'phase': 'follow', 'chord_xy_mm': [(3, 4), (1, 2)]},
            {'phase': 'ease_in', 'chord_xy_mm': [(5, 1), (2, 6)]},
            {'phase': 'follow', 'chord_xy_mm': [(2, 3), (3, 3)]}]
    assert overload_summary(rows) == {'count': 3, 'phases': {'follow': 2, 'ease_in': 1},
                                      'chord_bounds_mm': (1., 1., 5., 6.)}
    assert overload_summary([]) == {'count': 0, 'phases': {}, 'chord_bounds_mm': None}


def test_small_section_audit_distinguishes_missing_contact_from_missing_span():
    sections = [{'x_mm': 4., 'eligible_y_mm': [(2., 6.)]}]
    stock = box(6.5, 0, 11, 10)
    audit = []
    paths = list(small_section_cuts(sections, stock, 2., turn_exits=True, audit=audit))
    assert paths == list(small_section_cuts(sections, stock, 2., turn_exits=True))
    assert sum(row['proposal_count'] for row in audit) == len(paths) == 24
    audit.clear()
    assert not list(small_section_cuts(sections, box(8, 0, 11, 10), 2., audit=audit))
    assert all(len(row['profiles'][0]['missed_y_mm']) == row['profiles'][0]['rows'] for row in audit)
    audit.clear()
    assert not list(small_section_cuts([], stock, 2., audit=audit))
    assert all(not row['profiles'] and row['proposal_count'] == 0 for row in audit)
    farther = box(7.6, 0, 11, 10)
    assert not list(small_section_cuts(sections, farther, 2.))
    extended = list(small_section_cuts(sections, farther, 2., ray_length=1.65))
    assert len(extended) == 12
    assert extended == list(small_section_cuts(sections, farther, 2., ray_length=1.8))
    extensions = []
    options = dict(extend=True, on_extension=lambda: extensions.append(True))
    assert list(bounded_small_section_cuts(sections, farther, 2.)) == []
    assert list(bounded_small_section_cuts(sections, farther, 2., **options)) == extended
    assert list(bounded_small_section_cuts(sections, stock, 2., turn_exits=True, **options)) == paths
    assert list(bounded_small_section_cuts([], stock, 2., **options)) == []
    assert extensions == [True]


def test_section_follow_eases_to_stock_contact_across_middle_rows():
    sections = [{'x_mm': 4., 'eligible_y_mm': [(2., 6.)]}]
    paths = list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2.))
    assert len(paths) == 3
    nominal, = section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., advances=(0.,))
    assert max(x for x, _ in nominal) == pytest.approx(4.5)
    assert nominal[0] == paths[0][0] and nominal[-1] == paths[0][-1]
    intermediate = list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., advances=(.01, .04)))
    assert [max(x for x, _ in path) for path in intermediate] == pytest.approx([4.51, 4.54])
    tapered = list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., taper_entry=True))
    assert tapered[:3] == paths and len(tapered) == 6
    for fraction in (.4, .5):
        shallow = list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., entry_fraction=fraction))
        for flat, ramped in zip(paths, shallow, strict=True):
            assert ramped[0] == flat[0]
            assert ramped[(len(flat)-1)//4][0] < flat[(len(flat)-1)//4][0]
            assert ramped[len(flat)//2:] == flat[len(flat)//2:]
    assert list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., taper_only=True)) == tapered[3:]
    for flat, ramped in zip(paths, tapered[3:]):
        quarter = (len(flat)-1)//4
        half = len(flat)//2
        assert ramped[0] == flat[0] and ramped[-1] == flat[-1]
        assert ramped[quarter][0] < flat[quarter][0]
        assert ramped[half:] == flat[half:]
    for path, expected in zip(paths, (4.55, 4.60, 4.65)):
        assert path[0] == pytest.approx((4., 5.8))
        assert path[-1] == pytest.approx((4., 2.2))
        assert all(x == pytest.approx(expected) for x, y in path if 3.2 < y < 4.8)
    audit = []
    assert list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., audit=audit)) == paths
    assert audit[0]['missed_y_mm'] == []
    assert audit[0]['max_hit_distance_mm'] == pytest.approx(.5)
    profiles = []
    variants = list(section_follow_cuts(sections, box(6.5, 0, 11, 10), 2., turn_exits=True,
                                        on_profile=lambda *data: profiles.append(data)))
    assert len(profiles) == len(variants) == 6
    assert all(path is variant for (path, _, _), variant in zip(profiles, variants))
    for i, body in enumerate(paths):
        (_, chords, advance), (retreat, retreat_body_chords, retreat_advance) = profiles[2*i:2*i+2]
        assert retreat[:chords+1] == body
        assert chords == retreat_body_chords == len(body)-1
        assert advance == retreat_advance == (.05, .10, .15)[i]
    audit.clear()
    assert not list(section_follow_cuts(sections, box(8, 0, 11, 10), 2., audit=audit))
    assert len(audit[0]['missed_y_mm']) == audit[0]['rows']
    assert audit[0]['max_hit_distance_mm'] is None
    audit.clear()
    assert not list(section_follow_cuts([{'x_mm': 4., 'eligible_y_mm': []}], box(8, 0, 11, 10), 2., audit=audit))
    assert not audit


def test_bite_span_audit_explains_empty_candidate_family():
    domain = [box(0, 0, 12, 10)]
    narrow = box(1, 0, 5, 1.49)
    audit = section_bite_spans(domain, narrow)
    assert [row['x_mm'] for row in audit] == [4.75, 4.5]
    assert all(row['connected_y_mm'] == [(0., 1.49)] and not row['eligible_y_mm'] for row in audit)
    assert list(section_bites(domain, narrow, 2.)) == []
    assert all(row['eligible_y_mm'] == [(0., 1.5)] for row in section_bite_spans(domain, box(1, 0, 5, 1.5)))


def test_section_bites_start_and_end_inside_clearance_and_bow_east():
    component = box(1, 2, 5, 7)
    paths = list(section_bites([box(0, 0, 12, 10)], component, 2.))
    assert len(paths) == 6
    for path in paths:
        assert component.contains(Point(path[0])) and component.contains(Point(path[-1]))
        assert path[0][0] == pytest.approx(path[-1][0])
        assert path[0][1] > path[-1][1]
        assert max(x for x, _ in path) > path[0][0]
    assert list(section_bites([box(0, 0, 12, 10)], box(1, 2, 5, 3), 2.)) == []
    variants = list(section_bites([box(0, 0, 12, 10)], component, 2., turn_exits=True))
    assert variants[::3] == paths and len(variants) == 18
    for index, path in enumerate(paths):
        for retreat in variants[3*index+1:3*index+3]:
            assert retreat[:len(path)] == path
            dx, dy = (b-a for a, b in zip(retreat[-2], retreat[-1]))
            assert dx < 0 and abs(dy) < abs(dx)


def test_west_search_stops_at_first_eligible_section_and_leaves_wide_default_alone():
    domain = [box(0, 0, 12, 10)]
    tapered = Polygon([(1, 0), (4.4, 0), (5, .8), (4.4, 1.6), (1, 1.6)])
    audit = section_bite_spans(domain, tapered, search_west=True)
    assert [row['x_mm'] for row in audit] == [4.75, 4.5, 4.25]
    assert [bool(row['eligible_y_mm']) for row in audit] == [False, False, True]
    assert len(list(section_bites(domain, tapered, 2., search_west=True))) == 3
    wide = box(1, 0, 5, 2)
    assert section_bite_spans(domain, wide, search_west=True) == section_bite_spans(domain, wide)
    assert len(section_bite_spans(domain, box(1, 0, 5, 1), search_west=True)) == 4


def test_fit_width_retains_first_measured_span_beyond_fixed_search():
    domain = [box(0, 0, 12, 10)]
    component = Polygon([(1, 0), (3.75, 0), (5, .8), (3.75, 1.6), (1, 1.6)])
    fixed = section_bite_spans(domain, component, search_west=True)
    fitted = section_bite_spans(domain, component, search_west=True, fit_width=True)
    assert len(fixed) == 4 and all(not s['eligible_y_mm'] for s in fixed)
    assert fitted[:-1] == fixed
    assert fitted[-1]['x_mm'] == 3.8125
    assert fitted[-1]['eligible_y_mm']
    narrow = box(1, 0, 5, 1)
    assert len(section_bite_spans(domain, narrow, search_west=True, fit_width=True)) == 4


def test_live_section_depths_follow_stock_contact_onset():
    domain = [box(0, 0, 12, 10)]
    component = box(1, 2, 5, 7)
    fixed = list(section_bites(domain, component, 2.))
    far = list(section_bites(domain, component, 2., live_stock=box(9, 0, 11, 10)))
    assert far == fixed
    live = list(section_bites(domain, component, 2., live_stock=box(7.1, 0, 11, 10)))
    assert len(live) > len(fixed)
    assert live[:3] == fixed[:3]
    assert max(x for x, _ in live[3]) == pytest.approx(5.15, abs=.0025)


def test_terminal_sections_distinguish_open_spans_from_wall_domain():
    domain = box(0, 0, 10, 10)
    connected = box(0, 2, 6, 3).union(box(0, 5, 6, 7)).union(box(0, 2, 1, 7))
    assert clearance_sections([domain], connected, [4, 8, 11]) == [
        {'x_mm': 4, 'domain_y_mm': [(0., 10.)], 'connected_y_mm': [(2., 3.), (5., 7.)]},
        {'x_mm': 8, 'domain_y_mm': [(0., 10.)], 'connected_y_mm': []},
        {'x_mm': 11, 'domain_y_mm': [], 'connected_y_mm': []},
    ]


def test_review_export_writes_xy_only_and_refuses_overwrite(tmp_path):
    path = tmp_path / 'review.nc'
    result = check_neck(review_gcode=path)
    text = path.read_text('ascii')
    assert text.startswith('(DEBUG ONLY')
    assert '(Cut 1: cleared link)' in text and '(Cut 1: stock removal)' in text
    moves = [line.split() for line in text.splitlines() if line.startswith(('G0 ', 'G1 '))]
    assert moves[0] == ['G0', 'X9.000000', 'Y28.500000']
    assert len(moves) > 1 and all(len(line) == 3 for line in moves)
    assert [float(word[1:]) for word in moves[-1][1:]] == pytest.approx(result['last_xy_mm'], abs=1e-6)
    with pytest.raises(FileExistsError):
        check_neck(review_gcode=path)
    assert path.read_text('ascii') == text


def test_clearance_trace_includes_seed_and_matches_final_report():
    report = check_neck(trace_clearance=True)
    initial, final = report['clearance_trace']
    assert initial['cut'] == 0 and initial['feed_mm'] == 0.
    assert final['cut'] == report['cut_count'] == 1
    assert final['area_mm2'] - initial['area_mm2'] == pytest.approx(report['seed_clearance_gain_mm2'])
    assert final['east_x_mm'] == report['seed_clearance_east_x_mm']
    assert not final['reaches_probe']
    assert initial['motion_sha256'] is None and initial['removed_mm2'] == 0.
    assert len(bytes.fromhex(final['motion_sha256'])) == 32
    assert final['motion_sha256'] == check_neck(trace_clearance=True)['clearance_trace'][-1]['motion_sha256']
    assert final['end_xy_mm'] == report['last_xy_mm']
    assert final['removed_mm2'] == pytest.approx(report['removed_mm2'])


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


def test_clear_exit_gate_advances_past_early_exit_stall():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True, max_cuts=48, with_clearance_tapers=True, with_early_exits=True,
                        require_clear_exit=True)
    assert result['cut_count'] == 23 and result['stop'] == 'stalled'
    assert result['reachable_residual_mm2'] == pytest.approx(4074.87, abs=.02)
    assert result['nearby_frontier_mm'] == pytest.approx(76.37, abs=.02)
    assert result['nearby_frontier_bounds_mm'][2] == pytest.approx(25.)
    assert result['last_selection_counts']['exit_clearance'] > 0
    assert 'origin_clearance' not in result['last_selection_counts']
    assert min(result['last_stock_distance_mm'], result['last_wall_distance_mm']) >= 2.
    assert result['peak_contact_deg'] < 60.


def test_eastern_front_adds_proposals_but_does_not_bypass_link_checks():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True, max_cuts=48, with_clearance_tapers=True, with_early_exits=True,
                        require_clear_exit=True, with_neck_front=True)
    assert result['cut_count'] == 23 and result['stop'] == 'stalled'
    assert result['reachable_residual_mm2'] == pytest.approx(4074.87, abs=.02)
    assert result['last_selection_counts']['link_clearance'] == 24


def test_departure_gate_reaches_later_stall_with_clear_departure():
    result = check_neck(with_corners=True, corner_runoff=.5, with_live_detours=True,
                        with_shallow_fronts=True, shallow_runoff=1., shallow_rolloff=1., shallow_rollon=1.,
                        with_shifted_joins=True, max_cuts=96, with_clearance_tapers=True, with_early_exits=True,
                        require_clear_exit=True, with_neck_front=True, min_departure=.25)
    assert result['stop'] == 'stalled' and result['cut_count'] == 57
    assert result['reachable_residual_mm2'] == pytest.approx(4011.53, abs=.02)
    assert result['last_selection_counts'] == {'start_clearance': 578, 'contact_limit': 38, 'exit_clearance': 10}
    assert result['last_forward_clearance_mm'] >= .25
    assert result['peak_contact_deg'] < 60.
