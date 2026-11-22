import math

import pytest
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from tools.check_hsm_neck import neck_fixture
from tools.hsm_center_regions import center_regions
from tools.hsm_wavefront import (along_wall, bow_across, choose_seeds, clear_pocket, clearance, cut, cutting_pieces, eased,
                                 find_lobes, fronts, polygons, spiral_out, stay_down_link, wall_ends, write_review)


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


def test_a_boss_gets_a_start_at_each_wider_spot_on_the_way_round():
    # Regression: one start in a corner sent fronts both ways round the boss; they fanned out at its
    # corners (162 of 351 arcs at the smallest stepovers) and spent more on links than on cutting.
    square = box(0, 0, 50, 50).difference(box(17, 17, 33, 33))
    starts = choose_seeds(unary_union(center_regions(square, 2.)), min_radius=2.)
    assert sorted((round(x), round(y)) for (x, y), _ in starts) == [(10, 10), (10, 40), (40, 10), (40, 40)]
    assert all(room == pytest.approx(8., abs=.1) for _, room in starts)
    ring = Point(25, 25).buffer(24, quad_segs=32).difference(Point(25, 25).buffer(10, quad_segs=32))
    assert len(choose_seeds(unary_union(center_regions(ring, 2.)), min_radius=2.)) == 1  # Even width: one start.


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


def test_wall_ends_hook_onto_both_walls_and_short_arcs_roll_off_instead():
    pocket, allowed = box(-1, -1, 31, 21), box(0, 0, 30, 20)  # 1 mm cutter radius
    clear = box(0, 0, 10, 20)
    own = pocket.difference(box(-1, -1, 11, 21))
    rings = [LineString(allowed.exterior.coords)]
    (run, closed), = fronts(clear, clear.buffer(.5).intersection(allowed), allowed.boundary)
    path = wall_ends(run, clear, own, 1., allowed, rings, 3.)
    assert allowed.covers(LineString(path)) and max(x for x, _ in path) == pytest.approx(10.5)
    assert clear.distance(Point(path[0])) < 1e-9 and clear.distance(Point(path[-1])) < 1e-9
    top = [x for x, y in path if y > 20 - 1e-9]
    bottom = [x for x, y in path if y < 1e-9]
    # A hook of twice the cutter radius meets each wall about 2.9 mm behind the front and runs back along it.
    assert max(top) == pytest.approx(10.5 - 2/.7, abs=.2) and max(bottom) == pytest.approx(10.5 - 2/.7, abs=.2)
    assert min(top) < max(top) - .5 and min(bottom) < max(bottom) - .5
    headings = [math.atan2(b[1]-a[1], b[0]-a[0]) for a, b in zip(path, path[1:]) if math.dist(a, b) > 1e-6]
    turns = [abs((b-a+math.pi) % (2*math.pi) - math.pi) for a, b in zip(headings, headings[1:])]
    assert max(turns) < math.radians(35)  # No sharp corner anywhere along the hooked arc.
    plain = wall_ends([(10.5, 15.), (10.5, 5.)], clear, own, 1., allowed, rings, 3.)
    assert all(0 < y < 20 for _, y in plain)  # Ends away from the wall roll off to the old front instead.
    short = wall_ends([(10.5, 2.), (10.5, 0.)], clear, own, 1., allowed, rings, 3.)
    assert clear.distance(Point(short[0])) < 1e-9 and clear.distance(Point(short[-1])) < 1e-9


