"""Shared runtime constants and declarative tables."""
from __future__ import annotations
from gcodeproducer.core.runtime.compute import (
    run_slice,
    run_blocks,
    run_cam_highlight,
    run_cam_pick,
    run_tab_pick,
)

TASKS = {
    "cam_pick": lambda payload, log, progress: run_cam_pick(payload),
    "cam_tab_pick": lambda payload, log, progress: run_tab_pick(payload),
    "cam_highlight": lambda payload, log, progress: run_cam_highlight(payload),
    "slice": lambda payload, log, progress: run_slice(*payload, log=log, progress=progress),
    "blocks": lambda payload, log, progress: run_blocks(payload),
    "ping": lambda payload, log, progress: payload,
}

CHUNK = 5000
