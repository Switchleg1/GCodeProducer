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


def run(path, settings, library, strategy):
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
    setup = CAMSetup.from_dict(copy.deepcopy(data))
    placement_raw = settings.value(model_key('placement_cam', path))
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
                compute_s=round(seconds, 1), machine_s=round(build_toolpath(job.program).stats['est_time_s'], 1),
                layers=len(job.layers), lines=len(job.program.lines),
                clearing_log=[m.strip() for m in messages if 'Adaptive' in m or 'Waterfall' in m or 'Pocket' in m][:12],
                warnings=job.warnings[:12])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', help='model file the CAM setup was saved for')
    parser.add_argument('--strategy', action='append', default=[],
                        help='clearing strategy to try (repeatable); "saved" keeps the saved one')
    args = parser.parse_args()
    settings = QSettings('GCodeProducer', 'GCodeProducer')
    library = LibrarySet().load()
    for strategy in args.strategy or ['saved']:
        report = run(args.model, settings, library, None if strategy == 'saved' else strategy)
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