@pytest.mark.parametrize('pocket', [box(-2, -2, 62, 22), Polygon([(-2, -2), (62, -22), (62, 42), (-2, 22)])])
def test_hooks_nest_pass_after_pass_without_drifting_or_loading_up(pocket):
    # Regressions: (1) a front ends a few hundredths short of the wall and the wall treatment was skipped;
    # (2) hooking from the front's curled-in end landed further back each pass until contact ran away.
    allowed = pocket.buffer(-2., join_style=2)
    rings = [LineString(allowed.exterior.coords)]
    own = pocket.difference(box(-2, -40, 6, 60))
    peaks, lag = [], []
    for _ in range(14):
        part = max(polygons(clearance(allowed, own, 2.)), key=lambda g: g.area)
        (run, closed), = fronts(part, part.buffer(.4, quad_segs=16).intersection(allowed), allowed.boundary)
        assert along_wall(rings, run[0], part, own, 2., .75) is not None
        assert along_wall(rings, run[-1], part, own, 2., .75) is not None
        path = wall_ends(run, part, own, 2., allowed, rings, 3.)
        peak, own = cut(path, own, 2., .2)
        peaks.append(peak)
        on_wall = [x for x, y in path if allowed.boundary.distance(Point(x, y)) < 1e-6]
        lag.append(max(x for x, _ in path) - max(on_wall))
    # Bounded; it still swings between about 47 and 66 degrees from pass to pass (open issue), and the
    # contact check refuses the heavy passes.
    assert max(peaks) < 70.
    assert min(lag[4:]) > 1.5  # The wall is met well behind the front, never square on.


@pytest.mark.parametrize('width, steady', [(6., 59.), (8., 56.), (12., 52.)])
def test_narrow_channel_is_crossed_in_one_bow_with_steady_contact(width, steady):
    # Regression: two separate hooks on the short arc across a channel are tight corners; in the 80 x 12
    # slot they read over 110 degrees and half the arcs fell to the smallest stepovers.
    pocket = box(-2, -2, 62, width+2)
    allowed = pocket.buffer(-2., join_style=2)
    rings = [LineString(allowed.exterior.coords)]
    own = pocket.difference(box(-2, -40, 6, 60))
    peaks, reach = [], []
    for _ in range(12):
        part = max(polygons(clearance(allowed, own, 2.)), key=lambda g: g.area)
        (run, closed), = fronts(part, part.buffer(.4, quad_segs=16).intersection(allowed), allowed.boundary)
        note = []
        path = wall_ends(run, part, own, 2., allowed, rings, 3., note=note)
        if len(peaks) >= 6:
            assert note == ['bow', 'bow']
            assert part.distance(Point(path[0])) < 1e-6 and part.distance(Point(path[-1])) < 1e-6
            assert sum(y < 1e-6 for _, y in path) > 3 and sum(y > width - 1e-6 for _, y in path) > 3  # Both walls.
        peak, own = cut(path, own, 2., .1)
        peaks.append(peak)
        reach.append(part.bounds[2])
    assert peaks[6:] == pytest.approx([steady]*6, abs=1.5)
    steps = [b-a for a, b in zip(reach[6:], reach[7:])]
    assert steps == pytest.approx([.4]*len(steps), abs=.02)  # One stepover per pass, every pass the same shape.


def test_bow_needs_a_narrow_channel_with_near_parallel_walls():
    run = [(10., 12.), (10.4, 6.), (10., 0.)]
    part = box(-18, 0, 9.6, 12)
    for pocket, expected in ((box(-20, -2, 20, 14), True),                                 # 12 mm, parallel
                             (Polygon([(-20, -2), (20, -6), (20, 18), (-20, 14)]), False),  # tapering
                             (box(-20, -2, 20, 22), False)):                               # 20 mm, too wide
        allowed = pocket.buffer(-2., join_style=2)
        rings = [LineString(allowed.exterior.coords)]
        own = pocket.difference(part.buffer(2., join_style=2))
        bow = bow_across(run, rings, part, own, 2., allowed, 2*2./.7, .75, .75)
        assert (bow is not None) is expected


