"""Compare offline two-lobe front proposals on the same seeded pocket."""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from shapely import from_wkt, union_all
from shapely.geometry import LineString, Point, box

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcodeproducer.core.cam.hsm_contact import contact_angle
from tools.hsm_center_regions import CENTER_BUFFER_SEGMENTS, center_regions, connected_clearance, nearby_frontier
from tools.hsm_front_corner import (clearance_tapers, filleted_corner, frontier_corner_poses, roll_off, roll_on,
                                    shifted_roll_ons, tapered_roll_on, turned_straight_candidates)
from tools.hsm_front_choice import choose_front_cut
from tools.hsm_front_run import run_front
from tools.hsm_live_waypoints import live_waypoints
from tools.hsm_replay_overlay import write_overlay
from tools.hsm_tangent_link import forward_clearance
from tools.hsm_straight_front import eased_front_bite, frontier_edges, straight_advance, straight_front_candidates


def clearance_sections(regions, component, xs):
    """Separate wall-limited spans from seed-connected open spans."""
    domain = union_all(regions)

    def spans(geometry):
        if geometry.is_empty:
            return
        if hasattr(geometry, 'geoms'):
            for part in geometry.geoms:
                yield from spans(part)
        elif geometry.length > 0:
            yield geometry.bounds[1], geometry.bounds[3]

    def intervals(geometry):
        merged = []
        for lo, hi in sorted(spans(geometry)):
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
            else:
                merged.append((lo, hi))
        return merged

    report = []
    for x in xs:
        if not math.isfinite(x):
            raise ValueError('section X must be finite')
        section = LineString([(x, domain.bounds[1]), (x, domain.bounds[3])]) if not domain.is_empty else LineString()
        report.append({'x_mm': x, 'domain_y_mm': intervals(section.intersection(domain)),
                       'connected_y_mm': intervals(section.intersection(component))})
    return report


def section_bite_spans(regions, component, *, search_west=False, fit_width=False):
    """Report the exact sections and width gate used by the bow generator."""
    if component.is_empty:
        return []
    east = component.bounds[2]
    def audit(offsets):
        sections = clearance_sections(regions, component, [east-d for d in offsets])
        for section in sections:
            section['eligible_y_mm'] = [(lo, hi) for lo, hi in section['connected_y_mm'] if hi-lo >= 1.5]
        return sections

    sections = audit((.25, .5))
    if search_west and not any(section['eligible_y_mm'] for section in sections):
        for offset in (.75, 1.):
            sections.extend(audit((offset,)))
            if sections[-1]['eligible_y_mm']:
                break
    if fit_width and not any(section['eligible_y_mm'] for section in sections):
        # Keep the nearest sampled opening that actually fits the width gate.
        for i in range(17, 33):
            row = audit((i/16,))[0]
            if row['eligible_y_mm']:
                sections.append(row)
                break
    return sections


def section_bites(regions, component, radius, *, turn_exits=False, live_stock=None, search_west=False):
    """Propose shallow eastward bows between clear poses on inset sections."""
    contact_zone = None if live_stock is None else live_stock.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS)
    for section in section_bite_spans(regions, component, search_west=search_west):
        x = section['x_mm']
        for low, high in section['eligible_y_mm']:
            face_x = x + radius + .25
            depths = (.125, .25, .375)
            if contact_zone is not None:
                y = (low + high)/2
                hit = LineString([(x, y), (x+.75, y)]).intersection(contact_zone)
                if not hit.is_empty:
                    onset = hit.bounds[0] - x
                    probes = (round(onset + delta - .25, 6) for delta in (.05, .10, .15))
                    depths += tuple(depth for depth in probes if 0 < depth < radius and depth <= .5)
            for immersion in dict.fromkeys(depths):
                edge = ((face_x, high-.2), (face_x, low+.2))
                path = eased_front_bite(edge, radius, immersion, .25, .0025)
                yield path
                if turn_exits:
                    for turn_radius in (.25, .5):
                        yield roll_off(path, turn_radius, .0025)


def section_follow_cuts(sections, stock, radius, *, turn_exits=False, audit=None, on_profile=None, taper_entry=False, taper_only=False, entry_fraction=.25, advances=(.05, .10, .15), ray_length=1.5):
    """Follow first stock contact across an open span, easing both ends west."""
    occupied = stock.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS)
    for section in sections:
        x = section['x_mm']
        for low, high in section['eligible_y_mm']:
            low, high = low+.2, high-.2
            count = max(8, math.ceil((high-low)/.125))
            rows = []
            missed = []
            for i in range(count+1):
                t = i/count
                y = high + (low-high)*t
                hit = LineString([(x, y), (x+ray_length, y)]).intersection(occupied)
                if hit.is_empty:
                    if audit is None:
                        break
                    missed.append(y)
                    continue
                blend = math.sin(math.pi/2*min(1., t/entry_fraction, 4*(1-t)))**2
                rows.append((y, hit.bounds[0]-x, blend))
            if audit is not None:
                audit.append({'x_mm': x, 'inset_y_mm': (low, high), 'rows': count+1,
                              'missed_y_mm': missed, 'max_hit_distance_mm': max((d for _, d, _ in rows), default=None)})
            if len(rows) != count+1:
                continue
            styles = (True,) if taper_only else (False, True) if taper_entry else (False,)
            for tapered in styles:
                for advance in advances:
                    path = []
                    for i, (y, offset, blend) in enumerate(rows):
                        weight = math.sin(math.pi/2*max(0., min(1., 4*i/count-1)))**2 if tapered else 1.
                        path.append((x + (offset+advance*weight)*blend, y))
                    if on_profile is not None:
                        on_profile(path, count, advance)
                    yield path
                    if turn_exits:
                        retreat = roll_off(path, .25, .0025)
                        if on_profile is not None:
                            on_profile(retreat, count, advance)
                        yield retreat


