import math

import numpy as np

import pytest
from shapely import segmentize
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from tools.check_hsm_neck import neck_fixture
from tools.hsm_center_regions import center_regions
from tools.hsm_contact_replay import indexed_contact
from tools.hsm_wavefront import (along_wall, bow_across, choose_seeds, clear_pocket, clearance, cut, cutting_pieces, eased,
                                 channel_stretches, clear_depths, spiral_pitch, convex_corners, motion_time, smooth_link, write_program, corner_pecks, CORNER_DEPTH, round_a_boss,
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


def test_spiral_that_spans_a_channel_round_a_boss_sends_one_front_one_way():
    # Regression: in a ring the two sides of the spiral each sent a front round the boss; they met
    # head-on on the far side in a pinch of small wobbling cuts (102 of 411 arcs at 0.2 mm or less).
    ring = Point(25, 25).buffer(22, quad_segs=64).difference(Point(25, 25).buffer(12, quad_segs=64))  # cutter centres
    rings = [LineString(ring.exterior.coords), LineString(ring.interiors[0].coords)]
    behind, ahead = round_a_boss((42., 25.), 5. - 1e-3, rings, 2.)
    assert behind.covers(Point(42, 22.9)) and not behind.covers(Point(42, 23.1))  # A cutter radius behind the centre.
    assert not behind.covers(Point(42, 30)) and behind.covers(Point(25, 0))
    assert ahead == pytest.approx((42., 30.), abs=.1)  # The polygon wall makes the nearest point a little off.
    assert round_a_boss((42., 25.), 3., rings, 2.) is None  # Does not reach both walls.
    slot = [LineString(box(2, 2, 78, 10).exterior.coords)]
    assert round_a_boss((20., 6.), 4. - 1e-3, slot, 2.) is None  # Both walls are one ring: nothing to go round.


def test_starts_round_a_boss_each_take_one_stretch_forward_into_the_next_spiral():
    # Regression: four corner starts each sent fronts both ways; they met head-on between the corners
    # in pinches of small arcs, as in the ring. Now the channel is cut across at every start.
    square = box(0, 0, 50, 50).difference(box(17, 17, 33, 33))
    allowed = unary_union(center_regions(square, 2.))
    seeds = choose_seeds(allowed, min_radius=2.)
    stretches = channel_stretches(allowed, seeds, 2.)
    assert sorted(rank for *_, rank in stretches) == [0, 1, 2, 3]
    pieces = [piece for _, _, piece, _ in stretches]
    assert sum(piece.area for piece in pieces) == pytest.approx(allowed.area, rel=1e-6)  # The channel, once.
    for ((x, y), room), (stretch, ahead, piece, rank) in zip(seeds, stretches):
        following = seeds[[r for *_, r in stretches].index((rank+1) % 4)][0]
        assert stretch.buffer(1e-6).covers(Point(following))  # Runs on into the next spiral ...
        assert math.dist(ahead, following) < math.dist((x, y), following)  # ... going forward.
        assert piece.distance(Point(x, y)) < 1e-6
    assert channel_stretches(unary_union(center_regions(box(0, 0, 60, 30), 2.)), [((20, 15), 13.), ((40, 15), 13.)], 2.) is None


def test_bow_crosses_a_curved_channel_square_to_its_walls():
    # Regression: the crossing followed the slant of the front, so in a ring (and round the corners of
    # a boss) each bow ran a little further from square; here the front leans 6 degrees.
    lo, hi = 12., 22.
    ring = Point(0, 0).buffer(24, quad_segs=64).difference(Point(0, 0).buffer(10, quad_segs=64))
    allowed = Point(0, 0).buffer(hi, quad_segs=64).difference(Point(0, 0).buffer(lo, quad_segs=64))
    rings = [LineString(allowed.exterior.coords), LineString(allowed.interiors[0].coords)]
    a0, a1 = math.radians(10), math.radians(4)
    run = [(r*math.cos(a0 + (a1-a0)*(r-lo)/(hi-lo)), r*math.sin(a0 + (a1-a0)*(r-lo)/(hi-lo)))
           for r in [lo + k*(hi-lo)/20 for k in range(21)]]
    sector = [(0, 0)] + [(30*math.cos(t), 30*math.sin(t)) for t in [-1 + k*.05 for k in range(int((1+a1-.03)/.05)+1)]]
    part = Polygon(sector).intersection(allowed)
    bow = bow_across(run, rings, part, ring.difference(part.buffer(2.)), 2., allowed, 2*2./.7, .75, .75)
    middle = [q for q in bow if 16 < math.hypot(*q) < 18]
    off = [abs(math.degrees((math.atan2(q[1]-p[1], q[0]-p[0]) - math.atan2(p[1], p[0]) + math.pi/2) % math.pi - math.pi/2))
           for p, q in zip(middle, middle[1:])]
    assert max(off) < 2.  # Radial, not along the 6 degree lean (10 degrees off before).


def test_corner_creep_reaches_the_corner_in_steps_no_deeper_than_the_limit():
    # Regression: the fronts swallow a corner once it is within a stepover, so the cutter centre never
    # got there; 1-3 mm² were left in every square corner of the test shapes.
    pocket = box(0, 0, 30, 20).buffer(-2., join_style=2).buffer(2., quad_segs=16)  # corners of cutter radius
    allowed = pocket.buffer(-2., join_style=2)
    corners = convex_corners(LineString(allowed.exterior.coords))
    assert len(corners) == 4
    (vertex, along), = [c for c in corners if c[0] == pytest.approx((28., 18.), abs=.01)]
    cleared = unary_union([box(2, 2, 28, 17.2), box(2, 2, 27.2, 18)])  # centres; the corner itself missed
    stock = pocket.difference(cleared.buffer(2., quad_segs=32))
    assert Point(vertex).distance(stock) < 1.5
    cuts = 0
    for path in corner_pecks(vertex, along, stock, 2., LineString(allowed.exterior.coords)):
        assert path is not None  # Never stuck here.
        assert 2. - min(Point(q).distance(stock) for q in path) <= CORNER_DEPTH + 1e-9
        assert path[0] == path[-1]  # Backs out along its own track.
        stock = stock.difference(LineString(path).buffer(2., quad_segs=32))
        cuts += 1
    assert 1 < cuts < 20 and Point(vertex).distance(stock) > 2. - .02


def test_square_cornered_pocket_is_cleared_into_its_corners():
    strokes, residual, report = clear_pocket(box(0, 0, 30, 20), 2.)
    assert report['reachable_residual_mm2'] < .1 and report['corners']['visits'] > 0
    assert report['retract_rapids'] == 1 and report['peak_contact_deg'] <= 60.


def test_fast_contact_measure_agrees_with_the_step_by_step_replay():
    # chunk_contact measures the forward half of the cutter against the stock before the stretch; the
    # reference subtracts the sweep after every sample. They must agree, the reference reading a
    # little high from its polygonal sweeps.
    stock = box(0, 0, 40, 20).difference(box(10, 3, 14, 30))
    paths = [[(-5., -1.5), (45., -1.5)],                                                # side cut, 0.5 mm deep
             [(20 + 6*math.cos(k*math.pi/60), -4 + 6*math.sin(k*math.pi/60)) for k in range(61)],  # arc into stock
             [(k*.2 - 5, .8*math.sin((k*.2 - 5)/2.) - 1.3) for k in range(250)]]        # wavering depth
    for path in paths:
        path = list(segmentize(LineString(path), .2).coords)
        reference = []
        for _, angle, _ in indexed_contact(path, stock, 2., .1, 16):
            reference.append(angle)
        tally = [0., 0., 0.]
        peak, after = cut(path, stock, 2., .1, tally=tally)
        assert peak == pytest.approx(max(reference), abs=1.5)
        assert tally[0]/tally[1] == pytest.approx(sum(reference)/len(reference), abs=.7)
        assert after.area == pytest.approx(stock.difference(LineString(path).buffer(2., quad_segs=32)).area, abs=.05)
    assert math.acos(1 - .5/2.) < math.radians(cut(paths[0], stock, 2., .1)[0]) < math.acos(1 - .5/2.) + .03  # Analytic.


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
    assert report['wall_profile']['feed_mm'] < .05*report['cut_feed_mm']  # The finish only touches leftovers.
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


def test_links_leave_and_join_cuts_tangentially_and_stay_in_cleared_space():
    clear = box(0, 0, 20, 20)
    route = [(2., 2.), (2., 18.), (18., 18.)]
    curve = smooth_link(route, (1., 0.), (0., -1.), clear, box(30, 30, 31, 31), 1.)
    assert curve[0] == route[0] and curve[-1] == route[-1]
    first, last = (curve[1][0]-curve[0][0], curve[1][1]-curve[0][1]), (curve[-1][0]-curve[-2][0], curve[-1][1]-curve[-2][1])
    assert first[0] > 0 and abs(first[1]) < first[0]  # Leaves along the cut before ...
    assert last[1] < 0 and abs(last[0]) < -last[1]     # ... and arrives along the cut after.
    assert clear.buffer(1e-3).covers(LineString(curve))
    turns = [abs((math.atan2(c[1]-b[1], c[0]-b[0]) - math.atan2(b[1]-a[1], b[0]-a[0]) + math.pi) % (2*math.pi) - math.pi)
             for a, b, c in zip(curve, curve[1:], curve[2:])]
    assert max(turns) < math.radians(45)  # No sharp corner left (the route turned 90 degrees).
    blocked = smooth_link(route, (1., 0.), (0., -1.), clear, box(0, 0, 20, 20).difference(box(1, 1, 3, 19)).difference(
        box(1, 17, 19, 19)), 1.)
    assert blocked == route  # Where a curve would touch stock, the checked route stays as it was.


def test_fast_polyline_pieces_match_shapely_substring():
    from shapely.ops import substring
    from gcodeproducer.core.cam.wavefront.polyline import stretch
    line = LineString([(0, 0), (3, 0), (3, 4), (7, 4), (7, 9)])
    for a, b in ((0., 2.), (1., 6.5), (3., 7.), (2.5, line.length), (0., line.length), (4., 4.), (6.5, 1.)):
        expected = list(substring(line, a, b).coords) if a != b else [substring(line, a, b).coords[0]]*2
        assert np.allclose(stretch(line, a, b), expected)  # An empty stretch still makes a line.


def test_levels_planned_in_workers_match_planning_them_one_by_one(monkeypatch):
    from gcodeproducer.core.cam import Operation
    from gcodeproducer.core.cam.wavefront import plan_level, plan_levels
    op = Operation(kind='waterfall', strategy='adaptive')
    region = box(0, 0, 16, 12)
    levels = [(region, None, 1.), (region, region.difference(box(0, 0, 6, 12)), 1.)]
    one_by_one = [plan_level(op, r, 4., m, d) for r, m, d in levels]
    pooled = plan_levels(op, levels, 4.)
    for (paths, summary), (other, again) in zip(one_by_one, pooled):
        assert summary['fronts'] == again['fronts'] and len(paths) == len(other)
        assert all(np.allclose(p.points, q.points) and p.closed == q.closed for p, q in zip(paths, other))
    assert pooled[1][1]['fronts'] < pooled[0][1]['fronts']  # Less material at the second level.
    monkeypatch.setenv('GCODEPRODUCER_WORKERS', '0')  # No worker processes: planned here, same result.
    assert [s['fronts'] for _, s in plan_levels(op, levels, 4.)] == [s['fronts'] for _, s in pooled]


def test_engaged_width_is_the_radial_depth_share_of_the_diameter():
    stock = box(0, 0, 40, 20)
    for depth in (.2, .5, 1., 2., 4.):
        path = list(segmentize(LineString([(-5, -2 + depth), (45, -2 + depth)]), .2).coords)
        assert cut(path, stock, 2., .1, measure='width')[0] == pytest.approx(depth/4, abs=.01)


def test_spiral_laps_widen_with_the_radius_at_an_even_engagement():
    pitch = spiral_pitch(2., 1 - 2*.1, .5)  # 10 % width
    assert pitch(2.) < pitch(6.) < pitch(30.) <= .5
    assert pitch(1e6) == pytest.approx(.4, abs=.01)  # A straight wall: 10 % of a 4 mm cutter.


def test_motion_time_follows_a_trapezoid_and_slows_for_corners():
    total, _ = motion_time([(0., 0.), (100., 0.)], [600.], 100., .02)  # 10 mm/s, 100 mm/s²
    assert total == pytest.approx(100/10 + 10/100, rel=1e-6)  # Cruise plus the time lost speeding up and down.
    square = [(0., 0.), (50., 0.), (50., 50.), (0., 50.)]
    straight, _ = motion_time([(0., 0.), (150., 0.)], [600.]*1, 100., .02)
    cornered, _ = motion_time(square, [600.]*3, 100., .02)
    assert cornered > straight + .1  # Each square corner is taken at about 2 mm/s, not 10.
    rounded = [(25*math.cos(t), 25*math.sin(t)) for t in [k*math.pi/40 for k in range(41)]]
    assert motion_time(rounded, [600.]*40, 100., .02)[0] < LineString(rounded).length/10 + .5


def test_levels_make_one_program_with_helices_and_safe_rapids(tmp_path):
    from gcodeproducer.core.gcode.program import GCodeProgram
    from gcodeproducer.core.gcode.simulation import simulate
    from gcodeproducer.core.gcode.time_estimate import estimate_time
    pocket = box(0, 0, 18, 14)
    levels = clear_depths(pocket, 2., bottom=-3., step_down=2., sample_step=.2)
    assert [round(z, 6) for z, *_ in levels] == [-1.5, -3.]  # Equal levels, none deeper than the step.
    assert all(report['reachable_residual_mm2'] < .1 for *_, report in levels)
    assert levels[1][3]['reused_from_mm'] == pytest.approx(-1.5)  # One outline: planned once, moved down.
    shapes = clear_depths(lambda z: box(0, 0, 18 + z, 14), 2., bottom=-3., step_down=2., sample_step=.2)
    assert 'reused_from_mm' not in shapes[1][3] and shapes[1][1] != shapes[0][1]  # A slice per level.
    program = write_program(tmp_path / 'levels.nc', levels)
    parsed = GCodeProgram.from_file(str(program))
    sim = simulate(parsed)
    assert min(sim.z) == pytest.approx(-3.) and max(sim.z) == pytest.approx(2.)
    lines = parsed.lines
    for i, line in enumerate(lines):
        if line.cmd == 'G0' and ('X' in line.params or 'Y' in line.params):
            assert sim.z[i] == pytest.approx(2.)  # Every rapid across the pocket is above the top.
        if line.cmd == 'G1' and ('X' in line.params or 'Y' in line.params):
            assert sim.z[i] <= -1.5 + 1e-6 or 'Z' in line.params  # Feeds across run at a level or on a helix.
    assert program.read_text().count('(Helix entry)') == sum(len(report['entries']) for *_, report in levels)
    # The program's own time estimate agrees with the planner's.
    expected = sum(report['machine_time']['total_s'] for *_, report in levels)
    motion = {'print_acceleration': 500., 'travel_acceleration': 500., 'junction_deviation': .02}
    assert estimate_time(parsed, sim, motion) == pytest.approx(expected, rel=.08)
    with pytest.raises(FileExistsError):
        write_program(program, levels)


def test_small_pocket_is_cleared_under_the_contact_limit(tmp_path):
    pocket = box(0, 0, 18, 14)
    strokes, residual, report = clear_pocket(pocket, 2., sample_step=.2)
    assert strokes[0].kind == 'spiral' and report['islands'][0]['accepted']
    assert report['cleared_fraction'] > .95
    assert report['peak_contact_deg'] <= 60.
    assert all(stroke.peak_deg <= 60. for stroke in strokes if stroke.kind != "corner")  # Corners go by depth.
    assert 0 < report['mean_contact_deg'] <= report['mean_contact_while_cutting_deg'] < report['peak_contact_deg']
    assert .5 < report['share_of_cut_feed_in_contact'] <= 1.
    links = [stroke for stroke in strokes if stroke.kind == 'link']
    assert report['stay_down_links'] == len(links) > 0
    assert report['retract_rapids'] <= 2 and report['retract_reasons']['first_cut'] == 1
    for before, link in zip(strokes, strokes[1:]):
        if link.kind == 'link':
            assert link.points[0] == before.points[-1]
    assert report['spiral_feed_mm'] > .3*report['cut_feed_mm']
    timing = report['machine_time']
    assert timing['total_s'] == pytest.approx(sum(timing[k] for k in ('cutting_s', 'links_s', 'helix_s', 'rapids_s')))
    assert timing['cutting_s'] >= 60*report['cut_feed_mm']/timing['machine']['cut_feed_mm_min']  # 0.45 mm spiral since finer stepovers
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


def test_rest_passes_finish_what_the_fronts_leave_and_report_it():
    from pathlib import Path
    from shapely import from_wkt
    slot = from_wkt(Path('examples/hsm-shapes/slot.wkt').read_text())
    _, left_alone, report = clear_pocket(slot, 2., rest_finish=False)
    assert left_alone.area > .1 and report['rest']['pieces'] == 0
    strokes, residual, report = clear_pocket(slot, 2.)
    rest = report['rest']
    assert residual.area < .05 and report['stop'] == 'front_exhausted'
    assert rest['pieces'] > 0 and rest['stock_before_mm2'] > .1 and rest['stock_after_mm2'] < .05
    assert 0 < rest['feed_mm'] < .02*report['cut_feed_mm']        # a few extra moves
    assert rest['over_limit_mm'] <= rest['feed_mm'] and rest['peak'] > 0
    assert sum(s.kind == 'rest' for s in strokes) == rest['pieces']


@pytest.mark.parametrize('ends', [((0., 0.), (1., 0.), (0., -3.), (-1., 0.)), ((0., 0.), (1., 0.), (5., 5.), (0., 1.)),
                                  ((0., 0.), (0., 1.), (1., 0.), (0., -1.))])
def test_turn_round_leaves_and_joins_along_the_headings_without_a_corner(ends):
    from gcodeproducer.core.cam.wavefront.links import turn_round
    start, leaving, end, arriving = ends
    paths = turn_round(start, leaving, end, arriving, 1.)
    assert paths
    for path in paths:
        q = np.asarray(path, float)
        steps = np.diff(q, axis=0)
        unit = steps/np.linalg.norm(steps, axis=1)[:, None]
        assert np.allclose(q[0], start) and np.allclose(q[-1], end)
        assert unit[0] @ np.asarray(leaving) > .9 and unit[-1] @ np.asarray(arriving) > .9
        assert (unit[:-1]*unit[1:]).sum(axis=1).min() > math.cos(math.radians(20))   # no kink anywhere


@pytest.mark.parametrize('name', ['rectangle', 'cross'])
def test_links_leave_and_join_the_cuts_without_reversing(name):
    from pathlib import Path
    from shapely import from_wkt
    from gcodeproducer.core.cam.wavefront.links import heading
    pocket = from_wkt(Path(f'examples/hsm-shapes/{name}.wkt').read_text())
    strokes, _, _ = clear_pocket(pocket, 2.)
    turns = []
    for before, link, after in zip(strokes, strokes[1:], strokes[2:]):
        if link.kind != 'link':
            continue
        for a, b in ((heading(before.points, True), heading(link.points, False)),
                     (heading(link.points, True), heading(after.points, False))):
            turns.append(math.degrees(math.acos(max(-1., min(1., a[0]*b[0] + a[1]*b[1])))))
    turns = np.asarray(turns)
    assert len(turns) > 50
    # Before 0.2.35 a tenth of these turned back on themselves (rectangle 9.5 %, cross 7 %), where a
    # cut ends or starts against a wall and no curve could join it tangentially.
    assert (turns > 150).mean() < .01
    assert (turns < 30).mean() > .9            # almost all leave and join along the cut
