"""Wavefront clearing of a planar pocket, and of a pocket in levels."""
import math
import time
import numpy as np

from shapely import distance, points, segmentize
from shapely.geometry import LineString, Point
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, unary_union

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.geometry.polygon_parts import polygons
from .stroke import Stroke
from .regions import roll_off_walls, spiral_pitch, clear_of, center_regions, find_lobes, choose_seeds, spiral_out, clearance, grow_clearance, fronts, eased, without_slivers, sweep, round_a_boss, channel_stretches
from .contact import cutting_pieces, cut
from .walls import wall_ends, convex_corners, corner_pecks
from .links import stay_down_link, smooth_link, heading
from .timing import machine_time
from .wavefront_constants import (CORNER_RUN_IN, RESTARTS, RESTART_MM2, SPIRAL_LARGEST, STEPOVERS, SPIRAL_SCALES, STUCK_SPOT, SWEEP_SEGMENTS, WALL_TOLERANCE, MIN_GAIN_MM2, PROFILE_CHUNK, ROLL_STEPOVER, STEADY_STEPOVER, RAISE_PATIENCE, RAISE_PATIENCE_MAX, PROFILE_INSETS, REST_MM2, REST_STEPOVER, REST_PASSES, FRONT_RUN_OUT, BOTH_WAYS_GAIN,
                                  LINK_RUN_MIN, LINK_RUN_POINTS, LINK_TOLERANCE, LINK_WALL_NEAR, LINK_WALL_RUN, LINK_WALL_TURN)


