import math

import pytest
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from tools.check_hsm_neck import neck_fixture
from tools.hsm_center_regions import center_regions
from tools.hsm_wavefront import (choose_seeds, clear_pocket, clearance, eased, find_lobes, fronts, spiral_out,
                                 write_review)


def test_two_islands_sit_a_third_in_from_each_end_of_a_long_pocket():
    allowed = unary_union(center_regions(box(0, 0, 60, 20), 2.))
    (one, room), = choose_seeds(allowed, 1, min_radius=2.)
    assert room == pytest.approx(8.) and one[1] == pytest.approx(10., abs=.1)
    left, right = choose_seeds(allowed, 2, min_radius=2.)
    assert left[0][0] == pytest.approx(2+56/3, abs=1.) and right[0][0] == pytest.approx(2+2*56/3, abs=1.)
    assert left[1] == right[1] == pytest.approx(8.)
    assert not choose_seeds(allowed, 2, min_radius=9.)


def test_widest_placement_puts_one_island_in_each_lobe():
    pocket, _ = neck_fixture()
    allowed = unary_union(center_regions(pocket, 2.))
    big, small = choose_seeds(allowed, 2, min_radius=2., placement='widest')
    assert big[0][0] > 80 and small[0][0] < 24
    assert big[1] > small[1] > 2.
    with pytest.raises(ValueError, match='placement'):
        choose_seeds(allowed, 2, min_radius=2., placement='random')


def test_default_placement_starts_one_island_in_each_lobe_joined_by_a_neck():
    pocket, _ = neck_fixture()
    allowed = unary_union(center_regions(pocket, 2.))
    big, small = find_lobes(allowed, min_radius=2.)
    assert big[0][0] > 80 and small[0][0] < 24 and big[1] > small[1]
    assert small[2][2] < big[0][0] and big[2][0] > small[0][0]  # Each box stops short of the other start.
    assert choose_seeds(allowed, min_radius=2.) == [big[:2], small[:2]]
    assert choose_seeds(allowed, 1, min_radius=2.) == [big[:2]]


def test_single_lobe_takes_two_islands_only_when_elongated():
    long = unary_union(center_regions(box(0, 0, 60, 20), 2.))
    squarer = unary_union(center_regions(box(0, 0, 30, 24), 2.))
    assert len(find_lobes(long, min_radius=2.)) == len(find_lobes(squarer, min_radius=2.)) == 1
    assert [round(xy[0], 1) for xy, _ in choose_seeds(long, min_radius=2.)] == [20.7, 39.3]
    (centre, room), = choose_seeds(squarer, min_radius=2.)
    assert room == pytest.approx(10.) and centre[1] == pytest.approx(12., abs=.1)
    with pytest.raises(ValueError, match='island count'):
        choose_seeds(long, min_radius=2., placement='thirds')


def test_spiral_grows_by_one_stepover_per_turn_and_rolls_off_inward():
    path = spiral_out((5., 5.), 4., .5)
    radii = [math.dist((5., 5.), p) for p in path]
    assert radii[0] == 0. and max(radii) == pytest.approx(4.)
    growth = [b-a for a, b in zip(radii, radii[1:])]
    peak = radii.index(max(radii))
    assert all(step >= -1e-9 for step in growth[:peak])
    assert radii[-1] < 4. and radii[-1] >= 3.5 - 1e-9
    assert max(math.dist(a, b) for a, b in zip(path, path[1:])) < .5
    # Clockwise keeps uncut stock on the left of the cutter.
    a, b = path[peak], path[peak+1]
    assert (a[0]-5.)*(b[1]-5.) - (a[1]-5.)*(b[0]-5.) < 0


def test_front_runs_skip_the_wall_and_start_and_end_on_the_old_front():
    allowed = box(0, 0, 10, 6)
    clear = box(0, 0, 4, 6)
    grown = clear.buffer(.5).intersection(allowed)
    (run, closed), = fronts(clear, grown, allowed.boundary)
    assert not closed and all(x == pytest.approx(4.5) for x, _ in run)
    assert run[0][1] > run[-1][1]  # Stock on the left while heading down the east face.
    path = eased(run, closed, clear, allowed, 2.)
    assert clear.distance(Point(path[0])) < 1e-9 and clear.distance(Point(path[-1])) < 1e-9
    assert max(x for x, _ in path) == pytest.approx(4.5)
    assert allowed.covers(LineString(path))


def test_small_pocket_is_cleared_under_the_contact_limit(tmp_path):
    pocket = box(0, 0, 18, 14)
    strokes, residual, report = clear_pocket(pocket, 2., sample_step=.2)
    assert strokes[0].kind == 'spiral' and report['islands'][0]['accepted']
    assert report['cleared_fraction'] > .95
    assert report['peak_contact_deg'] <= 60.
    assert all(stroke.peak_deg <= 60. for stroke in strokes)
    assert report['spiral_feed_mm'] > .4*report['cut_feed_mm']
    allowed = unary_union(center_regions(pocket, 2.)).buffer(1e-6)
    assert all(allowed.covers(LineString(stroke.points)) for stroke in strokes)
    assert clearance(allowed, residual, 2.).area > .9*allowed.area
    review = tmp_path / 'wave.nc'
    write_review(review, pocket, strokes, residual, report)
    text = review.read_text('ascii')
    assert text.startswith('(DEBUG ONLY') and 'helix entries omitted' in text
    assert sum(line.startswith('G0 ') for line in text.splitlines()) == len(strokes) and review.with_suffix('.svg').is_file()
    with pytest.raises(FileExistsError):
        write_review(review, pocket, strokes, residual, report)