def small_section_cuts(sections, stock, radius, *, turn_exits=False, audit=None, on_profile=None, ray_length=1.5):
    """Generate the small-advance retries, optionally auditing each entry shape."""
    for fraction in (.25, .4, .5):
        profiles = [] if audit is not None else None
        note = None if on_profile is None else lambda path, n, a: on_profile(path, n, a, fraction)
        emitted = 0
        for path in section_follow_cuts(sections, stock, radius, turn_exits=turn_exits,
                                        on_profile=note, audit=profiles, entry_fraction=fraction,
                                        advances=(.01, .02, .03, .04), ray_length=ray_length):
            emitted += 1
            yield path
        if audit is not None:
            audit.append({'entry_fraction': fraction, 'profiles': profiles, 'proposal_count': emitted})


def bounded_small_section_cuts(sections, stock, radius, *, extend=False, on_extension=None, **kwargs):
    """Extend only an empty proposal set with recorded misses; leave motion checks to the caller."""
    audit = [] if extend else None
    emitted = False
    for path in small_section_cuts(sections, stock, radius, audit=audit, **kwargs):
        emitted = True
        yield path
    if not emitted and audit and any(p['missed_y_mm'] for row in audit for p in row['profiles']):
        if on_extension is not None:
            on_extension()
        yield from small_section_cuts(sections, stock, radius, ray_length=1.65, **kwargs)


def overload_summary(overloads):
    """Bound first-overload chords, not inferred sample or stock-contact locations."""
    points = [xy for row in overloads for xy in row['chord_xy_mm']]
    return {'count': len(overloads), 'phases': dict(Counter(row['phase'] for row in overloads)),
            'chord_bounds_mm': LineString(points).bounds if points else None}


def relieve_contour(path, low, high, depth, *, shoulder=.3):
    """Pull interior points west over a failing Y band with eased shoulders."""
    result = [path[0]]
    for x, y in path[1:-1]:
        distance = max(low-y, y-high, 0.)
        weight = .5*(1 + math.cos(math.pi*min(1., distance/shoulder)))
        result.append((x-depth*weight, y))
    return [*result, path[-1]]


def clearance_delta(before, after):
    """Measure newly connected area and signed east-edge shift."""
    return {'new_connected_mm2': after.difference(before).area,
            'east_shift_mm': None if before.is_empty or after.is_empty else after.bounds[2]-before.bounds[2]}


def wider_sections(regions, component, *, widths=(2., 2.5, 3.)):
    """Find the closest sampled section per target span width."""
    if component.is_empty:
        return []
    east = component.bounds[2]
    rows = clearance_sections(regions, component, [east-i/16 for i in range(4, 49)])
    result = []
    for target in widths:
        for row in rows:
            eligible = [(lo, hi) for lo, hi in row['connected_y_mm'] if hi-lo >= target]
            if eligible:
                result.append(dict(row, target_width_mm=target, eligible_y_mm=eligible))
                break
    return result


def widest_span(section):
    return max((hi-lo for lo, hi in section['connected_y_mm']), default=0.)


def probe_wide_east_sweep(pocket, regions, stock, component, seed_xy, pose, radius, gates, routes):
    """Check a stock-following sweep across a wider section of the east front."""
    sections = wider_sections(regions, component, widths=(2.5, 3., 3.5, 4.))
    audit, counts = [], Counter()
    paths = section_follow_cuts(sections, stock, radius, turn_exits=True, audit=audit,
                                ray_length=2.75, advances=(.03, .05, .08))

    def score(live):
        clear = connected_clearance(pocket, live, seed_xy, radius)
        return None if clear.is_empty else round(clear.bounds[2], 6)

    choice = choose_front_cut(pocket, stock, pose, paths, radius, waypoints=routes, diagnostics=counts,
                              priority_score=score, **gates)
    report = {'sections': sections, 'profiles': audit, 'gates': dict(counts)}
    if choice is not None:
        after = connected_clearance(pocket, choice.remaining, seed_xy, radius)
        ys = [y for _, y in choice.cut]
        report.update(removed_mm2=choice.removed_mm2, feed_mm=choice.travel_mm, peak_deg=choice.peak_deg,
                      cut_y_span_mm=max(ys)-min(ys), **clearance_delta(component, after))
    return choice, report


def neck_fixture():
    fixture = Path(__file__).resolve().parents[1] / 'examples' / 'adaptive-neck-pocket.wkt'
    pocket = from_wkt(fixture.read_text(encoding='utf-8'))
    cleared = union_all([box(5, 16, 22, 30), box(5, 12, 14, 34), box(20, 24, 25, 34)])
    return pocket, pocket.difference(cleared)


def write_opening_review(path, pocket, stock, link, cut):
    """Show the modeled initial material that an XY-only viewer cannot infer."""
    with Path(path).open('x', encoding='ascii', newline='\n') as stream:
        write_overlay(stream, pocket, stock, [(i, points, clear) for i, (points, clear) in
                      enumerate(((link, True), (cut, False)), 1) if len(points) > 1],
                      legend='Opening: orange stock | light pre-cleared | 1 gray link | 2 blue cut')


def write_review_gcode(path, cuts, seed_xy, reason):
    """Save accepted XY motion for a viewer, not a machine or quantized replay."""
    with Path(path).open('x', encoding='ascii', newline='\n') as stream:
        def move(code, xy):
            stream.write(f'{code} X{xy[0]:.6f} Y{xy[1]:.6f}\n')

        stream.write('(DEBUG ONLY - XY GEOMETRY REVIEW - DO NOT RUN ON A MACHINE)\n'
                     f'(Synthetic two-lobe fixture: {reason}, {len(cuts)} accepted cuts)\n'
                     '(Starts in assumed pre-cleared stock; see companion opening SVG)\n'
                     '(No Z, entry, spindle, tool or feed schedule; rounded XY not replayed)\n'
                     'G21\nG90\n')
        move('G0', seed_xy)
        for index, choice in enumerate(cuts, 1):
            stream.write(f'(Cut {index}: cleared link)\n')
            for xy in choice.link[1:]:
                move('G1', xy)
            stream.write(f'(Cut {index}: stock removal)\n')
            for xy in choice.cut[1:]:
                move('G1', xy)
        stream.write('M2\n')


