"""Heavy work that runs outside the GUI process.

The slicer is mostly Python, and Python threads share one interpreter lock
(the GIL): a slicing *thread* keeps taking the interpreter from the GUI thread and
the window stutters.  So the GUI runs this work in a separate **process**
(:mod:`gcodeproducer.gui.compute_service`).  This module is Qt-free: it holds the
task functions and the loop of that process.

Tasks
-----
``slice``   (job, pipeline) -> {"program", "steps", "toolpath", "filament_mm"}
``blocks``  kwargs for :func:`support.generate_blocks` -> [SupportBlock]
``ping``    anything -> the same (used by tests / warm-up)

Messages sent back on the result queue: ``(task_id, kind, payload)`` with kind
``log`` (str), ``progress`` (0..1, throttled), ``chunk`` (a slice of the program's lines),
``done`` (result) or ``error`` (traceback text).

A big program (hundreds of thousands of line objects) is sent as ``chunk``
messages before ``done``: unpickling it in one piece would hold the GUI
process's interpreter lock for about a second; in chunks the GUI keeps running
in between.
"""
from __future__ import annotations


import time, traceback


def run_slice(job, pipeline, log=None, progress=None) -> dict:
    """Slice and prepare everything the GUI shows, so the GUI only has to display it."""
    from gcodeproducer.core.jobs.session import slice_job
    from gcodeproducer.core.gcode.simulation import simulate
    from gcodeproducer.core.gcode.toolpath import build_toolpath

    res = slice_job(job, pipeline, log=log, progress=progress)
    prog = res.program
    out = {"program": prog, "steps": res.steps, "toolpath": None, "filament_mm": 0.0, "warnings": list(job.warnings),
           "material_results": job.material_results}
    from gcodeproducer.core.cam.tabs import resolve_tabs
    out["tab_bounds"] = resolve_tabs(job.mesh, job.cam_setup) if job.cam_setup is not None else []
    if prog is not None:
        s = simulate(prog)
        out["toolpath"] = build_toolpath(prog, sim=s)
        out["filament_mm"] = float(s.de[(s.de > 0) & s.moved].sum())
    return out


def run_blocks(kwargs: dict) -> list:
    from gcodeproducer.core.fdm.support import generate_blocks
    return generate_blocks(**kwargs)


def run_cam_pick(payload):
    from gcodeproducer.core.cam.planning import pick_geometry
    return pick_geometry(payload)


def run_placement_face(payload):
    """Return the hit triangle's world normal without doing mesh picking on the GUI thread."""
    from gcodeproducer.core.geometry.kernel import ray_triangles
    from gcodeproducer.core.jobs.placement import face_normals
    mesh, origin, direction = payload
    _, index = ray_triangles(origin, direction, mesh.vertices[mesh.triangles])
    if index < 0:
        return None
    normals, _ = face_normals(mesh.vertices, mesh.triangles[index:index + 1])
    return normals[0]


def run_tab_pick(payload):
    from gcodeproducer.core.cam.tabs import tab_pick
    return tab_pick(*payload)


def run_cam_highlight(payload):
    from gcodeproducer.core.cam.planning import highlight_geometry
    return highlight_geometry(payload)


def worker_main(task_q, out_q) -> None:
    """Loop of the compute process: run tasks until ``None`` arrives."""
    from gcodeproducer.core.runtime.runtime_constants import TASKS, CHUNK
    while True:
        task = task_q.get()
        if task is None:
            break
        tid, kind, payload = task
        last = [-1.0, 0.0]                     # last fraction sent, time sent

        def log(msg, tid=tid):
            out_q.put((tid, "log", str(msg)))

        def progress(f, tid=tid):
            now = time.monotonic()
            # at most ~20 updates per second and only when it moved by >= 1 %
            if f >= 1.0 or (f - last[0] >= 0.01 and now - last[1] >= 0.05):
                last[0], last[1] = f, now
                out_q.put((tid, "progress", float(f)))
        try:
            result = TASKS[kind](payload, log, progress)
        except Exception:
            out_q.put((tid, "error", traceback.format_exc()))
            continue
        prog = result.get("program") if isinstance(result, dict) else None
        if prog is not None and len(prog.lines) > CHUNK:
            lines, prog.lines = prog.lines, []
            for i in range(0, len(lines), CHUNK):
                out_q.put((tid, "chunk", lines[i:i + CHUNK]))
        out_q.put((tid, "done", result))


#: program lines per ``chunk`` message
