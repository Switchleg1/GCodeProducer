from tools.check_adaptive_ledge import trial


def test_rise_before_crossing_the_ledge():
    name, report = trial()
    assert report['flat']['bite_mm'] == 1
    assert report['copied_ramp']['bite_mm'] > .1
    assert name == 'early_1.5'
    assert report[name]['width_mm'] == .3
    assert report[name]['bite_mm'] == 0
    assert report[name]['removed_mm3'] > 10
