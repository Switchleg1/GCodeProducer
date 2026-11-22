"""Run independent per-layer work in parallel: worker processes, or threads as a fallback.

Most of the slicer is Python, and Python threads share one interpreter lock,
so threads only overlap the parts spent inside GEOS (about 1.6x on walls).
Worker *processes* each have their own interpreter and scale with the cores.

A process pool is used when the work function can be pickled (a module-level
function or a :func:`functools.partial` of one) and the calling process may
start children; otherwise - closures, a daemon process, ``GCODEPRODUCER_WORKERS``
set to 0 or 1, or a broken pool - the same work runs on threads. The pool is
created once per process and reused. Each worker watches its parent and exits
when the parent goes away (a cancelled slice terminates the compute process),
so no orphans are left behind.
"""
from __future__ import annotations

import atexit
import os
import pickle
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from gcodeproducer.core.fdm import fdm_constants

_pool = None
_pool_lock = threading.Lock()


def watch_parent():
    """Worker initializer: exit as soon as the parent process ends."""
    import multiprocessing as mp
    parent = mp.parent_process()
    if parent is None:
        return

    def wait_and_exit():
        from multiprocessing.connection import wait
        wait([parent.sentinel])
        os._exit(0)

    threading.Thread(target=wait_and_exit, name="parent-watch", daemon=True).start()


def worker_count() -> int:
    """Worker processes to use (``GCODEPRODUCER_WORKERS`` overrides; 0 / 1 = threads only)."""
    env = os.environ.get(fdm_constants.LAYER_WORKERS_ENV)
    if env is not None:
        try:
            return max(0, int(env))
        except ValueError:
            pass
    return max(1, min(fdm_constants.LAYER_PROCESSES, (os.cpu_count() or 1) - 1))


def process_pool():
    """The shared worker pool, or None when processes can't or shouldn't be used."""
    global _pool
    import multiprocessing as mp
    if mp.current_process().daemon or worker_count() < 2:
        return None
    with _pool_lock:
        if _pool is None:
            ctx = mp.get_context("spawn")
            _pool = ProcessPoolExecutor(worker_count(), mp_context=ctx, initializer=watch_parent)
            atexit.register(shutdown_pool)
        return _pool


def shutdown_pool():
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def _picklable(fn) -> bool:
    try:
        pickle.dumps(fn)
        return True
    except Exception:
        return False


def layer_map(fn, items):
    """``map(fn, items)`` in order, computed in parallel; yields results as they are ready."""
    items = list(items)
    if len(items) >= fdm_constants.LAYER_PROCESS_MIN and _picklable(fn):
        pool = process_pool()
        if pool is not None:
            yield from _process_map(pool, fn, items)
            return
    yield from _thread_map(fn, items)


def _process_map(pool, fn, items):
    try:
        futures = [pool.submit(fn, item) for item in items]
    except (BrokenProcessPool, RuntimeError):
        shutdown_pool()
        yield from _thread_map(fn, items)
        return
    try:
        for i, future in enumerate(futures):
            try:
                result = future.result()
            except BrokenProcessPool:
                # a worker died (out of memory, killed): finish on threads, start a new pool next time
                shutdown_pool()
                yield from _thread_map(fn, items[i:])
                return
            yield result
    finally:
        for future in futures:                   # a cancelled slice must not leave queued work
            future.cancel()


def _thread_map(fn, items):
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
