"""Wavefront clearing of a planar pocket, and of a pocket in levels."""
import math
import time
import numpy as np

from shapely import distance, points, segmentize
from shapely.geometry import LineString, Point
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from gcodeproducer.core.cam.adaptive_entry import seed_entry
from gcodeproducer.core.geometry.polygon_parts import polygons
from .stroke import Stroke
from .regions import center_regions, find_lobes, choose_seeds, spiral_out, clearance, grow_clearance, fronts, eased, without_slivers, sweep, round_a_boss, channel_stretches
from .contact import cutting_pieces, cut
from .walls import wall_ends, convex_corners, corner_pecks
from .links import stay_down_link, smooth_link, heading
from .timing import machine_time
from .wavefront_constants import (STEPOVERS, SWEEP_SEGMENTS, WALL_TOLERANCE, MIN_GAIN_MM2, PROFILE_CHUNK, ROLL_STEPOVER, STEADY_STEPOVER, RAISE_PATIENCE, RAISE_PATIENCE_MAX)


def clear_pocket(pocket, radius, *, limit=60., sample_step=.1, stepovers=STEPOVERS, blend=3.,
                 islands=None, placement='lobes', wall_pull_back=True, wall_profile=True, trace=None, top=0., depth=-2., lead_angle=2.5, time_budget=None,
                 smooth_links=True, material=None):
    """Return (strokes, residual, report) for one target plane.

    The stock starts as the whole pocket, or as the part of it inside
    material where earlier cuts or levels already removed some.
    """
    allowed = unary_union(center_regions(pocket, radius))
    wall = allowed.boundary
    rings = [LineString(r.coords) for g in polygons(allowed) for r in (g.exterior, *g.interiors)]
    reachable = allowed.buffer(radius, quad_segs=SWEEP_SEGMENTS)
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

    def commit(kind, path, stepover, peak):
        """Join the cut to the previous one through cleared space, else count a retract and rapid."""
        if strokes:
            route = stay_down_link(stock_clear(), stock, radius, strokes[-1].points[-1], path[0],
                                  why=refused)
            if route is None:
                travel['rapids'] += 1
            else:
                travel['links'] += 1
                if smooth_links:
                    route = smooth_link(route, heading(strokes[-1].points, True), heading(path, False),
                                        stock_clear(), stock, radius)
                strokes.append(Stroke('link', route, 0., 0.))
        else:
            travel['rapids'] += 1
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
                failed, halt = [], False
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
                    # Sweep the wall at the arc ends; only at ROLL_STEPOVER or below fall back to
                    # rolling off before the wall, so a lighter cut gets to try the wall first.
                    if wall_pull_back and not closed:
                        ends, others = [], []
                        shapes = [wall_ends(run, part, own, radius, allowed, rings, blend, note=ends, alternatives=others),
                                  *others]
                        if stepover <= ROLL_STEPOVER or level == len(stepovers)-1:
                            shapes.append(lambda run=run, closed=closed: eased(run, closed, part, allowed, blend))
                    else:
                        shapes = [eased(run, closed, part, allowed, blend)]
                    done, skip = None, False
                    for path in shapes:
                        # Fallback shapes are callables, built only when the shapes before them fail.
                        path = path() if callable(path) else path
                        if len(path) < 2:
                            continue
                        pieces = cutting_pieces(path, stock, radius)
                        if shared and pieces:
                            points = [q for piece in pieces for q in piece]
                            if sum(owner(q) == index for q in points) < len(points)/2:
                                skip = True  # A neighbour finishes this stretch; do not advance through it.
                                break
                        trial, done = stock, []
                        for piece in pieces:
                            at, tally = [], [0., 0., 0.]
                            peak, after = cut(piece, trial, radius, sample_step, where=at, tally=tally, stop_above=limit)
                            if peak > limit:
                                done = None
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
                        commit('front', piece, stepover, peak)
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
        return passes, arcs, blocked

    front_passes, any_blocked = 0, False

    def open_island(centre, room):
        """Helix and spiral for one start: (centre, spiral reach, island report, own stock, spiral kept)."""
        nonlocal stock
        region = Point(centre).buffer(room)
        entry = seed_entry(region, stock, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
        alone = seed_entry(region, start, radius=radius, top=top, depth=depth, lead_angle=lead_angle)
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
        for stepover in stepovers:
            probe = spiral_out(centre, min(reach, 1.8*radius + 3.), stepover, blend=blend)
            if cut(probe, stock, radius, sample_step, stop_above=limit)[0] <= limit:
                chosen = stepover
                break
        if chosen is not None:
            path = spiral_out(centre, reach, chosen, blend=blend)
            tally = [0., 0., 0.]
            peak, trial = cut(path, stock, radius, sample_step, tally=tally)
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

    # Corners: the fronts swallow a corner once it is within a stepover, so the cutter centre never
    # reaches it. Creep into each corner along one wall in steps no deeper than CORNER_DEPTH.
    corners = {'visits': 0, 'refused': 0, 'no_link': 0, 'feed_mm': 0., 'peak_deg': 0.}
    for ring in rings:
        for vertex, along in convex_corners(ring):
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
    for inset in ((.3, 0.) if wall_profile else ()):
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
                        peak, trial = cut(piece, stock, radius, sample_step, tally=tally)
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

    stop = 'time_budget' if out_of_time() else 'blocked' if any_blocked or profile['over_limit'] else 'front_exhausted'
    passes = front_passes
    residual = stock.intersection(reachable)
    total = start.intersection(reachable).area
    cuts = [s for s in strokes if s.kind == 'front']
    feeds = [s for s in strokes if s.kind not in ('link', 'corner')]  # Corners are judged by depth.
    report = {'stop': stop, 'placement': placement, 'wall_pull_back': wall_pull_back,
              'lobes': [{'widest_xy_mm': xy, 'room_mm': room, 'bounds_mm': bounds}
                        for xy, room, bounds in find_lobes(allowed, min_radius=radius)],
              'islands': island_reports, 'front_passes': passes, 'front_arcs': len(cuts),
              'wall_profile': profile if wall_profile else None, 'corners': corners,
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
