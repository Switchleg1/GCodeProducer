"""An XYZ program of wavefront levels for a viewer or simulator."""
import math
from pathlib import Path

from shapely import points
from shapely.geometry import LineString

from .wavefront_constants import (MACHINE_DEFAULTS)


def write_program(path, levels, *, top=0., machine=None):
    """Write the levels as one XYZ program for a viewer or simulator; never overwrites.

    Every cut and link runs at its level's depth. A helix enters each start
    from just above the floor of the level above. Wherever a cut does not
    start where the last ended, the cutter rises to RETRACT above the top,
    crosses at rapid and comes down at rapid to just above the level above,
    then at the plunge feed: into a helix at a start, or straight down into
    space already cleared at this level. Untested on a machine.
    """
    settings = dict(MACHINE_DEFAULTS, **(machine or {}))
    safe = top + settings['retract_mm']
    cut_f, link_f = settings['cut_feed_mm_min'], settings['link_feed_mm_min']
    plunge_f = settings['plunge_feed_mm_min']
    path = Path(path)
    with path.open('x', encoding='ascii', newline='\n') as out:
        out.write('(WAVEFRONT TRIAL - INCOMPLETE - FOR A VIEWER OR SIMULATOR ONLY - NOT RUN ON A MACHINE)\n'
                  f'({len(levels)} levels, top Z{top:.3f}, bottom Z{levels[-1][0]:.3f})\n'
                  '(No tool change, spindle, coolant, tabs or allowance)\nG21\nG90\nG17\n'
                  f'G0 Z{safe:.4f}\n')
        above, here = top, None
        for z, strokes, _, report in levels:
            out.write(f'(Level Z{z:.3f}: {report["front_arcs"]} fronts, stop {report["stop"]})\n')
            helices = {entry['stroke']: entry['helix_xyz'] for entry in report.get('entries', [])}
            for index, stroke in enumerate(strokes):
                points = list(LineString(stroke.points).simplify(.002).coords)
                if here is None or math.dist(here, points[0]) > 1e-6 or index in helices:
                    helix = helices.get(index)
                    start = helix[0][:2] if helix else points[0]
                    out.write(f'G0 Z{safe:.4f}\nG0 X{start[0]:.4f} Y{start[1]:.4f}\n'
                              f'G0 Z{above + .5:.4f}\n')
                    if helix:
                        out.write(f'(Helix entry)\nG1 Z{helix[0][2]:.4f} F{plunge_f:g}\n')
                        for x, y, hz in helix[1:]:
                            out.write(f'G1 X{x:.4f} Y{y:.4f} Z{hz:.4f}\n')
                        if math.dist(helix[-1][:2], points[0]) > 1e-6:
                            out.write(f'G1 X{points[0][0]:.4f} Y{points[0][1]:.4f} Z{z:.4f}\n')
                    else:
                        out.write(f'G1 Z{z:.4f} F{plunge_f:g}\n')
                feed = link_f if stroke.kind == 'link' else cut_f
                out.write(f'({stroke.kind})\nG1 X{points[1][0]:.4f} Y{points[1][1]:.4f} Z{z:.4f} F{feed:g}\n'
                          if len(points) > 1 else f'({stroke.kind})\n')
                for x, y in points[2:]:
                    out.write(f'G1 X{x:.4f} Y{y:.4f}\n')
                here = points[-1]
            above = z
        out.write(f'G0 Z{safe:.4f}\nM2\n')
    return path