def check_neck(*, with_corners=False, corner_runoff=0., with_detours=False,
               with_live_detours=False, with_shallow_fronts=False, shallow_runoff=2., shallow_rolloff=0.,
               shallow_rollon=0., with_shifted_joins=False, max_cuts=12, with_taper=False,
               with_clearance_tapers=False, with_early_exits=False, require_clear_exit=False,
               with_neck_front=False, with_three_leg_links=False, min_departure=0., prioritize_neck=False, with_front_bites=False, trace_clearance=False,
               prioritize_clearance=False, with_wide_bites=False, lookahead_width=1, lookahead_after=0, section_xs=(), with_section_bites=False, section_bites_last=False, section_turn_exits=False, section_live_depth=False, section_search_west=False, section_follow=False, section_fit_width=False, section_taper_entry=False, section_taper_at_stall=False, section_shallow_approach=False, section_nominal_at_stall=False, section_bracket_at_stall=False, section_small_retry=False, section_ray_probe=False, section_extend_rays=False, section_relief_probe=False, section_widen_probe=False, review_gcode=None, section_widen_retry=False, full_stock=False, initial_state=None, clearance_straight_fallback=False, wide_east_sweep=False, sweep_follow_budget=0):
    if not math.isfinite(corner_runoff) or corner_runoff < 0 or (corner_runoff and not with_corners):
        raise ValueError('corner runoff must be nonnegative and requires corner proposals')
    if not math.isfinite(shallow_runoff) or shallow_runoff < 0:
        raise ValueError('shallow runoff must be nonnegative')
    if not math.isfinite(shallow_rolloff) or shallow_rolloff < 0 or (shallow_rolloff and not with_shallow_fronts):
        raise ValueError('shallow roll-off must be nonnegative and requires shallow proposals')
    if not math.isfinite(shallow_rollon) or shallow_rollon < 0 or (shallow_rollon and not with_shallow_fronts):
        raise ValueError('shallow roll-on must be nonnegative and requires shallow proposals')
    probe_count = sum((section_taper_at_stall, section_shallow_approach, section_nominal_at_stall, section_bracket_at_stall))
    if (section_ray_probe or section_extend_rays) and not section_small_retry:
        raise ValueError('ray trials require small section retries')
    if (section_relief_probe or section_widen_probe or section_widen_retry) and not section_extend_rays:
        raise ValueError('terminal geometry probes require extended small retries')
    if section_ray_probe and section_extend_rays:
        raise ValueError('ray audit requires unchanged small section retries')
    if section_small_retry and (not section_follow or probe_count):
        raise ValueError('small retries require section following without terminal probes')
    if probe_count and (not section_follow or section_taper_entry):
        raise ValueError('terminal approach probes require untapered section following')
    if probe_count > 1:
        raise ValueError('select only one terminal approach probe')
    if section_taper_entry and not section_follow:
        raise ValueError('section entry taper requires section following')
    if section_fit_width and not (section_follow and section_search_west):
        raise ValueError('fitting section width requires section following and west search')
    if (section_turn_exits or section_live_depth or section_search_west or section_follow) and not section_bites_last:
        raise ValueError('section variants require last-resort section bites')
    if (with_section_bites or section_bites_last) and not with_shallow_fronts:
        raise ValueError('section bites require shallow fronts')
    if with_shifted_joins and not shallow_rollon:
        raise ValueError('shifted joins require a shallow roll-on radius')
    if (with_taper or with_clearance_tapers) and not with_shallow_fronts:
        raise ValueError('tapered approaches require shallow proposals')
    if with_early_exits and not (with_clearance_tapers and shallow_rolloff):
        raise ValueError('early exits require clearance tapers and a roll-off radius')
    if with_neck_front and not (with_shallow_fronts and shallow_rolloff):
        raise ValueError('neck-front proposals require shallow fronts and roll-off')
    if (with_front_bites or with_wide_bites) and not with_neck_front:
        raise ValueError('front bites require neck-front proposals')
    if sweep_follow_budget < 0 or (sweep_follow_budget and not wide_east_sweep):
        raise ValueError('sweep follow-up requires a wide sweep and nonnegative budget')
    if wide_east_sweep and not clearance_straight_fallback:
        raise ValueError('wide east sweep requires a clearance-straight handoff')
    if clearance_straight_fallback and (initial_state is None or section_small_retry):
        raise ValueError('clearance straight fallback is for handoff without small section retries')
    pocket, stock = neck_fixture()
    seed = ((9., 28.5), (1., 0.))
    if initial_state is not None:
        if full_stock:
            raise ValueError('received stock state cannot be combined with full stock')
        stock, seed = initial_state
        if stock.difference(pocket).area > 1e-8:
            raise ValueError('received stock lies outside the neck fixture')
    elif full_stock:
        stock = pocket
    radius = 2.
    regions = center_regions(pocket, radius)

    def propose(live, _pose):
        yield from straight_front_candidates(pocket, live, radius, .5, min_edge=2., lead=2., runoff=2.)
        if with_corners:
            for poses in frontier_corner_poses(pocket, live, radius, .5, lead=2., runoff=corner_runoff):
                path = filleted_corner(*poses, 3., .0025)
                if path is not None:
                    yield path

    taper_candidate = None
    taper_chords = 0
    overload_phases = defaultdict(Counter)

    follow_profile = None
    entry_fraction = .25
    follow_overloads = defaultdict(list)

    def note_profile(path, body_chords, advance, fraction=None, family='standard'):
        nonlocal follow_profile
        follow_profile = (path, body_chords, advance, entry_fraction if fraction is None else fraction, family)

    def report_overload(round_index, path, segment, angle):
        if path is taper_candidate:
            phase = 'approach' if segment < taper_chords else 'straight' if segment == taper_chords else 'exit'
            overload_phases[round_index][phase] += 1
        if follow_profile is not None and path is follow_profile[0]:
            _, body_chords, advance, fraction, family = follow_profile
            t = (segment + .5)/body_chords
            phase = ('retreat' if segment >= body_chords else 'ease_in' if t < fraction
                     else 'ease_out' if t > .75 else 'follow')
            follow_overloads[round_index].append({'family': family, 'phase': phase, 'segment': segment,
                                                 'chord_xy_mm': path[segment:segment+2],
                                                 'entry_fraction': fraction,
                                                 'advance_mm': advance, 'contact_deg': angle})

    def propose_shallow(live, pose):
        nonlocal taper_candidate, taper_chords
        for path in straight_front_candidates(pocket, live, radius, .25, min_edge=2., lead=2., runoff=shallow_runoff):
            cut = roll_off(path, shallow_rolloff, .0025) if shallow_rolloff else path
            yield cut
            if shallow_rollon:
                yield roll_on(cut, shallow_rollon, .0025)
                if with_shifted_joins:
                    yield from shifted_roll_ons(cut, shallow_rollon, .0025, (2., 4.))
            if with_taper:
                yield tapered_roll_on(cut, 1.5, 4., .0025)
            if with_clearance_tapers:
                variants = [cut]
                start, end = path
                length = math.dist(start, end)
                if with_early_exits:
                    for trim in (1., 2.):
                        if length - trim <= radius:
                            continue
                        early_end = tuple(b - (b-a)*trim/length for a, b in zip(start, end))
                        variants.append(roll_off([start, early_end], shallow_rolloff, .0025))
                for variant in variants:
                    for taper in clearance_tapers(pocket, live, variant, radius, offset=1.5, run=4., chord_error=.0025):
                        taper_candidate = taper
                        taper_chords = len(taper) - len(variant)
                        yield taper
                        taper_candidate = None

        if with_neck_front:
            front = nearby_frontier(pocket, live, pose[0], radius, extra_reach=.25)
            if not front.is_empty:
                _, y0, x1, y1 = front.bounds
                focus = front.intersection(box(x1-3., y0-1., x1+1., y1+1.))
                for edge in frontier_edges(pocket, live, focus=focus):
                    if math.dist(*edge) < 2.:
                        continue
                    if with_front_bites:
                        yield eased_front_bite(edge, radius, .25, .25, .0025)
                    if with_wide_bites:
                        yield eased_front_bite(edge, radius, .25, .25, .0025, ramp_fraction=.25)
                    path = straight_advance(pocket, edge, radius, .25)
                    if path is not None:
                        cut = roll_off(path, shallow_rolloff, .0025)
                        yield from clearance_tapers(pocket, live, cut, radius, offset=1.5, run=4., chord_error=.0025)

        if with_section_bites:
            yield from propose_section_bites(live, pose)

    def propose_section_bites(live, _pose):
        component = connected_clearance(pocket, live, seed[0], radius)
        yield from section_bites(regions, component, radius, turn_exits=section_turn_exits,
                                 live_stock=live if section_live_depth else None, search_west=section_search_west)
        if section_follow:
            sections = section_bite_spans(regions, component, search_west=section_search_west, fit_width=section_fit_width)
            yield from section_follow_cuts(sections, live, radius, turn_exits=section_turn_exits,
                                           on_profile=note_profile, taper_entry=section_taper_entry)

    ray_extensions = 0

    def record_extension():
        nonlocal ray_extensions
        ray_extensions += 1

    def propose_small_contours(live, _pose):
        component = connected_clearance(pocket, live, seed[0], radius)
        sections = section_bite_spans(regions, component, search_west=section_search_west, fit_width=section_fit_width)
        family = 'small'

        def extend_profile():
            nonlocal family
            family = 'extended_ray'
            record_extension()

        def note(path, chords, advance, fraction):
            note_profile(path, chords, advance, fraction, family)

        return bounded_small_section_cuts(sections, live, radius, turn_exits=section_turn_exits,
                                          on_profile=note, extend=section_extend_rays, on_extension=extend_profile)

    def propose_widening(live, _pose):
        component = connected_clearance(pocket, live, seed[0], radius)
        if component.is_empty:
            return (), None
        gauge_x = component.bounds[2] - .75

        def width(region):
            return widest_span(clearance_sections(regions, region, (gauge_x,))[0])

        baseline = width(component)

        def score(post_cut):
            gain = width(connected_clearance(pocket, post_cut, seed[0], radius)) - baseline
            return gain if gain >= .01 else None

        rows = wider_sections(regions, component)
        paths = small_section_cuts(rows, live, radius, turn_exits=section_turn_exits, ray_length=2.75)
        return paths, score

    def propose_clearance_straights(live, _pose):
        component = connected_clearance(pocket, live, seed[0], radius)
        focus = component.buffer(radius+.35)
        return turned_straight_candidates(pocket, live, radius, component, focus=focus)

    waypoints = tuple((xy, heading) for xy in ((10., 20.), (10., 27.), (17., 23.), (18., 28.))
                      for heading in ((1., 0.), (0., 1.), (-1., 0.), (0., -1.))) if with_detours else ()
    def propose_waypoints(live, pose):
        return live_waypoints(pocket, live, pose[0], radius, spacing=3., rings=4, limit=8)

    neck_target = pocket.intersection(box(24., 0., 134., 61.))
    def clearance_score(live):
        component = connected_clearance(pocket, live, seed[0], radius)
        return round(component.bounds[2], 6) if not component.is_empty else -math.inf

    gates = dict(contact_limit=60., sample_step=.1 if initial_state is None else .025, link_handle=1., require_clear_exit=require_clear_exit,
                 with_three_leg_links=with_three_leg_links, min_departure=min_departure)
    diagnostics = []
    cuts, remaining, reason = run_front(pocket, stock, seed, propose, radius, max_cuts=max_cuts,
                                       diagnostics=diagnostics,
                                       waypoints=waypoints,
                                       propose_waypoints=propose_waypoints if with_live_detours else None,
                                       propose_on_stall=propose_shallow if with_shallow_fronts else None,
                                       on_overload=report_overload if with_clearance_tapers or section_follow else None,
                                       priority_region=neck_target if prioritize_neck else None,
                                       priority_score=clearance_score if prioritize_clearance else None,
                                       lookahead_width=lookahead_width, lookahead_after=lookahead_after,
                                       propose_last_resort=propose_section_bites if section_bites_last else None,
                                       propose_final_retry=(propose_small_contours if section_small_retry else
                                                            propose_clearance_straights if clearance_straight_fallback else None),
                                       scored_retry=propose_widening if section_widen_retry else None,
                                       **gates)
    if not cuts and reason == 'stalled' and diagnostics[-1].get('origin_clearance'):
        reason = 'entry_required'
    reachable = union_all([r.buffer(radius, quad_segs=CENTER_BUFFER_SEGMENTS) for r in regions])
    last_xy = cuts[-1].cut[-1] if cuts else seed[0]
    last_heading = seed[1]
    if cuts:
        previous = next(xy for xy in reversed(cuts[-1].cut[:-1]) if xy != last_xy)
        last_heading = tuple(b-a for a, b in zip(previous, last_xy))
    departure = forward_clearance(pocket, remaining, radius, last_xy, last_heading, 2*radius)
    point = Point(last_xy)
    initial_clearance = connected_clearance(pocket, stock, seed[0], radius)
    clearance = connected_clearance(pocket, remaining, seed[0], radius)
    sweep = None
    if wide_east_sweep and reason != 'entry_required':
        pose = last_xy, last_heading
        routes = (*waypoints, *propose_waypoints(remaining, pose)) if with_live_detours else waypoints
        sweep, sweep_report = probe_wide_east_sweep(pocket, regions, remaining, clearance, seed[0], pose, radius, gates, routes)
        followups = []
        if sweep_follow_budget:
            run_options = dict(waypoints=waypoints, propose_waypoints=propose_waypoints if with_live_detours else None,
                               propose_on_stall=propose_shallow if with_shallow_fronts else None,
                               propose_final_retry=propose_clearance_straights, **gates)

            def continuation(live, pose):
                cuts_after, stock_after, stop = run_front(pocket, live, pose, propose, radius,
                                                          max_cuts=sweep_follow_budget, **run_options)
                clear_after = connected_clearance(pocket, stock_after, seed[0], radius)
                start_clear = connected_clearance(pocket, live, seed[0], radius)
                start_east = None if start_clear.is_empty else start_clear.bounds[2]
                trace = []
                for cut in cuts_after:
                    component = connected_clearance(pocket, cut.remaining, seed[0], radius)
                    trace.append({'east_x_mm': None if component.is_empty else component.bounds[2],
                                  'removed_mm2': cut.removed_mm2,
                                  'cut_max_x_mm': max(x for x, _ in cut.cut),
                                  'family': 'fallback' if len(cut.cut) > 2 and any(math.dist(a, b) >= .75-1e-9 for a, b in zip(cut.cut, cut.cut[1:])) else 'other'})
                return cuts_after, {'stop': stop, 'start_east_x_mm': start_east, 'trace': trace, 'cut_count': len(cuts_after),
                                    'removed_mm2': live.area-stock_after.area,
                                    'feed_mm': sum(c.travel_mm for c in cuts_after),
                                    'peak_deg': max((c.peak_deg for c in cuts_after), default=None),
                                    'east_x_mm': None if clear_after.is_empty else clear_after.bounds[2]}

            _, sweep_report['control_followup'] = continuation(remaining, pose)
            if sweep is not None:
                tail = sweep.cut[-1]
                before = next(xy for xy in reversed(sweep.cut[:-1]) if xy != tail)
                followups, sweep_report['sweep_followup'] = continuation(
                    sweep.remaining, (tail, tuple(b-a for a, b in zip(before, tail))))
    if review_gcode is not None and reason != 'entry_required' and (initial_state is None or cuts or sweep):
        opening = Path(review_gcode).with_suffix('.opening.svg')
        if opening.exists():
            raise FileExistsError(f'review companion already exists: {opening}')
        label = reason if initial_state is None else f'{reason}; modeled helix and seed cuts omitted'
        preview = [*cuts, sweep, *followups] if sweep is not None else cuts
        if sweep is not None:
            label = f'east sweep after {label}'
        write_review_gcode(review_gcode, preview, seed[0], label)
        link, cut = (preview[0].link, preview[0].cut) if preview else ((), ())
        write_opening_review(opening, pocket, stock, link, cut)
    frontier = nearby_frontier(pocket, remaining, last_xy, radius, extra_reach=.25)
    report = {'stop': reason, 'regions': len(regions), 'cut_count': len(cuts),
            'corner_cut_count': sum(len(cut.cut) > 2 for cut in cuts),
            'initial_stock_mm2': stock.area, 'removed_mm2': stock.area - remaining.area,
            'assumed_preclear_mm2': pocket.difference(stock).area if initial_state is None else 0.,
            'modeled_handoff_removed_mm2': pocket.difference(stock).area if initial_state is not None else None,
            'seed_contact_deg': contact_angle(seed[0], radius, stock),
            'received_initial_state': initial_state is not None, 'start_xy_mm': seed[0],
            'reachable_residual_mm2': remaining.intersection(reachable).area,
            'last_selection_counts': diagnostics[-1] if diagnostics else {},
            'last_taper_contact_failures': dict(overload_phases.get(len(diagnostics)-1, {})),
            'neckward_removed_mm2': stock.intersection(neck_target).difference(remaining).area,
            'seed_clearance_gain_mm2': clearance.difference(initial_clearance).area,
            'seed_clearance_east_x_mm': None if clearance.is_empty else clearance.bounds[2],
            'seed_clearance_reaches_neck_probe': clearance.covers(Point(36., 23.)),
            'feed_mm': sum(cut.travel_mm for cut in cuts),
            'peak_contact_deg': max((cut.peak_deg for cut in cuts), default=None),
            'last_xy_mm': last_xy,
            'last_forward_clearance_mm': departure,
            'nearby_frontier_mm': frontier.length,
            'nearby_frontier_bounds_mm': None if frontier.is_empty else frontier.bounds,
            'last_stock_distance_mm': None if remaining.is_empty else point.distance(remaining),
            'last_wall_distance_mm': point.distance(pocket.boundary)}
    if wide_east_sweep and reason != 'entry_required':
        sweep_report['preview_cut_count'] = len(cuts) + (sweep is not None) + len(followups)
        report['wide_east_sweep'] = sweep_report
    if clearance_straight_fallback:
        other_cuts = [i for i, row in enumerate(diagnostics[:len(cuts)], 1) if not row.get('final_retry_eligible')]
        report['clearance_straight_cuts'] = len(cuts)-len(other_cuts)
        report['non_fallback_cut_indices'] = other_cuts
    if section_widen_retry:
        report['widen_retry_cuts'] = sum('scored_retry_eligible' in row for row in diagnostics)
    if section_small_retry:
        if section_extend_rays:
            report['small_retry_ray_extensions'] = ray_extensions
        report['small_retry_cuts'] = sum('final_retry_eligible' in row for row in diagnostics)
    if with_section_bites or section_bites_last:
        report['final_section_bite_spans'] = section_bite_spans(regions, clearance, search_west=section_search_west)
    if section_follow:
        audit = []
        sections = section_bite_spans(regions, clearance, search_west=section_search_west, fit_width=section_fit_width)
        proposal_count = sum(1 for _ in section_follow_cuts(sections, remaining, radius,
                                                          turn_exits=section_turn_exits, audit=audit,
                                                          taper_entry=section_taper_entry))
        report['final_section_follow'] = {'sections': sections, 'profiles': audit, 'proposal_count': proposal_count,
                                          'first_overloads': follow_overloads.get(len(diagnostics)-1, [])}
    if section_small_retry and reason == 'stalled':
        audit = []
        count = sum(1 for _ in small_section_cuts(sections, remaining, radius, turn_exits=section_turn_exits, audit=audit))
        report['final_small_retry'] = {'proposal_count': count, 'entry_shapes': audit}
        if section_extend_rays:
            failures = [row for row in follow_overloads.get(len(diagnostics)-1, ()) if row['family'] == 'extended_ray']
            summary = overload_summary(failures)
            report['terminal_extension_overloads'] = summary
            if section_relief_probe and summary['chord_bounds_mm'] is not None:
                _, low, _, high = summary['chord_bounds_mm']
                pose = last_xy, last_heading
                routes = (*waypoints, *propose_waypoints(remaining, pose)) if with_live_detours else waypoints
                bodies = list(small_section_cuts(sections, remaining, radius, ray_length=1.65))
                trials = []
                for depth in (.015, .03, .06):
                    def candidates():
                        for body in bodies:
                            path = relieve_contour(body, low, high, depth)
                            yield path
                            if section_turn_exits:
                                yield roll_off(path, .25, .0025)

                    counts = Counter()
                    measurements = []

                    def measure_clearance(_key, choice):
                        component = connected_clearance(pocket, choice.remaining, seed[0], radius)
                        measurements.append(dict(removed_mm2=choice.removed_mm2, peak_deg=choice.peak_deg,
                                                 **clearance_delta(clearance, component)))

                    choice = choose_front_cut(pocket, remaining, pose, candidates(), radius, waypoints=routes,
                                              diagnostics=counts, priority_score=lambda live: -live.area,
                                              on_eligible=measure_clearance, **gates)
                    shifts = [row for row in measurements if row['east_shift_mm'] is not None]
                    trials.append({'relief_mm': depth, 'gates': dict(counts),
                                   'best_removed_mm2': None if choice is None else choice.removed_mm2,
                                   'best_peak_deg': None if choice is None else choice.peak_deg,
                                   'most_eastward': max(shifts, key=lambda row: row['east_shift_mm'], default=None),
                                   'max_new_connected_mm2': max((row['new_connected_mm2'] for row in measurements), default=None),
                                   'east_advances_at_least_001_mm': sum(row['east_shift_mm'] >= .001 for row in shifts)})
                report['terminal_relief_probe'] = trials
        if section_ray_probe:
            pose = last_xy, last_heading
            routes = (*waypoints, *propose_waypoints(remaining, pose)) if with_live_detours else waypoints
            trials = []
            for length in (1.55, 1.65, 1.8):
                audit, counts = [], Counter()
                candidates = small_section_cuts(sections, remaining, radius, turn_exits=section_turn_exits,
                                                audit=audit, ray_length=length)
                choice = choose_front_cut(pocket, remaining, pose, candidates, radius, waypoints=routes,
                                          diagnostics=counts, priority_score=lambda live: -live.area, **gates)
                trials.append({'ray_length_mm': length, 'entry_shapes': audit, 'gates': dict(counts),
                               'best_removed_mm2': None if choice is None else choice.removed_mm2,
                               'best_peak_deg': None if choice is None else choice.peak_deg})
            report['terminal_ray_probe'] = trials
    if section_widen_probe and reason == 'stalled' and not clearance.is_empty:
        pose = last_xy, last_heading
        routes = (*waypoints, *propose_waypoints(remaining, pose)) if with_live_detours else waypoints
        gauge_x = clearance.bounds[2] - .75
        width = widest_span(clearance_sections(regions, clearance, (gauge_x,))[0])
        trials = []
        for row in wider_sections(regions, clearance):
            counts, accepted = Counter(), []

            def measure(_key, choice):
                component = connected_clearance(pocket, choice.remaining, seed[0], radius)
                gauge = clearance_sections(regions, component, (gauge_x,))[0]
                accepted.append(dict(width_gain_mm=widest_span(gauge)-width, removed_mm2=choice.removed_mm2,
                                     peak_deg=choice.peak_deg, **clearance_delta(clearance, component)))

            paths = small_section_cuts([row], remaining, radius, turn_exits=section_turn_exits, ray_length=2.75)
            choose_front_cut(pocket, remaining, pose, paths, radius, waypoints=routes, diagnostics=counts,
                             on_eligible=measure, **gates)
            trials.append({'anchor_x_mm': row['x_mm'], 'target_width_mm': row['target_width_mm'], 'gates': dict(counts),
                           'best_widening': max(accepted, key=lambda item: item['width_gain_mm'], default=None)})
        report['terminal_widen_probe'] = {'gauge_x_mm': gauge_x, 'baseline_width_mm': width, 'trials': trials}
    if probe_count and reason == 'stalled':
        pose = last_xy, last_heading
        routes = (*waypoints, *propose_waypoints(remaining, pose)) if with_live_detours else waypoints
        fractions = ((.25, .4, .5) if section_nominal_at_stall or section_bracket_at_stall
                     else (.4, .5) if section_shallow_approach else (.25,))

        def terminal_probes(advances):
            nonlocal entry_fraction
            for entry_fraction in fractions:
                yield from section_follow_cuts(sections, remaining, radius, turn_exits=section_turn_exits,
                                               taper_only=section_taper_at_stall, on_profile=note_profile,
                                               entry_fraction=entry_fraction, advances=advances)
        def measure(advances):
            counts = Counter()
            trial = len(diagnostics)
            choice = choose_front_cut(pocket, remaining, pose, terminal_probes(advances), radius,
                                      waypoints=routes, diagnostics=counts,
                                      on_overload=lambda path, chord, angle: report_overload(trial, path, chord, angle),
                                      priority_score=lambda live: -live.area, **gates)
            return {'gates': dict(counts), 'first_overloads': follow_overloads.pop(trial, []),
                    'best_removed_mm2': None if choice is None else choice.removed_mm2,
                    'best_peak_deg': None if choice is None else choice.peak_deg}

        if section_bracket_at_stall:
            report['terminal_advance_bracket'] = [dict(advance_mm=depth, **measure((depth,)))
                                                  for depth in (.01, .02, .03, .04, .05)]
        else:
            key = ('terminal_nominal_probe' if section_nominal_at_stall else
                   'terminal_approach_probe' if section_shallow_approach else 'terminal_taper_probe')
            report[key] = measure((0.,) if section_nominal_at_stall else (.05, .10, .15))
    if section_xs:
        report['clearance_sections'] = clearance_sections(regions, clearance, section_xs)
    if trace_clearance:
        probe = Point(36., 23.)
        trace = []
        travel = 0.
        for index, cut in enumerate((None, *cuts)):
            if cut is None:
                component = initial_clearance
            else:
                travel += cut.travel_mm
                component = connected_clearance(pocket, cut.remaining, seed[0], radius)
            motion = None if cut is None else json.dumps((cut.link, cut.cut), separators=(',', ':'))
            trace.append({'cut': index, 'feed_mm': travel, 'area_mm2': component.area,
                          'east_x_mm': None if component.is_empty else component.bounds[2],
                          'reaches_probe': component.covers(probe),
                          'motion_sha256': None if motion is None else hashlib.sha256(motion.encode('ascii')).hexdigest(),
                          'end_xy_mm': seed[0] if cut is None else cut.cut[-1],
                          'removed_mm2': 0. if cut is None else cut.removed_mm2})
        report['clearance_trace'] = trace
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-corners', action='store_true', help='also propose 3 mm tangent corner blends')
    parser.add_argument('--corner-runoff', type=float, default=0., metavar='MM',
                        help='extend the tangent exit and check it as part of the cut')
    parser.add_argument('--with-detours', action='store_true', help='try fixed seed-area waypoints after failed direct links')
    parser.add_argument('--with-live-detours', action='store_true', help='sample waypoints from current clearance')
    parser.add_argument('--with-shallow-fronts', action='store_true', help='retry with 0.25 mm straight immersion when the main proposals fail')
    parser.add_argument('--shallow-runoff', type=float, default=2., metavar='MM',
                        help='tangent exit distance for shallow retries')
    parser.add_argument('--shallow-rolloff', type=float, default=0., metavar='MM',
                        help='append a checked tangent quarter turn of this radius to shallow cuts')
    parser.add_argument('--shallow-rollon', type=float, default=0., metavar='MM',
                        help='also try a tangent quarter-turn approach at this radius')
    parser.add_argument('--with-shifted-joins', action='store_true', help='also shift shallow joins by 2 and 4 mm')
    parser.add_argument('--max-cuts', type=int, default=12, help='maximum accepted cuts in the offline trial')
    parser.add_argument('--with-taper', action='store_true', help='try tapered entries on shallow cuts')
    parser.add_argument('--with-clearance-tapers', action='store_true', help='sample tapered starts from live clearance')
    parser.add_argument('--with-early-exits', action='store_true', help='try rolling off clearance tapers 1 or 2 mm earlier')
    parser.add_argument('--require-clear-exit', action='store_true',
                        help='reject cuts that end without planar link clearance')
    parser.add_argument('--with-neck-front', action='store_true', help='also try the east side of mapped live frontier')
    parser.add_argument('--with-three-leg-links', action='store_true', help='try two waypoints after direct and one-waypoint links fail')
    parser.add_argument('--min-departure', type=float, default=0., metavar='MM',
                        help='require a checked straight departure before ranking cuts')
    parser.add_argument('--prioritize-neck', action='store_true', help='rank checked cuts by removal east of X24 first')
    parser.add_argument('--with-front-bites', action='store_true', help='try eased side cuts on the neck-facing frontier')
    parser.add_argument('--trace-clearance', action='store_true', help='include connected clearance after each cut')
    parser.add_argument('--prioritize-clearance', action='store_true', help='rank verified cuts by seed-connected eastward extent first')
    parser.add_argument('--with-wide-bites', action='store_true', help='also try a straight plateau between eased ramps')
    parser.add_argument('--lookahead-width', type=int, default=1,
                        help='preview a successor for this many top cuts (1 disables lookahead)')
    parser.add_argument('--lookahead-after', type=int, default=0,
                        help='number of accepted cuts before enabling lookahead')
    parser.add_argument('--section-x', type=float, action='append', default=[],
                        help='report terminal center clearance and domain spans at this X (repeatable)')
    section_mode = parser.add_mutually_exclusive_group()
    section_mode.add_argument('--with-section-bites', action='store_true',
                        help='try eastward bows across seed-connected sections during shallow retries')
    section_mode.add_argument('--section-bites-last', action='store_true',
                              help='try section bites only when the other families fail')
    parser.add_argument('--section-turn-exits', action='store_true',
                        help='also try quarter-turn retreats on last-resort section bites')
    parser.add_argument('--section-live-depth', action='store_true',
                        help='also try depths just past midpoint contact with live stock')
    parser.add_argument('--section-search-west', action='store_true',
                        help='try farther insets only if both default sections are too narrow')
    parser.add_argument('--section-follow', action='store_true',
                        help='also try cuts following stock contact across the open span')
    parser.add_argument('--section-fit-width', action='store_true',
                        help='search for the closest wider section beyond the default west insets')
    parser.add_argument('--section-taper-entry', action='store_true',
                        help='also try delaying contour advance until after the entry blend')
    parser.add_argument('--section-taper-at-stall', action='store_true',
                        help='audit entry tapers on final baseline stock without committing them')
    parser.add_argument('--section-shallow-approach', action='store_true',
                        help='audit longer entry blends on final baseline stock without committing them')
    parser.add_argument('--section-nominal-at-stall', action='store_true',
                        help='audit the nominal contact contour without extra advance at the baseline stall')
    parser.add_argument('--section-bracket-at-stall', action='store_true',
                        help='test intermediate advances independently on unchanged terminal stock')
    parser.add_argument('--section-small-retry', action='store_true',
                        help='try smaller contour advances only after standard cuts fail')
    parser.add_argument('--section-ray-probe', action='store_true',
                        help='audit longer rays at the small-retry stall without committing cuts')
    parser.add_argument('--section-extend-rays', action='store_true',
                        help='retry at 1.65 mm only when misses prevent all small candidates')
    parser.add_argument('--section-relief-probe', action='store_true',
                        help='test local contour relief over clustered overloads without committing edits to stock')
    parser.add_argument('--section-widen-probe', action='store_true',
                        help='compare wider anchor spans for terminal approach growth without committing cuts')
    parser.add_argument('--review-gcode', type=Path, help='save accepted XY paths to a new debug-only .nc file')
    parser.add_argument('--section-widen-retry', action='store_true',
                        help='try verified widening only after all other cuts fail')
    parser.add_argument('--full-stock', action='store_true',
                        help='start without assumed clearance and report whether an entry is required')
    args = parser.parse_args()
    if (args.with_section_bites or args.section_bites_last) and not args.with_shallow_fronts:
        parser.error('section bites require --with-shallow-fronts')
    try:
        result = check_neck(with_corners=args.with_corners, corner_runoff=args.corner_runoff,
                            with_detours=args.with_detours, with_live_detours=args.with_live_detours,
                            with_shallow_fronts=args.with_shallow_fronts, shallow_runoff=args.shallow_runoff,
                            shallow_rolloff=args.shallow_rolloff, shallow_rollon=args.shallow_rollon,
                            with_shifted_joins=args.with_shifted_joins, max_cuts=args.max_cuts, with_taper=args.with_taper,
                            with_clearance_tapers=args.with_clearance_tapers, with_early_exits=args.with_early_exits,
                            require_clear_exit=args.require_clear_exit, with_neck_front=args.with_neck_front,
                            with_three_leg_links=args.with_three_leg_links, min_departure=args.min_departure, prioritize_neck=args.prioritize_neck, with_front_bites=args.with_front_bites,
                            trace_clearance=args.trace_clearance, prioritize_clearance=args.prioritize_clearance,
                            with_wide_bites=args.with_wide_bites, lookahead_width=args.lookahead_width,
                            lookahead_after=args.lookahead_after, section_xs=args.section_x, with_section_bites=args.with_section_bites,
                            section_bites_last=args.section_bites_last, section_turn_exits=args.section_turn_exits,
                            section_live_depth=args.section_live_depth, section_search_west=args.section_search_west,
                            section_follow=args.section_follow, section_fit_width=args.section_fit_width, section_taper_entry=args.section_taper_entry,
                            section_taper_at_stall=args.section_taper_at_stall,
                            section_shallow_approach=args.section_shallow_approach,
                            section_nominal_at_stall=args.section_nominal_at_stall,
                            section_bracket_at_stall=args.section_bracket_at_stall, section_small_retry=args.section_small_retry,
                            section_ray_probe=args.section_ray_probe, section_extend_rays=args.section_extend_rays, section_relief_probe=args.section_relief_probe,
                            section_widen_probe=args.section_widen_probe, review_gcode=args.review_gcode, section_widen_retry=args.section_widen_retry,
                            full_stock=args.full_stock)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
