import math

import pytest
from shapely.geometry import box

from tools.check_cambam_pocket import level_moves, read_pocket, replay


HEADER = 'G21\nG90\nG0 X2 Y2 Z3\nG1 Z-0.5\n'


def test_replay_counts_already_swept_returns_in_order():
    report, residual, rows = replay(box(0, 0, 10, 10), 1., -.5,
                                   HEADER + 'G1 X8\nG1 X2\nG1 Y8\n', .0025)
    assert report['stroke_count'] == 3
    assert report['already_swept_distance_mm'] == 6.
    assert report['outside_pocket_sweep_mm2'] == 0.
    assert rows[0]['new_sweep_mm2'] > 12.
    assert rows[1]['new_sweep_mm2'] == 0.
    assert rows[2]['new_sweep_mm2'] > 0.
    assert 0 < residual.area < report['reachable_mm2']


def test_replay_tracks_outside_sweep_separately():
    report, _, rows = replay(box(0, 0, 10, 10), 1., -.5, HEADER + 'G1 X11\n', .0025)
    assert report['outside_pocket_sweep_mm2'] > 0.
    assert rows[0]['new_sweep_mm2'] > rows[0]['new_pocket_sweep_mm2']


def test_arc_direction_length_and_target_plane_only():
    text = HEADER + 'G3 X3 Y3 I0 J1\nG2 X2 Y2 I-1 J0\nG0 Z3\n'
    arcs = list(level_moves(text, -.5, .0025))
    assert [arc[0] for arc in arcs] == [5, 6]
    assert [arc[3] for arc in arcs] == pytest.approx([math.pi/2, math.pi/2])
    assert arcs[0][2][0] == arcs[1][2][-1] == (2., 2.)
    assert len(arcs[0][2]) == len(arcs[1][2])
    for a, b in zip(arcs[0][2], reversed(arcs[1][2])):
        assert a == pytest.approx(b)


@pytest.mark.parametrize('block', ['G91', 'G0 X3', 'G1 Z-1', 'G2 X3 R1', 'G2 X3 I0 J1', 'G1 X3 X4'])
def test_fails_on_unsupported_geometry(block):
    with pytest.raises(ValueError):
        list(level_moves(HEADER + block, -.5, .0025))


def test_reads_one_native_outline_but_rejects_explicit_stock(tmp_path):
    text = '''<CADFile xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <objects><pline id="7" Closed="true"><mat m="Identity"/>
    <pts><p>0,0,0</p><p>10,0,0</p><p>10,10,0</p></pts></pline></objects>
    <machineops><mop xsi:type="MOPTrochopock" Enabled="true">
    <WorkPlane>XY</WorkPlane><primitive><prim>7</prim></primitive>
    <ToolDiameter>3.175</ToolDiameter><StockSurface>0</StockSurface>
    <TargetDepth>-0.5</TargetDepth><RoughingClearance>0</RoughingClearance>
    </mop></machineops><Stock><PMin>0,0</PMin><PMax>0,0</PMax></Stock></CADFile>'''
    src = tmp_path / 'pocket.cb'
    src.write_text(text)
    pocket, radius, depth = read_pocket(src)
    assert (pocket.area, radius, depth) == (50., 1.5875, -.5)
    src.write_text(text.replace('<PMax>0,0', '<PMax>10,10'))
    with pytest.raises(ValueError, match='explicit stock'):
        read_pocket(src)
