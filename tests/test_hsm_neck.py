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
