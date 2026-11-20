"""Offline XY sweep replay for the single-plane CamBam TrochoPock reference.

Not a general G-code interpreter or a machine clearance/engagement check.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

from shapely.geometry import LineString, Polygon, mapping

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.hsm_contact_replay import distance_percentile, sampled_contact
from tools.hsm_replay_overlay import write_overlay


WORD = re.compile(r'([A-Z])([+-]?(?:\d+(?:\.\d*)?|\.\d+))')
IGNORED_M = {'M3', 'M5', 'M10', 'M11', 'M30'}
BUFFER_SEGMENTS = 64
CLEAR_AREA_MM2 = 1e-8  # numerical noise only, not a clearance allowance


def read_pocket(path):
    """Read one untransformed straight-sided closed pocket, with unset stock."""
    root = ElementTree.parse(path).getroot()
    outlines, operations = root.findall('.//objects/*'), root.findall('.//machineops/*')
    if len(outlines) != 1 or len(operations) != 1:
        raise ValueError('expected one outline and one operation')
    outline, op = outlines[0], operations[0]
    if (op.get('{http://www.w3.org/2001/XMLSchema-instance}type') != 'MOPTrochopock'
            or op.get('Enabled') != 'true' or op.findtext('WorkPlane') != 'XY'
            or [p.text for p in op.findall('primitive/prim')] != [outline.get('id')]
            or outline.tag != 'pline' or outline.get('Closed') != 'true'
            or outline.find('mat') is None or outline.find('mat').get('m') != 'Identity'):
        raise ValueError('expected a single XY TrochoPock with an untransformed closed polyline')
    for stock in root.findall('.//Stock'):
        if not all(tuple(map(float, stock.findtext(tag, '').split(','))) == (0., 0.)
                   for tag in ('PMin', 'PMax')):
            raise ValueError('explicit stock is not supported by the full-pocket assumption')
    points = [tuple(map(float, p.text.split(','))) for p in outline.findall('pts/p')]
    if len(points) < 3 or any(len(p) != 3 or p[2] != 0 or not all(map(math.isfinite, p)) for p in points):
        raise ValueError('expected straight polyline vertices at Z0')
    pocket = Polygon([p[:2] for p in points])
    radius, top, depth = (float(op.findtext(tag)) for tag in ('ToolDiameter', 'StockSurface', 'TargetDepth'))
    if (not pocket.is_valid or pocket.area <= 0 or not all(map(math.isfinite, (radius, top, depth)))
            or radius <= 0 or not depth < top or float(op.findtext('RoughingClearance')) != 0):
        raise ValueError('expected valid pocket, positive tool diameter, negative cut from stock top and zero allowance')
    return pocket, radius / 2, depth


def arc_points(start, end, offset, sign, chord_error):
    i, j = offset
    radius = math.hypot(i, j)
    cx, cy = start[0] + i, start[1] + j
    if radius <= 0 or abs(math.hypot(end[0]-cx, end[1]-cy) - radius) > .001:
        raise ValueError('invalid incremental-I/J arc')
    angle = math.atan2(-j, -i)
    sweep = (sign * (math.atan2(end[1]-cy, end[0]-cx) - angle)) % math.tau if end != start else math.tau
    max_angle = min(.25, 4 * math.asin(math.sqrt(min(1., chord_error / (2 * radius)))))
    count = max(2, math.ceil(sweep / max_angle))
    points = [start]
    for k in range(1, count):
        t = angle + sign * sweep * k / count
        points.append((cx + radius * math.cos(t), cy + radius * math.sin(t)))
    return [*points, end], radius * sweep


def level_moves(text, depth, chord_error):
    """Yield only numbered target-level XY moves."""
    for number, mode, points, length, at_level in _feed_moves(text, depth, chord_error):
        if at_level:
            yield number, mode, points, length


def _feed_moves(text, depth, chord_error):
    """Include above-plane feed projections for entry uncertainty tagging."""
    if not math.isfinite(chord_error) or chord_error <= 0:
        raise ValueError('chord error must be positive and finite')
    xyz = (None, None, None)
    metric = absolute = False
    for number, line in enumerate(text.splitlines(), 1):
        command = ''.join(line.partition(';')[0].upper().split())
        if not command:
            continue
        pairs = WORD.findall(command)
        mode = ''.join(pairs[0]) if pairs else ''
        words = {k: float(v) for k, v in pairs[1:]}
        if (''.join(k+v for k, v in pairs) != command or len(words) != len(pairs)-1
                or not all(map(math.isfinite, words.values()))):
            raise ValueError(f'line {number}: unsupported syntax')
        if mode == 'G21' and not words:
            metric = True
        elif mode == 'G90' and not words:
            absolute = True
        elif mode in IGNORED_M and (not words or (mode == 'M3' and set(words) == {'S'})):
            continue
        elif mode in {'G0', 'G1', 'G2', 'G3'} and metric and absolute:
            arc = mode in {'G2', 'G3'}
            if (set(words) - set('XYZF' + ('IJ' if arc else ''))
                    or (arc and not {'I', 'J'} <= words.keys())):
                raise ValueError(f'line {number}: unsupported motion words')
            start = xyz
            xyz = tuple(words.get(axis, value) for axis, value in zip('XYZ', start))
            if xyz[2] is None or xyz[2] < depth:
                raise ValueError(f'line {number}: unknown Z or motion below the target plane')
            if mode == 'G0' and ('X' in words or 'Y' in words) and depth in (start[2], xyz[2]):
                raise ValueError(f'line {number}: XY rapid at target depth')
            if mode == 'G0':
                continue
            at_level = start[2] == depth == xyz[2]
            if None in (*start[:2], *xyz[:2]):
                raise ValueError(f'line {number}: unknown feed XY')
            if not arc and start == xyz:
                continue
            if arc:
                points, length = arc_points(start[:2], xyz[:2], (words['I'], words['J']),
                                            1 if mode == 'G3' else -1, chord_error)
            else:
                points, length = [start[:2], xyz[:2]], math.dist(start[:2], xyz[:2])
            yield number, mode, points, length, at_level
        else:
            raise ValueError(f'line {number}: unsupported command {mode}')


def replay(pocket, radius, depth, text, chord_error, contact_step=None):
    moves = _feed_moves(text, depth, chord_error)
    return replay_strokes(pocket, pocket, radius, depth, moves, chord_error, contact_step)


def replay_strokes(pocket, initial_stock, radius, depth, moves, chord_error, contact_step=None):
    """Replay ordered XY strokes against explicit initial stock, not an assumed full pocket."""
    if not initial_stock.is_empty and not pocket.covers(initial_stock):
        raise ValueError('initial stock must be inside the diagnostic pocket')
    reachable = pocket.buffer(-radius, quad_segs=BUFFER_SEGMENTS).buffer(radius, quad_segs=BUFFER_SEGMENTS)
    reachable = reachable.intersection(pocket)
    swept = Polygon()
    rows = []
    contacts = []
    unaffected_contacts = []
    affected_samples = 0
    remaining = initial_stock
    entry_shadow = Polygon()
    for number, mode, points, length, at_level in moves:
        line = LineString(points)
        if not at_level:
            if contact_step is not None:
                margin = chord_error + .001 if mode in ('G2', 'G3') else 0.
                projection = line.buffer(radius + margin, quad_segs=BUFFER_SEGMENTS)
                entry_shadow = entry_shadow.union(projection.intersection(remaining))
            continue
        stroke = line.buffer(radius, quad_segs=BUFFER_SEGMENTS)
        new = stroke.difference(swept)
        rows.append({'line': number, 'motion': mode, 'length_mm': length,
                     'new_sweep_mm2': new.area, 'new_pocket_sweep_mm2': new.intersection(pocket).area,
                     'removed_stock_mm2': new.intersection(initial_stock).area})
        if contact_step is not None:
            samples = list(sampled_contact(points, remaining, radius, contact_step, BUFFER_SEGMENTS))
            rows[-1]['sampled_peak_contact_deg'] = max((a for a, _ in samples), default=None)
            affected = (not entry_shadow.is_empty
                        and stroke.intersection(entry_shadow).area > CLEAR_AREA_MM2)
            rows[-1]['contact_entry_uncertain'] = affected
            if affected:
                affected_samples += len(samples)
                entry_shadow = entry_shadow.difference(stroke)
            else:
                unaffected_contacts.extend(samples)
            contacts.extend(samples)
            remaining = remaining.difference(stroke)
        swept = swept.union(stroke)
    if not rows:
        raise ValueError('no XY strokes at target depth')
    reachable_stock = reachable.intersection(initial_stock)
    residual = reachable_stock.difference(swept)
    clear = [row for row in rows if row['new_sweep_mm2'] <= CLEAR_AREA_MM2]
    air = [row for row in rows if row['removed_stock_mm2'] <= CLEAR_AREA_MM2]
    report = {'depth_mm': depth, 'tool_diameter_mm': radius * 2, 'arc_chord_error_mm': chord_error,
            'nominal_mm2': pocket.area, 'reachable_mm2': reachable.area, 'initial_reachable_stock_mm2': reachable_stock.area,
            'reachable_residual_mm2': residual.area, 'outside_pocket_sweep_mm2': swept.difference(pocket).area,
            'stroke_count': len(rows), 'feed_distance_mm': sum(r['length_mm'] for r in rows),
            'air_stroke_count': len(air), 'air_distance_mm': sum(r['length_mm'] for r in air),
            'already_swept_stroke_count': len(clear),
            'already_swept_distance_mm': sum(r['length_mm'] for r in clear),
            'already_swept_straight_count': sum(r['motion'] == 'G1' for r in clear)}
    if contact_step is not None:
        report.update(contact_step_mm=contact_step, contact_samples=len(contacts),
                      sampled_peak_contact_deg=max((a for a, _ in contacts), default=None),
                      sampled_p95_contact_deg=distance_percentile(contacts, .95),
                      entry_uncertain_samples=affected_samples,
                      sampled_peak_outside_entry_shadow_deg=max((a for a, _ in unaffected_contacts), default=None),
                      sampled_p95_outside_entry_shadow_deg=distance_percentile(unaffected_contacts, .95))
    return report, residual, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pocket', type=Path, help='native CamBam .cb file')
    parser.add_argument('gcode', type=Path, help='matching CamBam G-code')
    parser.add_argument('--chord-error', type=float, default=.0025, metavar='MM')
    parser.add_argument('--contact-step', type=float, metavar='MM', help='also sample planar contact along each stroke')
    parser.add_argument('--details', type=Path, help='write a new JSON file with residual geometry and per-stroke data')
    parser.add_argument('--overlay', type=Path, help='write a new SVG plot with numbered strokes and residual stock')
    args = parser.parse_args()
    try:
        pocket, radius, depth = read_pocket(args.pocket)
        text = args.gcode.read_text(encoding='utf-8-sig')
        report, residual, rows = replay(pocket, radius, depth, text, args.chord_error, args.contact_step)
        if args.overlay:
            moves = level_moves(text, depth, args.chord_error)
            strokes = ((number, points, row['new_sweep_mm2'] <= CLEAR_AREA_MM2)
                       for (number, _, points, _), row in zip(moves, rows, strict=True))
            with args.overlay.open('x', encoding='utf-8') as out:
                write_overlay(out, pocket, residual, strokes)
        if args.details:
            with args.details.open('x', encoding='utf-8') as out:
                json.dump({'summary': report, 'residual_xy_mm': mapping(residual), 'strokes': rows}, out, indent=2)
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
