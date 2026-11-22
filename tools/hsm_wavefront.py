"""Offline wavefront clearing: command line and review output.

The planner lives in gcodeproducer.core.cam.wavefront; this module keeps the names it had,
the debug-only review writer and the command line.
"""
import argparse
import json
import sys
from pathlib import Path

from shapely.geometry import LineString

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gcodeproducer.core.cam.wavefront import *  # noqa: F401,F403
from gcodeproducer.core.cam.wavefront import clear_depths, clear_pocket, write_program  # noqa: F401
from gcodeproducer.core.cam.wavefront.wavefront_constants import *  # noqa: F401,F403
from gcodeproducer.core.geometry.polygon_parts import polygons  # noqa: F401
from tools.hsm_replay_overlay import write_overlay


def write_review(path, pocket, strokes, residual, report):
    """Save XY geometry for a viewer. G0 marks a retract and rapid; helix entries are not included."""
    path = Path(path)
    overlay = path.with_suffix('.svg')
    cuts = sum(stroke.kind != 'link' for stroke in strokes)
    with path.open('x', encoding='ascii', newline='\n') as out:
        out.write('(DEBUG ONLY - XY GEOMETRY REVIEW - DO NOT RUN ON A MACHINE)\n'
                  f'(Wavefront trial: {report["stop"]}, {cuts} cuts, {report["retract_rapids"]} retracts; '
                  'helix entries omitted)\n'
                  '(Each G0 stands for a retract, rapid and re-entry that are not planned here)\n'
                  '(No Z, entry, spindle, tool or feed schedule; rounded XY not replayed)\nG21\nG90\n')
        number, joined = 0, False
        for stroke in strokes:
            points = list(LineString(stroke.points).simplify(.002).coords)
            if stroke.kind == 'link':
                out.write('(Stay-down link through cleared area)\n')
                joined = True
            else:
                number += 1
                out.write(f'(Cut {number}: {stroke.kind}, stepover {stroke.stepover_mm:g} mm, '
                          f'sampled peak {stroke.peak_deg:.1f} deg)\n')
                if not joined:
                    out.write(f'G0 X{points[0][0]:.4f} Y{points[0][1]:.4f}\n')
                joined = False
            for x, y in points[1:]:
                out.write(f'G1 X{x:.4f} Y{y:.4f}\n')
        out.write('M2\n')
    with overlay.open('x', encoding='ascii', newline='\n') as out:
        write_overlay(out, pocket, residual,
                      [(n, list(LineString(s.points).simplify(.01).coords), s.kind == 'link')
                       for n, s in enumerate(strokes, 1)],
                      legend='Wavefront trial | blue: cuts | gray: stay-down links in cleared area | '
                             'orange: reachable stock left | retracts not drawn')


if __name__ == '__main__':
    from tools.check_hsm_neck import neck_fixture

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pocket-wkt', type=Path, help='pocket outline as a WKT polygon; default is the two-lobe fixture')
    parser.add_argument('--review-gcode', type=Path, help='save cuts to a new debug-only .nc file and .svg overlay')
    parser.add_argument('--islands', type=int, help='number of helical islands; default is chosen from the shape')
    parser.add_argument('--placement', choices=('lobes', 'thirds', 'widest'), default='lobes',
                        help='one island per lobe, spread along the long axis, or the widest remaining spots')
    parser.add_argument('--no-wall-pull-back', action='store_true',
                        help='roll arcs off before the wall instead of following it back')
    parser.add_argument('--no-wall-finish', action='store_true', help='skip the finish along wall that still has stock on it')
    parser.add_argument('--time-budget', type=float, help='stop adding passes after this many seconds')
    parser.add_argument('--sample-step', type=float, default=.1, help='contact sampling distance in mm')
    parser.add_argument('--bottom', type=float, help='clear in levels down to this Z (top is 0); needs --step-down')
    parser.add_argument('--step-down', type=float, help='largest depth of one level in mm')
    parser.add_argument('--program', type=Path, help='with --bottom: save all levels as one new XYZ .nc for a viewer')
    args = parser.parse_args()
    if args.pocket_wkt is not None:
        from shapely import from_wkt
        fixture = from_wkt(args.pocket_wkt.read_text(encoding='utf-8'))
    else:
        fixture, _ = neck_fixture()
    options = dict(islands=args.islands, placement=args.placement, wall_pull_back=not args.no_wall_pull_back,
                   wall_profile=not args.no_wall_finish, time_budget=args.time_budget, sample_step=args.sample_step)
    if args.bottom is not None:
        levels = clear_depths(fixture, 2., bottom=args.bottom, step_down=args.step_down or -args.bottom, **options)
        if args.program is not None:
            write_program(args.program, levels)
        summary = [{'z_mm': z, **{k: report[k] for k in ('stop', 'front_arcs', 'reachable_residual_mm2', 'seconds')},
                    'machine_s': report['machine_time']['total_s']} for z, _, _, report in levels]
        print(json.dumps({'levels': summary, 'machine_s': sum(level['machine_s'] for level in summary),
                          'compute_s': sum(level['seconds'] for level in summary)}, indent=2))
        raise SystemExit(0)
    result = clear_pocket(fixture, 2., islands=args.islands, placement=args.placement,
                          wall_pull_back=not args.no_wall_pull_back, wall_profile=not args.no_wall_finish, time_budget=args.time_budget,
                          sample_step=args.sample_step)
    if args.review_gcode is not None:
        write_review(args.review_gcode, fixture, *result)
    print(json.dumps(result[2], indent=2))