@pytest.mark.parametrize('gap', [0., .7])
def test_arcs_round_a_disc_that_touches_or_nearly_touches_a_wall_stay_light(gap):
    # Regression: beside a spiral the next front meets the wall almost parallel to it. A hook there ran
    # a straight line off a tightly curved front, and its wall leg hunted up to 20 mm for clean wall
    # through uncut stock, so contact read 100-184 degrees and every such arc fell to the smallest step.
    pocket = box(-30, -2, 30, 40)
    allowed = pocket.buffer(-2., join_style=2)
    rings = [LineString(allowed.exterior.coords)]
    own = pocket.difference(Point(0, 10+gap).buffer(12, quad_segs=64))  # cleared centres: a 10 mm disc
    peaks = []
    for _ in range(14):
        part = max(polygons(clearance(allowed, own, 2.)), key=lambda g: g.area)
        runs = fronts(part, part.buffer(.4, quad_segs=16).intersection(allowed), allowed.boundary)
        assert len(runs) == 1
        (run, closed), = runs
        path = eased(run, closed, part, allowed, 3.) if closed else wall_ends(run, part, own, 2., allowed, rings, 3.)
        peak, own = cut(path, own, 2., .1)
        peaks.append(peak)
    # Only the pass that first breaks through a gap to the wall is heavier; the rest stay under the limit.
    assert sorted(peaks)[-2] < 58. and max(peaks) < (58. if not gap else 75.)


def test_wall_is_not_followed_where_cleared_ground_falls_away_from_it():
    pocket, allowed = box(-1, -1, 31, 21), box(0, 0, 30, 20)
    rings = [LineString(allowed.exterior.coords)]
    clear = Point(15, 6).buffer(5.5, quad_segs=64)          # comes within 0.5 mm of the wall y = 0, never touches
    own = pocket.difference(clear.buffer(1., quad_segs=64))
    tail = along_wall(rings, (11., 0.), clear, own, 1., .75)
    xs = [x for x, _ in tail]
    assert xs == sorted(xs) and 15. <= xs[-1] < 16.5      # As far as the nearest approach plus the overlap.
    away = along_wall(rings, (19., 0.), clear, own, 1., .75)
    assert away[-1][0] < 19. and away[-1][0] > 13.5        # From the far side it comes back the same way.


def test_cutting_pieces_drop_air_and_keep_a_short_run_in_and_out():
    path = [(x/10, 0.) for x in range(0, 201)]
    stock = box(5, .5, 9, 3).union(box(14, .5, 16, 3))
    first, second = cutting_pieces(path, stock, 1.)
    assert first[0][0] == pytest.approx(3.2, abs=.11) and first[-1][0] == pytest.approx(10.8, abs=.11)
    assert second[0][0] == pytest.approx(12.2, abs=.11) and second[-1][0] == pytest.approx(17.8, abs=.11)
    joined, = cutting_pieces(path, stock, 1., run_out=2.)
    assert joined[0][0] < 3.5 and joined[-1][0] > 17.5
    assert cutting_pieces(path, box(5, 1.5, 9, 3), 1.) == []
    ring = [(0., 0.), (4., 0.), (4., 4.), (0., 4.), (0., 0.)]
    dense = [(x/10, 0.) for x in range(40)] + [(4., y/10) for y in range(40)] +             [(4-x/10, 4.) for x in range(40)] + [(0., 4-y/10) for y in range(41)]
    wrapped, = cutting_pieces(dense, Point(0., 0.).buffer(1.5), 1., closed=True, run_out=.5)
    assert len(ring) == 5 and LineString(wrapped).length == pytest.approx(6., abs=.3)  # One piece across the seam.