def clear_pocket(pocket, radius, *, limit=60., sample_step=.1, stepovers=STEPOVERS, blend=3.,
                 islands=None, placement='lobes', wall_pull_back=True, wall_profile=True, trace=None, top=0., depth=-2., lead_angle=2.5, time_budget=None,
                 smooth_links=True, material=None, measure='angle', end_allowance=None, rest_finish=True,
                 leave_wall_crescents=False, both_ways=False):
    """Return (strokes, residual, report) for one target plane.

    both_ways: cut an open front from whichever end is nearer the cutter
    (stock on the left from one end, on the right from the other), so it is
    never travelled back over cut ground just to start from the same end.

    The stock starts as the whole pocket, or as the part of it inside
    material where earlier cuts or levels already removed some. limit is
    the largest contact angle in degrees, or with measure='width' the largest
    engaged width as a share of the cutter diameter (see contact.cut).
    end_allowance, as (mm, factor), lets each front's first and last mm reach
    factor times the limit (see contact.cut).
    """
    allowed = unary_union(center_regions(pocket, radius))
    wall = allowed.boundary
    rings = [LineString(r.coords) for g in polygons(allowed) for r in (g.exterior, *g.interiors)]
    reachable = allowed.buffer(radius, quad_segs=SWEEP_SEGMENTS)
    # Leaving the wall alone: stock within a cutter radius of the pocket wall is what only a cutter
    # running along the wall takes - the crescents fronts leave when they roll off short of it.
    # It is reported, not chased; Overcut takes it where the wall is not the part's.
    wall_band = pocket.boundary.buffer(radius, quad_segs=8) if leave_wall_crescents else None

    def open_stock(geometry):
        """Stock that still has to be taken: all of it, or what lies off the wall band."""
        left = geometry.intersection(reachable)
        return left if wall_band is None else left.difference(wall_band)
    start = pocket if material is None else pocket.intersection(material)
    stock = start
    strokes, island_reports = [], []
    travel = {'rapids': 0, 'links': 0}
    contact = [0., 0., 0.]  # committed cuts only: angle x distance, distance, distance in contact

    def count(tally):
        for k in range(3):
            contact[k] += tally[k]

    refused = {}
    entries = []  # {'stroke': index of the first cut after the helix, 'helix_xyz': helix points}
    cleared = [None]  # clearance for the live stock; None until asked for after a wholesale change

    def stock_clear():
        if cleared[0] is None:
            cleared[0] = clearance(allowed, stock, radius)
        return cleared[0]

    run_off = [None]  # the air the last front's own shape ran on into after its cut was trimmed

    def clear_run(points):
        """The stretch, if it is long enough to turn on and clear of live stock."""
        if points is None or len(points) < 2 or LineString(points).length < LINK_RUN_MIN:
            return None
        return points if LineString(points).distance(stock) >= radius - 5*LINK_TOLERANCE else None

    def worst_turn(link, before, after):
        """Largest change of heading, in degrees, where the link leaves one cut and joins the next."""
        def angle(a, b):
            return math.degrees(math.acos(max(-1., min(1., a[0]*b[0] + a[1]*b[1]))))
        return max(angle(heading(before, True), heading(link, False)),
                   angle(heading(link, True), heading(after, False)))

    def along_the_wall(point, onward):
        """A stretch of clean wall ending at a cut that starts on the wall, to come in along; or None.

        A cut that starts square to a wall cannot be met from behind; coming
        along the wall into it turns a reversal into a quarter turn. The side
        whose last step turns least into the cut's heading is used.
        """
        if not rings:
            return None
        ring = min(rings, key=lambda r: r.distance(Point(point)))
        if ring.distance(Point(point)) > LINK_WALL_NEAR:
            return None
        here, best = ring.project(Point(point)), None
        for sign in (1, -1):
            run = [tuple(ring.interpolate((here - sign*d) % ring.length).coords[0])
                   for d in np.linspace(LINK_WALL_RUN, 0., 13)]
            run[-1] = tuple(point)
            if clear_run(run) is None:
                continue
            into = heading(run, True)
            turn = into[0]*onward[0] + into[1]*onward[1]
            if best is None or turn > best[0]:
                best = (turn, run)
        return None if best is None or best[0] < LINK_WALL_TURN else best[1]

    def commit(kind, path, stepover, peak, run_in=None):
        """Join the cut to the previous one through cleared space, else count a retract and rapid.

        run_in is the air the cut's own shape runs in from before it was trimmed to the stock it
        meets (a hook along a wall, a roll-on from the old front). A link that cannot join the cut
        along its heading - a cut that starts square to a wall cannot be met from behind - joins
        that run-in instead and follows it in; likewise it may leave along the last front's run-off.
        """
        if strokes:
            start, end = strokes[-1].points[-1], path[0]
            route = stay_down_link(stock_clear(), stock, radius, start, end, why=refused)
            if route is None:
                travel['rapids'] += 1
            else:
                travel['links'] += 1
                if smooth_links:
                    smooth = smooth_link(route, heading(strokes[-1].points, True), heading(path, False),
                                         allowed, stock, radius)
                    tail, lead = clear_run(run_off[0]), clear_run(run_in)
                    if smooth is route and lead is None:
                        lead = along_the_wall(end, heading(path, False))
                    if smooth is route and (tail is not None or lead is not None):
                        a = tail[-1] if tail is not None else start
                        b = lead[0] if lead is not None else end
                        detour = stay_down_link(stock_clear(), stock, radius, a, b)
                        if detour is not None:
                            out = heading(tail if tail is not None else strokes[-1].points, True)
                            into = heading(lead if lead is not None else path, False)
                            curve = smooth_link(detour, out, into, allowed, stock, radius)
                            joined = ((tail[:-1] if tail is not None else [])
                                      + list(curve) + (lead[1:] if lead is not None else []))
                            # Keep the way round by the run-in/off if it turns less sharply where it
                            # joins and leaves the cuts than the direct route does.
                            direct_turn = worst_turn(route, strokes[-1].points, path)
                            # A small heading improvement is not worth a long loop. Preserve
                            # the tangent approach when the alternative is a sharp reversal.
                            if ((direct_turn > 90 or LineString(joined).length <= LineString(route).length + radius)
                                    and worst_turn(joined, strokes[-1].points, path) < direct_turn):
                                smooth = joined
                    route = smooth
                strokes.append(Stroke('link', route, 0., 0.))
        else:
            travel['rapids'] += 1
        run_off[0] = None
        strokes.append(Stroke(kind, path, stepover, peak))

    started = time.time()

    def out_of_time():
        return time_budget is not None and time.time()-started > time_budget

    seeds = choose_seeds(allowed, islands, min_radius=radius, placement=placement)

    def owner(xy):
        """Island whose spiral disc is nearest; decides who finishes shared ground."""
        return min(range(len(seeds)), key=lambda k: math.dist(xy, seeds[k][0]) - seeds[k][1])

    def wave(index, centre, own, shared, focus=None, region=None):
        """Grow one island as if it were alone, cutting only where real stock remains.

        own is the stock this island would see by itself; it keeps the fronts
        concentric when they reach space another island has opened. A shared
        island leaves arcs that mostly belong to a neighbour for that neighbour.
        region, if given, is the stretch of the centre region this island works; its edges that are
        not pocket wall are not fronts.
        """
        nonlocal stock
        here = allowed if region is None else region
        edge = wall if region is None else region.boundary
        start, passes, arcs, blocked = 0, 0, 0, False
        own_clear = clearance(here, own, radius)
        steady, since, patience = 0, 0, RAISE_PATIENCE  # stepover level in use; passes at it; passes to wait
        # focus is the middle of the front last cut. Where it is given, that front is followed until it
        # is finished; elsewhere the front nearest the cutter goes next, which keeps links short and
        # measured better on the L-shape, cross and square with a boss.
        follow = focus is not None
        # Spots no stepover could take, kept out of later fronts so the rest of the pocket goes on.
        stuck, stuck_zone = [], None
        while not out_of_time():
            parts = [g for g in polygons(own_clear) if g.area > 1e-6]
            if not parts:
                break
            part = min(parts, key=lambda g: g.distance(Point(centre)))
            progressed, used, zone, blocked = False, None, None, False
            for level in range(start, len(stepovers)):
                stepover = stepovers[level]
                grown = part.buffer(stepover, quad_segs=SWEEP_SEGMENTS).intersection(here)
                runs = fronts(part, grown, edge, zone=zone)
                if stuck_zone is not None:
                    runs = clear_of(runs, stuck_zone)
                failed, halt, peaks = [], False, []
                while runs and not halt:
                    # Stay with one front. Round a boss two fronts set off opposite ways; taking whichever
                    # is nearer advances both, and they meet head-on on the far side in a narrowing pinch.
                    # One front followed all the way round breaks through into the space the spiral opened.
                    if focus is None:
                        at = strokes[-1].points[-1] if strokes else centre
                        pick = min(range(len(runs)), key=lambda k: math.dist(at, runs[k][0][0]))
                    else:
                        pick = min(range(len(runs)), key=lambda k: LineString(runs[k][0]).distance(Point(focus)))
                    run, closed = runs.pop(pick)
                    if both_ways and not closed and strokes:
                        # Cut it from whichever end is nearer: the far end would mean travelling the
                        # whole front back over cut ground first. Against its run that is conventional.
                        cutter = strokes[-1].points[-1]
                        if math.dist(cutter, run[-1]) + BOTH_WAYS_GAIN*radius < math.dist(cutter, run[0]):
                            run = run[::-1]
                    # Sweep the wall at the arc ends; only at ROLL_STEPOVER or below fall back to
                    # rolling off before the wall, so a lighter cut gets to try the wall first.
                    if wall_pull_back and not closed:
                        ends, others = [], []
                        shapes = [wall_ends(run, part, own, radius, allowed, rings, blend, note=ends, alternatives=others),
                                  *others]
                        if stepover <= ROLL_STEPOVER or level == len(stepovers)-1:
                            shapes.append(lambda run=run, closed=closed: eased(run, closed, part, allowed, blend))
                    elif not closed:
                        # No hooks: leave the wall alone; the front turns off short of it toward
                        # cleared ground and the crescent there is left.
                        shapes = [roll_off_walls(eased(run, closed, part, allowed, blend), part, allowed, wall, radius)]
                    else:
                        shapes = [eased(run, closed, part, allowed, blend)]
                    done, skip, near_stuck, before = None, False, None, len(peaks)
                    if stuck_zone is not None:
                        shapes.append(lambda run=run, closed=closed: eased(run, closed, part, allowed, blend))
                    for path in shapes:
                        # Fallback shapes are callables, built only when the shapes before them fail.
                        path = path() if callable(path) else path
                        if stuck_zone is not None and len(path) > 1 and LineString(path).intersects(stuck_zone):
                            # An end along the wall would run into a spot left as stuck. If no shape is
                            # left, the spot grows to take this front's end in too.
                            touch = nearest_points(LineString(path), stuck_zone)[0]
                            near_stuck = (touch.x, touch.y)
                            continue
                        if len(path) < 2:
                            continue
                        pieces = cutting_pieces(path, stock, radius, run_out=FRONT_RUN_OUT*radius, run_in=1.)
                        if shared and pieces:
                            points = [q for piece in pieces for q in piece]
                            if sum(owner(q) == index for q in points) < len(points)/2:
                                skip = True  # A neighbour finishes this stretch; do not advance through it.
                                break
                        trial, done = stock, []
                        for piece in pieces:
                            at, tally = [], [0., 0., 0.]
                            peak, after = cut(piece, trial, radius, sample_step, where=at, tally=tally, stop_above=limit,
                                              measure=measure, ends=end_allowance)
                            if peak > limit:
                                done = None
                                if at:
                                    spot = LineString(piece).interpolate(at[0])
                                    peaks.append((spot.x, spot.y))
                                if trace is not None:
                                    trace.append({'island': index, 'stepover_mm': stepover, 'retry': zone is not None,
                                                  'wall_ended': path is shapes[0] and len(shapes[0]) > 0
                                                  and wall_pull_back and not closed,
                                                  'ends': list(ends) if path is shapes[0] and wall_pull_back and not closed else None,
                                                  'run_start_xy': run[0], 'run_end_xy': run[-1], 'peak_deg': peak,
                                                  'peak_at_mm': at[0] if at else None,
                                                  'piece_mm': LineString(piece).length,
                                                  'piece_end_xy': piece[-1], 'outcome': 'over_limit'})
                                break
                            if trial.area - after.area >= MIN_GAIN_MM2:
                                done.append((piece, peak, tally))
                            trial = after
                        if done is not None:
                            break
                    if skip:
                        continue
                    if done is None:
                        failed.append(LineString(run))
                        if near_stuck is not None and len(peaks) == before:
                            peaks.append(near_stuck)
                        # Retry this front lighter before turning to another; only when it cannot be
                        # cut at all do the others get their turn. Trying the others at the same heavier
                        # stepover first refuses them too, and the lighter retry then cuts one front in
                        # each arm in turn, crossing the pocket between arms on every pass.
                        halt = zone is None and level < len(stepovers)-1
                        continue
                    if trace is not None:
                        trace.append({'island': index, 'stepover_mm': stepover, 'retry': zone is not None,
                                      'wall_ended': path is shapes[0] and wall_pull_back and not closed,
                                      'run_start_xy': run[0], 'run_end_xy': run[-1], 'pieces': len(done), 'path_mm': LineString(path).length,
                                      'path_end_xy': path[-1], 'outcome': 'cut' if done else 'air'})
                    for piece, peak, tally in done:
                        at = path.index(piece[0]) if piece[0] in path else None
                        ahead = path[max(0, at - LINK_RUN_POINTS):at+1] if at is not None and at > 0 else None
                        commit('front', piece, stepover, peak, run_in=ahead)
                        to = path.index(piece[-1]) if piece[-1] in path else None
                        run_off[0] = path[to:to + LINK_RUN_POINTS + 1] if to is not None and to < len(path)-1 else None
                        count(tally)
                    if done:
                        trial = without_slivers(trial)
                        cleared[0] = grow_clearance(stock_clear(), allowed, trial, path, radius)
                    stock = trial
                    before = own.area
                    own = sweep(path, own, radius)
                    own_clear = grow_clearance(own_clear, here, own, path, radius)
                    # A pass through air counts only if it moved the front on; otherwise it would repeat for ever.
                    moved = bool(done) or before - own.area > MIN_GAIN_MM2
                    progressed = progressed or moved
                    followed = focus is not None and moved
                    if follow and (done or followed):
                        middle = LineString(run).interpolate(.5, normalized=True)
                        focus = (middle.x, middle.y)
                    if done:
                        arcs += len(done)
                        used = level if used is None else used
                    # Stay with this stretch of front, also while it passes through space already
                    # open; the others wait their turn.
                    halt = zone is None and (bool(done) or followed)
                blocked = bool(failed)
                if failed and level == len(stepovers)-1 and peaks:
                    # Even the smallest stepover is refused here: typically a thin wedge where a front
                    # meets the wall at a shallow angle, or a tight inside corner of the stock. Leave
                    # a cutter-sized spot round each refusal and let the fronts go on round it; the
                    # corner moves and the wall finish come back for what is left.
                    stuck.extend(peaks)
                    stuck_zone = unary_union([Point(q).buffer(STUCK_SPOT*radius, quad_segs=8) for q in stuck])
                    progressed, blocked = True, False
                    break
                if not failed or out_of_time():
                    break
                zone = unary_union(failed).buffer(max(1., 2*stepover))
                parts = [g for g in polygons(own_clear) if g.area > 1e-6]
                part = min(parts, key=lambda g: g.distance(Point(centre)))
            if not progressed:
                if focus is None:
                    break
                focus = None  # The front being followed cannot be cut at all: give every front a turn.
                continue
            passes += used is not None
            # Try a larger stepover again only now and then. A front that takes 0.5 mm but not 0.65 mm
            # would otherwise have every pass replayed twice, once to be refused.
            if used is not None:
                if used < steady:
                    steady, since, patience = used, RAISE_PATIENCE, RAISE_PATIENCE  # It took more: try more again at once.
                elif used > steady:
                    steady, since, patience = used, RAISE_PATIENCE, RAISE_PATIENCE  # Dropped: climb back without waiting.
                elif start < steady and stepovers[steady] < STEADY_STEPOVER:
                    since = patience  # A thin peel: keep trying for a thicker one every pass.
                elif start < steady:
                    since, patience = 0, min(2*patience, RAISE_PATIENCE_MAX)  # The larger one was refused: wait longer.
                else:
                    since += 1
            start = max(0, steady-1) if since >= patience else steady
        stuck_spots.extend(stuck)
        return passes, arcs, blocked

    front_passes, any_blocked = 0, False
    stuck_spots = []

    def open_island(centre, room, base=None):
        """Helix and spiral for one start: (centre, spiral reach, island report, own stock, spiral kept)."""
        nonlocal stock
        region = Point(centre).buffer(room)
        entry = seed_entry(region, stock, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        alone = seed_entry(region, start if base is None else base, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        if entry is None or alone is None:
            return None
        centre = tuple(entry.points[-1, :2])
        stock, own = entry.remaining, alone.remaining
        cleared[0] = None
        reach = Point(centre).distance(wall) - 1e-3
        helix = np.asarray(entry.points, float)
        island = {'centre_xy_mm': centre, 'radius_mm': reach,
                  'helix_mm': float(np.linalg.norm(np.diff(helix, axis=0), axis=1).sum()) if len(helix) > 1 else 0.}
        chosen, kept = None, False
        entry_record = {'stroke': None, 'helix_xyz': helix.tolist()}
        entries.append(entry_record)
        # First a spiral whose lap spacing grows with the radius so its cut stays as wide as the
        # limit allows (tight laps round the helix, the full stepover far out); a fixed spacing must
        # suit the tightest lap and is far too close further out.
        spread = 1 - 2*limit if measure == 'width' else math.cos(math.radians(limit))
        path = peak = None
        for scale in SPIRAL_SCALES:
            pitch = spiral_pitch(radius, spread, min(stepovers[0], SPIRAL_LARGEST), scale=scale)
            trial_path = spiral_out(centre, reach, pitch(reach), blend=blend, pitch=pitch)
            tally = [0., 0., 0.]
            peak, trial = cut(trial_path, stock, radius, sample_step, tally=tally, stop_above=limit, measure=measure)
            if peak <= limit:
                path, chosen = trial_path, round(pitch(reach), 3)
                break
        for stepover in stepovers if path is None else ():
            probe = spiral_out(centre, min(reach, 1.8*radius + 3.), stepover, blend=blend)
            if cut(probe, stock, radius, sample_step, stop_above=limit, measure=measure)[0] <= limit:
                chosen = stepover
                break
        if chosen is not None and path is None:
            path = spiral_out(centre, reach, chosen, blend=blend)
            tally = [0., 0., 0.]
            peak, trial = cut(path, stock, radius, sample_step, tally=tally, measure=measure)
        if chosen is not None:
            island.update(stepover_mm=chosen, peak_deg=peak, feed_mm=LineString(path).length,
                          accepted=peak <= limit)
            if peak <= limit:
                commit('spiral', path, chosen, peak)
                entry_record['stroke'] = len(strokes)-1
                count(tally)
                stock, own = trial, sweep(path, own, radius)
                cleared[0] = None
                kept = True
        if entry_record['stroke'] is None:
            entry_record['stroke'] = len(strokes)  # Leads into whatever cut comes next.
        return centre, reach, island, own, kept

    stretches = channel_stretches(allowed, seeds, radius) if len(seeds) > 1 else None
    if stretches is not None:
        # Several starts in one channel round a boss: open every start first, then send one front
        # forward from each, across its own stretch of channel and into the next start's spiral.
        # Fronts never meet head-on between starts.
        # Open them in order round the channel; the last one opened works first. Each front ends in the
        # next start's spiral, where the next front begins, so the fronts follow on without a lift.
        order = sorted(range(len(seeds)), key=lambda k: stretches[k][3])
        opened = {k: open_island(*seeds[k]) for k in order}
        for index in order[-1:] + order[:-1]:
            found = opened[index]
            if found is None:
                continue
            centre, reach, island, own, kept = found
            region, ahead, piece, _ = stretches[index]
            # As in a ring with one start: the front runs straight on through the next start's spiral
            # up to its cut, instead of closing on it from both walls in a pinch of small arcs.
            through = start.difference(stock).intersection(piece.buffer(radius, quad_segs=SWEEP_SEGMENTS))
            passes, arcs, blocked = wave(index, centre, stock.union(through.difference(
                Point(centre).buffer(reach + radius))), shared=False, focus=ahead, region=region)
            island.update(front_passes=passes, front_arcs=arcs, one_way=True)
            front_passes += passes
            any_blocked = any_blocked or blocked
            island_reports.append(island)
    for index, (centre, room) in enumerate(seeds if stretches is None else ()):
        found = open_island(centre, room)
        if found is None:
            continue
        centre, reach, island, own, kept = found
        focus = None
        if len(seeds) == 1 and kept:
            one_way = round_a_boss(centre, reach, rings, radius)
            if one_way is not None:
                # The spiral fills a channel that runs round a boss. Its two sides would each send a
                # front round, to meet head-on on the far side. Treat the half behind as still uncut:
                # one front then goes all the way round and passes straight through the spiral.
                behind, focus = one_way
                own = own.union(start.difference(stock).intersection(behind))
        # Every island but the last leaves shared ground to its neighbour; the last one cleans up.
        passes, arcs, blocked = wave(index, centre, own, shared=index < len(seeds)-1, focus=focus)
        island.update(front_passes=passes, front_arcs=arcs)
        front_passes += passes
        any_blocked = any_blocked or blocked
        island_reports.append(island)

    # Restarts: where the fronts could not get through (a neck held by spots no stepover could take,
    # at a low limit), stock is left beyond. Enter it afresh with a helix wherever one fits in the
    # stock that is left, and grow from there as a new island.
    for extra in range(RESTARTS):
        if out_of_time():
            break
        left = open_stock(stock)
        # Room for a helix is judged on all the stock, the wall band too: in a channel only a few
        # cutters wide the band is most of it.
        room = allowed.intersection(stock.intersection(reachable).buffer(-radius, quad_segs=SWEEP_SEGMENTS))
        # The overlay can come back as a collection with slivers of line among the polygons.
        room = unary_union([g for g in polygons(room) if g.area > 1e-9])
        if left.area < RESTART_MM2 or room.is_empty:
            break
        fresh = choose_seeds(room, 1, min_radius=radius, placement='widest')
        if not fresh:
            break
        found = open_island(*fresh[0], base=stock)
        if found is None:
            break
        centre, reach, island, own, kept = found
        index = len(island_reports)
        passes, arcs, blocked = wave(index, centre, own, shared=False)
        island.update(front_passes=passes, front_arcs=arcs, restart=True)
        front_passes += passes
        any_blocked = any_blocked or blocked
        island_reports.append(island)

    # Corners: the fronts swallow a corner once it is within a stepover, so the cutter centre never
    # reaches it. Creep into each corner along one wall in steps no deeper than CORNER_DEPTH.
    corners = {'visits': 0, 'refused': 0, 'no_link': 0, 'feed_mm': 0., 'peak_deg': 0.}
    creeps = ([] if leave_wall_crescents else
              [(ring, vertex, along) for ring in rings for vertex, along in convex_corners(ring)])
    for spot in (() if leave_wall_crescents else stuck_spots):
        # A spot the fronts left is usually a wedge against the wall nearby: creep in along the wall
        # there from both sides, the same way as into a corner.
        ring = min(rings, key=lambda r: r.distance(Point(spot)))
        place = ring.project(Point(spot))
        foot = ring.interpolate(place)
        creeps.append((ring, (foot.x, foot.y), [(place, -1, 2*CORNER_RUN_IN), (place, 1, 2*CORNER_RUN_IN)]))
    for ring, vertex, along in creeps:
            if distance(stock, Point(vertex)) >= radius - WALL_TOLERANCE:
                continue
            for path in corner_pecks(vertex, along, stock, radius, ring):
                if path is None:
                    corners['refused'] += 1
                    continue
                if strokes and stay_down_link(stock_clear(), stock, radius, strokes[-1].points[-1], path[0]) is None:
                    corners['no_link'] += 1  # Not worth a lift for a corner.
                    break
                peak, trial = cut(path, stock, radius, sample_step)
                commit('corner', path, 0., peak)
                corners['peak_deg'] = max(corners['peak_deg'], peak)
                stock, cleared[0] = without_slivers(trial), None
                corners['visits'] += 1
                corners['feed_mm'] += LineString(path).length

    # Finish: follow the pocket wall only where stock is still on it, such as the skin the last front
    # of a channel leaves because no later front sweeps back over it. Clean wall is not passed again.
    profile = {'pieces': 0, 'over_limit': 0, 'refused_mm': 0., 'feed_mm': 0.,
               'reachable_stock_before_mm2': stock.intersection(reachable).area}
    for inset in (PROFILE_INSETS if wall_profile else ()):
        # Only stock thicker than the wall tolerance sends the cutter back to a wall.
        thick = stock.buffer(-WALL_TOLERANCE/2, join_style=2).buffer(WALL_TOLERANCE/2, join_style=2)
        for part in polygons(allowed.buffer(-inset) if inset else allowed):
            if part.area < 1e-6:
                continue
            part = orient(part, sign=-1.)
            for ring in (part.exterior, *part.interiors):
                dense = list(segmentize(LineString(ring.coords), .1).coords)
                for whole in cutting_pieces(dense, thick, radius, run_out=1.5, closed=True):
                    # Judge the wall in short stretches so one tight spot does not refuse the rest.
                    chunks, chunk, length = [], [whole[0]], 0.
                    for q in whole[1:]:
                        length += math.dist(chunk[-1], q)
                        chunk.append(q)
                        if length >= PROFILE_CHUNK:
                            chunks.append(chunk)
                            chunk, length = [q], 0.
                    if len(chunk) > 1:
                        chunks.append(chunk)
                    restart = False
                    for piece in chunks:
                        if restart:
                            # The stretch before was refused, so roll on from cleared space again.
                            piece = eased(piece, False, stock_clear(), allowed, 1.5,
                                          ends=(True, False))
                            if len(piece) < 2:
                                continue
                        tally = [0., 0., 0.]
                        peak, trial = cut(piece, stock, radius, sample_step, tally=tally, measure=measure)
                        if stock.area - trial.area < MIN_GAIN_MM2:
                            continue
                        if peak > limit:
                            profile['over_limit'] += 1
                            profile['refused_mm'] += LineString(piece).length
                            restart = True
                            continue
                        restart = False
                        last = strokes[-1] if strokes else None
                        if last is not None and last.kind == 'profile' and last.points[-1] == piece[0]                                 and last.stepover_mm == inset:
                            strokes[-1] = Stroke('profile', last.points + piece[1:], inset, max(last.peak_deg, peak))
                        else:
                            commit('profile', piece, inset, peak)
                            profile['pieces'] += 1
                        stock = trial
                        cleared[0] = None
                        count(tally)
                        profile['feed_mm'] += LineString(piece).length

    # Rest: stock still left that the fronts, corners and wall finish could not take within the limit,
    # mostly in a corner the cutter only just reaches or a neck. It is taken whatever the engagement,
    # and the report says how far over the limit that went: the feed rules slow those moves as slots
    # or high engagement. A few such moves finish the depth.
    rest = {'pieces': 0, 'feed_mm': 0., 'over_limit_mm': 0., 'peak': 0.,
            'stock_before_mm2': open_stock(stock).area}

    def take_rest(path, stepover):
        """Cut path wherever it meets stock, without refusing; True if it took any."""
        nonlocal stock
        tally = [0., 0., 0.]
        peak, trial = cut(path, stock, radius, sample_step, tally=tally, measure=measure)
        if stock.area - trial.area < MIN_GAIN_MM2:
            return False
        commit('rest', path, stepover, peak)
        stock, cleared[0] = trial, None
        count(tally)
        length = LineString(path).length
        rest['pieces'] += 1
        rest['feed_mm'] += length
        rest['over_limit_mm'] += length if peak > limit else 0.
        rest['peak'] = max(rest['peak'], peak)
        return True

    # Stock away from the wall that the fronts were stopped short of: step the cleared area out
    # into it a little at a time, as the fronts do, but without refusing a cut.
    step = REST_STEPOVER if measure != 'width' else min(max(limit*2*radius, .1), REST_STEPOVER)
    for _ in range(REST_PASSES if rest_finish else 0):
        left = open_stock(stock)
        if left.area <= REST_MM2 or out_of_time():
            break
        near = left.buffer(radius + step)
        taken = False
        for part in polygons(stock_clear()):
            if part.area < 1e-6 or not part.intersects(near):
                continue
            grown = part.buffer(step, quad_segs=SWEEP_SEGMENTS).intersection(allowed)
            for run, closed in fronts(part, grown, wall, zone=near):
                path = eased(run, closed, part, allowed, blend)
                if len(path) < 2:
                    continue
                for piece in cutting_pieces(path, stock, radius):
                    taken = take_rest(piece, step) or taken
        if not taken:
            break
    # Leaving the walls alone, this runs only where stock off the wall band is still left - a channel
    # too narrow for a helix or a front - and is then the only way in.
    if rest_finish and open_stock(stock).area > REST_MM2 and not out_of_time():
        # What is still left lies against the wall, mostly deep in a corner: follow the wall over it.
        thick = stock.buffer(-WALL_TOLERANCE/2, join_style=2).buffer(WALL_TOLERANCE/2, join_style=2)
        for part in polygons(allowed):
            if part.area < 1e-6:
                continue
            part = orient(part, sign=-1.)
            for ring in (part.exterior, *part.interiors):
                dense = list(segmentize(LineString(ring.coords), .1).coords)
                for whole in cutting_pieces(dense, thick, radius, run_out=1.5, closed=True):
                    take_rest(whole, 0.)
    rest['stock_after_mm2'] = open_stock(stock).area

    stop = ('time_budget' if out_of_time() else
            'blocked' if (any_blocked or profile['over_limit']) and rest['stock_after_mm2'] > REST_MM2 else
            'front_exhausted')
    passes = front_passes
    residual = open_stock(stock)
    crescents = stock.intersection(reachable).area - residual.area
    total = start.intersection(reachable).area
    cuts = [s for s in strokes if s.kind == 'front']
    feeds = [s for s in strokes if s.kind not in ('link', 'corner', 'rest')]  # Corners are judged by depth.
    report = {'stop': stop, 'placement': placement, 'wall_pull_back': wall_pull_back,
              'lobes': [{'widest_xy_mm': xy, 'room_mm': room, 'bounds_mm': bounds}
                        for xy, room, bounds in find_lobes(allowed, min_radius=radius)],
              'islands': island_reports, 'front_passes': passes, 'front_arcs': len(cuts),
              'wall_profile': profile if wall_profile else None, 'corners': corners, 'rest': rest,
              'stuck_spots': [tuple(float(v) for v in q) for q in stuck_spots],
              'reachable_stock_before_profile_mm2': profile['reachable_stock_before_mm2'],
              'reachable_mm2': total, 'reachable_residual_mm2': residual.area,
              'cleared_fraction': 1 - residual.area/total if total else None,
              'peak_contact_deg': max((s.peak_deg for s in feeds), default=None),
              'mean_contact_deg': contact[0]/contact[1] if contact[1] else None,
              'mean_contact_while_cutting_deg': contact[0]/contact[2] if contact[2] else None,
              'share_of_cut_feed_in_contact': contact[2]/contact[1] if contact[1] else None,
              'cut_feed_mm': sum(LineString(s.points).length for s in feeds),
              'link_feed_mm': sum(LineString(s.points).length for s in strokes if s.kind == 'link'),
              'spiral_feed_mm': sum(LineString(s.points).length for s in strokes if s.kind == 'spiral'),
              'stay_down_links': travel['links'], 'retract_rapids': travel['rapids'],
              'retract_reasons': dict(refused, first_cut=1),
              'arcs_at_0.2_mm_or_less': sum(s.stepover_mm <= .2 for s in cuts),
              'front_stepover_histogram': {str(v): sum(s.stepover_mm == v for s in cuts) for v in stepovers},
              'seconds': time.time()-started}
    report['entries'] = entries
    report['wall_crescents_mm2'] = crescents if leave_wall_crescents else 0.
    report['top_mm'], report['depth_mm'] = top, depth
    report['machine_time'] = machine_time(strokes, report['islands'], top=top, depth=depth)
    return strokes, residual, report


def clear_depths(pocket, radius, *, top=0., bottom, step_down, **options):
    """Clear a pocket in levels from top down to bottom: [(z, strokes, residual, report)].

    Levels are equal and at most step_down deep; each starts from intact
    stock at its own depth, with the floor of the level above as the top its
    helices start from. pocket is one outline for every level (a 2.5D
    pocket), or a function of Z giving each level's outline (the slices of a
    3D waterfall). With one outline the plan is the same at every level, so
    it is worked out once and moved down: only the helices differ in Z.
    clear_pocket options pass through.
    """
    if step_down <= 0 or bottom >= top:
        raise ValueError('expected a positive step-down and a bottom below the top')
    count = max(1, math.ceil((top - bottom)/step_down - 1e-9))
    levels, above, first = [], top, None
    for k in range(1, count+1):
        z = top - (top - bottom)*k/count
        if callable(pocket) or first is None:
            outline = pocket(z) if callable(pocket) else pocket
            strokes, residual, report = clear_pocket(outline, radius, top=above, depth=z, **options)
            first = first or (z, above)
        else:
            z0, above0 = first
            _, strokes, residual, base = levels[0]
            shift = z - z0
            report = dict(base, top_mm=above, depth_mm=z, reused_from_mm=z0, seconds=0.,
                          entries=[dict(entry, helix_xyz=[[x, y, hz + shift] for x, y, hz in entry['helix_xyz']])
                                   for entry in base['entries']])
            if abs((above - z) - (above0 - z0)) > 1e-9:
                raise AssertionError('levels are meant to be equal')
        levels.append((z, strokes, residual, report))
        above = z
    return levels
