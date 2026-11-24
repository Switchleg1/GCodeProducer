"""Read-only comparison of clearing strategies on a model's saved CAM setup (no G-code is written).

The setup, placement and machine come from the desktop settings for the given
model file; nothing is saved back. Each strategy is run in memory on the
clearing operations (pocket and waterfall) and the run time, the preview's
machine-time estimate and any incomplete or safety warnings are reported.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QSettings
from gcodeproducer.core.cam.cam_setup import CAMSetup
from gcodeproducer.core.gcode.toolpath import build_toolpath
from gcodeproducer.core.jobs.placement import Placement
from gcodeproducer.core.jobs.session import build_job, load_mesh, slice_job
from gcodeproducer.core.libraries.library_set import LibrarySet
from gcodeproducer.core.settings import preferences


def model_key(kind, path):
    """The desktop's per-model settings key (see MainWindow._model_key)."""
    return f'{kind}/' + hashlib.md5(str(Path(path).resolve()).lower().encode()).hexdigest()


def run(path, settings, library, strategy, follow_surface=None, material_limit=None, direction=None):
    placement_raw = None
    if path == 'session':
        # The desktop's current work session: its single model, setup and placement.
        session = json.loads(settings.value('workSession/default'))
        if session['workflow'] != 'cam' or len(session['models']) != 1:
            raise ValueError('The current work session is not a single-model CAM session')
        model, = session['models']
        path, data = model['path'], session['cam']['setup']
        placement_raw = json.dumps(model['placement'])
    else:
        raw = settings.value(model_key('cam', path))
        if raw is None:
            raise ValueError(f'No saved CAM setup for {path}')
        data = json.loads(raw)
    changed = []
    for group in data.get('groups', []):
        for op in group.get('operations', []):
            if strategy and op.get('kind') in ('pocket', 'waterfall'):
                changed.append(f"{op.get('name')}: {op.get('strategy')} → {strategy}")
                op['strategy'] = strategy
            if follow_surface is not None and op.get('kind') == 'waterfall':
                op['follow_surface'] = follow_surface
                changed.append(f"{op.get('name')}: follow the surface within each depth {'on' if follow_surface else 'off'}")
            if direction is not None and op.get('kind') in ('pocket', 'waterfall'):
                changed.append(f"{op.get('name')}: cutting direction {op.get('cut_direction')} → {direction}")
                op['cut_direction'] = direction
            if material_limit is not None and op.get('kind') in ('pocket', 'waterfall'):
                changed.append(f"{op.get('name')}: material boundary {op.get('material_limit')} → {material_limit:g} mm")
                op['material_limit'] = material_limit
    setup = CAMSetup.from_dict(copy.deepcopy(data))
    placement_raw = placement_raw or settings.value(model_key('placement_cam', path))
    placement = Placement.from_dict(json.loads(placement_raw)) if placement_raw else Placement()
    machine = library.machines.get(settings.value('machine/cam'))
    job = build_job('cam', machine, mesh=load_mesh(path), placement=placement,
                    tools=library.consumables_for(machine, 'tool'), cam_setup=setup,
                    preferences=preferences.load(library.root))
    messages = []
    start = time.perf_counter()
    slice_job(job, log=messages.append)
    seconds = time.perf_counter() - start
    incomplete = any(w.startswith('DEBUG ONLY') for w in job.warnings)
    unsafe = any('rapid motion contacts' in w.lower() or 'intersects a protected holding tab' in w.lower()
                 for w in job.warnings)
    return dict(strategy=strategy or 'as saved', changed=changed, complete=not incomplete, safety_findings=unsafe,
                left_above_model=left_above_model(job, data),
                compute_s=round(seconds, 1), machine_s=round(build_toolpath(job.program).stats['est_time_s'], 1),
                layers=len(job.layers), lines=len(job.program.lines),
                clearing_log=[m.strip() for m in messages if 'Adaptive' in m or 'Waterfall' in m or 'Pocket' in m][:12],
                warnings=job.warnings[:12])


def left_above_model(job, data):
    """After each operation: material left above the model plus that operation's stock to leave (mm³, and its peak mm).

    Measured on the material grid of the emitted program, against the model's
    highest point in each cell; cells without model below the blank top are
    compared with the end depth of the run (they are counted only above it).
    """
    import numpy as np
    from gcodeproducer.core.cam.drop_surface import DropSurface
    snapshots = getattr(job, 'material_results', None) or []
    if len(snapshots) < 2:
        return {}
    heights0 = snapshots[0]['heights']
    ny, nx = heights0.shape
    lo, hi = (np.asarray(v, float) for v in job.cam_setup.stock.bounds)
    xs = lo[0] + (np.arange(nx) + .5)*(hi[0]-lo[0])/nx
    ys = lo[1] + (np.arange(ny) + .5)*(hi[1]-lo[1])/ny
    gx, gy = np.meshgrid(xs, ys)
    cell = max((hi[0]-lo[0])/nx, (hi[1]-lo[1])/ny)
    surface = DropSurface(job.mesh, lo[:2] - cell, hi[:2] + cell, cell/2, 10**8)
    model = surface.heights(np.column_stack((gx.ravel(), gy.ravel())), cell/2).reshape(ny, nx)
    resolution = cell
    ops = [o for g in data.get('groups', []) for o in g.get('operations', [])]
    out = {}
    for snap, op in zip(snapshots[1:], ops):
        floor = np.where(np.isfinite(model), model + float(op.get('stock', 0)), -np.inf)
        excess = np.clip(snap['heights'] - floor, 0, None)
        excess = np.where(np.isfinite(floor), excess, 0.)  # open areas are judged by coverage, not here
        cut = snap['heights'] < heights0 - 1e-6
        near = cut | (np.isfinite(model) & (excess > 0))
        out[snap['label']] = {'mm3_above_model': round(float(excess[near].sum()*resolution**2), 1),
                              'peak_mm': round(float(excess[near].max()) if near.any() else 0., 2)}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', help='model file the CAM setup was saved for, or "session" for the current work session')
    parser.add_argument('--strategy', action='append', default=[],
                        help='clearing strategy to try (repeatable); "saved" keeps the saved one')
    parser.add_argument('--follow-surface', choices=('on', 'off'), help='override Waterfall "Follow the surface within each depth"')
    parser.add_argument('--material-limit', type=float, help='override Pocket/Waterfall "Material boundary" (mm)')
    parser.add_argument('--direction', choices=('machine', 'climb', 'conventional', 'meander'),
                        help='override Pocket/Waterfall cutting direction')
    args = parser.parse_args()
    settings = QSettings('GCodeProducer', 'GCodeProducer')
    library = LibrarySet().load()
    for strategy in args.strategy or ['saved']:
        report = run(args.model, settings, library, None if strategy == 'saved' else strategy,
                     None if args.follow_surface is None else args.follow_surface == 'on', args.material_limit,
                     args.direction)
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