def test_each_island_keeps_its_own_fronts_and_the_last_breaks_through():
    pocket = unary_union([box(0, 0, 14, 12), box(13, 3, 23, 9), box(22, 0, 36, 12)])
    strokes, residual, report = clear_pocket(pocket, 2., sample_step=.3)
    first, last = report['islands']
    assert first['front_arcs'] > 0 and last['front_arcs'] > 0
    assert report['retract_rapids'] == 2
    assert report['retract_reasons'] == {'separate_cleared_areas': 1, 'first_cut': 1}
    assert report['peak_contact_deg'] <= 60. and report['cleared_fraction'] > .93
    kinds = [stroke.kind for stroke in strokes if stroke.kind != 'link']
    assert kinds[0] == 'spiral' and kinds.count('spiral') == 2
    second_spiral = kinds.index('spiral', 1)
    assert 'front' in kinds[1:second_spiral]  # The first island works its own ground before the lift.
    assert 'profile' not in kinds and report['wall_profile'] is None
    centre_x = [island['centre_xy_mm'][0] for island in report['islands']]
    for stroke in strokes[:[s.kind for s in strokes].index('spiral', 1)]:
        if stroke.kind == 'front':
            xs = [x for x, _ in stroke.points]
            assert abs(sum(xs)/len(xs) - centre_x[0]) < abs(sum(xs)/len(xs) - centre_x[1])


def test_stay_down_link_routes_round_stock_and_refuses_what_it_cannot_check():
    clear = Polygon([(0, 0), (10, 0), (10, 10), (7, 10), (7, 3), (3, 3), (3, 10), (0, 10)])
    stock = box(4, 4, 6, 12)  # One unit of cutter radius fits between it and each leg.
    assert stay_down_link(clear, stock, 1., (1., 1.), (9., 1.)) == [(1., 1.), (9., 1.)]
    route = stay_down_link(clear, stock, 1., (1.5, 9.), (8.5, 9.))
    assert route[0] == (1.5, 9.) and route[-1] == (8.5, 9.) and len(route) > 2
    assert clear.buffer(2e-3).covers(LineString(route)) and LineString(route).distance(stock) >= 1. - 5e-3
    assert LineString(route).length < 25.
    why = {}
    assert stay_down_link(clear, box(4, 2.5, 6, 12), 1., (1.5, 9.), (8.5, 9.), why=why) is None
    assert stay_down_link(unary_union([box(0, 0, 2, 2), box(5, 0, 7, 2)]), stock, 1., (1., 1.), (6., 1.), why=why) is None
    assert why == {'route_touches_stock': 1, 'separate_cleared_areas': 1}


def test_small_pocket_is_cleared_under_the_contact_limit(tmp_path):
    pocket = box(0, 0, 18, 14)
    strokes, residual, report = clear_pocket(pocket, 2., sample_step=.2)
    assert strokes[0].kind == 'spiral' and report['islands'][0]['accepted']
    assert report['cleared_fraction'] > .95
    assert report['peak_contact_deg'] <= 60.
    assert all(stroke.peak_deg <= 60. for stroke in strokes)
    assert 0 < report['mean_contact_deg'] <= report['mean_contact_while_cutting_deg'] < report['peak_contact_deg']
    assert .5 < report['share_of_cut_feed_in_contact'] <= 1.
    links = [stroke for stroke in strokes if stroke.kind == 'link']
    assert report['stay_down_links'] == len(links) > 0
    assert report['retract_rapids'] <= 2 and report['retract_reasons']['first_cut'] == 1
    for before, link in zip(strokes, strokes[1:]):
        if link.kind == 'link':
            assert link.points[0] == before.points[-1]
    assert report['spiral_feed_mm'] > .35*report['cut_feed_mm']
    allowed = unary_union(center_regions(pocket, 2.)).buffer(2e-3)
    assert all(allowed.covers(LineString(stroke.points)) for stroke in strokes)
    assert clearance(allowed, residual, 2.).area > .9*allowed.area
    review = tmp_path / 'wave.nc'
    write_review(review, pocket, strokes, residual, report)
    text = review.read_text('ascii')
    assert text.startswith('(DEBUG ONLY') and 'helix entries omitted' in text
    assert sum(line.startswith('G0 ') for line in text.splitlines()) == report['retract_rapids'] and review.with_suffix('.svg').is_file()
    with pytest.raises(FileExistsError):
        write_review(review, pocket, strokes, residual, report)
