from tools.check_curved_adaptive import replay


def test_rising_and_falling_laps_merge_without_cutting_under_old_floor():
    assert replay(.05,False)['old_floor_bite_mm'] > .05
    assert replay(.05,True,.125)['old_floor_bite_mm'] > .001
    for pitch in (.05,.025):
        result = replay(pitch,True,.25)
        assert result['old_floor_bite_mm'] <= .001
        assert result['join_removal_mm3'] == 0
        assert result['radial_span_mm'] < .4
        assert result['removed_mm3'] > 25
        assert result['max_tip_lift_mm'] < .1
