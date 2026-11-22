"""Run independent per-layer geometry work on threads.

Shapely releases the GIL inside GEOS, so buffering and Boolean operations on
different layers overlap well on threads. The compute process is a daemon and
cannot start worker processes, so threads are the available parallelism.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from gcodeproducer.core.fdm import fdm_constants


def layer_map(fn, items):
    """``map(fn, items)`` in order, computed on a small thread pool; yields results as they are ready."""
    items = list(items)
    workers = max(1, min(fdm_constants.LAYER_THREADS, os.cpu_count() or 1, len(items)))
    if workers == 1:
        yield from map(fn, items)
        return
    pool = ThreadPoolExecutor(workers, thread_name_prefix="fdm-layer")
    try:
        yield from pool.map(fn, items)
    finally:
        # a cancelled slice (exception in the consumer) must not wait for queued layers
        pool.shutdown(wait=True, cancel_futures=True)
