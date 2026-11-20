"""Read-only benchmark of the saved desktop CAM session (no G-code export)."""
from pathlib import Path
import argparse
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


def main():
    from gcodeproducer.core.cam import adaptive_paths

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--point-budget', type=int, default=adaptive_paths.ADAPTIVE_CAM_POINT_LIMIT,
                        help='override the adaptive point guard in this benchmark process only')
    args = parser.parse_args()
    if args.point_budget < 1:
        parser.error('--point-budget must be positive')
    adaptive_paths.ADAPTIVE_CAM_POINT_LIMIT = args.point_budget
    settings = QSettings('GCodeProducer', 'GCodeProducer')
    session = json.loads(settings.value('workSession/default'))
    if session['workflow'] != 'cam' or len(session['models']) != 1:
        raise ValueError('Benchmark expects the saved single-model CAM session')
    model, = session['models']
    library = LibrarySet().load()
    machine = library.machines.get(settings.value('machine/cam'))
    setup = CAMSetup.from_dict(session['cam']['setup'])
    job = build_job('cam', machine, mesh=load_mesh(model['path']), placement=Placement.from_dict(model['placement']),
                    tools=library.consumables_for(machine, 'tool'), cam_setup=setup,
                    preferences=preferences.load(library.root))
    print(f'Benchmark: {Path(model["path"]).name}; adaptive point budget {args.point_budget}', flush=True)
    start = time.perf_counter()
    slice_job(job, log=lambda m: print(m, flush=True) if 'Adaptive' in m or 'DEBUG ONLY' in m else None)
    runtime = time.perf_counter()-start
    incomplete = any(w.startswith('DEBUG ONLY') for w in job.warnings)
    unsafe = any('rapid motion contacts' in w.lower() or 'intersects a protected holding tab' in w.lower()
                 for w in job.warnings)
    report = dict(complete=not incomplete, safety_findings=unsafe, point_budget=args.point_budget,
                  seconds=round(runtime, 2),
                  preview_seconds=round(build_toolpath(job.program).stats['est_time_s'], 1),
                  layers=len(job.layers), lines=len(job.program.lines), warnings=job.warnings)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return int(incomplete or unsafe)


if __name__ == '__main__':
    raise SystemExit(main())
