"""Runs slicing and other heavy work in a separate process.

* one long-lived compute process (``multiprocessing``, *spawn*) is started on
  the first request and reused - no start-up cost per slice;
* a reader ``QThread`` blocks on the result queue and re-emits messages as Qt
  signals, so the GUI thread never waits or polls;
* :meth:`cancel` terminates the process (a new one starts with the next task).

Because the work happens in another process it never competes with the GUI for
Python's interpreter lock, which is what made the window stutter when slicing
ran in a thread.
"""
from __future__ import annotations

import gc
import itertools
import multiprocessing as mp
import queue

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class _Reader(QThread):
    message = pyqtSignal(object)                # (task_id, kind, payload)

    def __init__(self, out_q, parent=None):
        super().__init__(parent)
        self.out_q = out_q
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        while not self._stop:
            try:
                msg = self.out_q.get(timeout=0.1)
            except queue.Empty:
                continue
            except (EOFError, OSError):       # queue closed (process terminated)
                break
            self.message.emit(msg)


class ComputeService(QObject):
    log = pyqtSignal(int, str)
    progressed = pyqtSignal(int, float)
    done = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._task_q = self._out_q = None
        self._reader = None
        self._ids = itertools.count(1)
        self.running: set = set()             # task ids submitted and not finished
        self._chunks: dict = {}               # task id -> program lines received so far

    # ------------------------------------------------------------ process
    def _ensure(self):
        if self._proc is not None and self._proc.is_alive():
            return
        from ..core.compute import worker_main
        self._task_q = self._ctx.Queue()
        self._out_q = self._ctx.Queue()
        self._proc = self._ctx.Process(target=worker_main, args=(self._task_q, self._out_q),
                                       name="gcodeproducer-compute", daemon=True)
        self._proc.start()
        self._reader = _Reader(self._out_q, self)
        self._reader.message.connect(self._dispatch)
        self._reader.start()

    def _stop_process(self, wait: bool = True):
        if self._reader is not None:
            self._reader.stop()
            if wait:
                self._reader.wait(2000)
            self._reader = None
        if self._proc is not None:
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(2)
            self._proc = None
        for q in (self._task_q, self._out_q):
            if q is not None:
                q.cancel_join_thread()
                q.close()
        self._task_q = self._out_q = None

    # ---------------------------------------------------------------- API
    @property
    def busy(self) -> bool:
        return bool(self.running)

    def submit(self, kind: str, payload) -> int:
        self._ensure()
        tid = next(self._ids)
        self.running.add(tid)
        self._task_q.put((tid, kind, payload))
        return tid

    def cancel(self) -> None:
        """Stop everything that is running (the process is restarted on demand)."""
        self._stop_process()
        self.running.clear()
        if self._chunks:
            self._chunks.clear()
            self._settle_gc()

    @staticmethod
    def _settle_gc():
        """Move the received objects out of the collector's reach and re-enable it.

        Program lines hold no reference cycles, so frozen ones are still freed by
        reference counting when they are replaced."""
        gc.freeze()
        gc.enable()

    def shutdown(self) -> None:
        if self._task_q is not None and self._proc is not None and self._proc.is_alive():
            try:
                self._task_q.put(None)
                self._proc.join(1)
            except Exception:
                pass
        self._stop_process()
        self.running.clear()

    # ----------------------------------------------------------- messages
    def _dispatch(self, msg):
        tid, kind, payload = msg
        if tid not in self.running:            # cancelled task: ignore late messages
            return
        if kind == "log":
            self.log.emit(tid, payload)
        elif kind == "progress":
            self.progressed.emit(tid, payload)
        elif kind == "chunk":                  # a big program arrives in pieces
            if tid not in self._chunks:
                # no automatic full collections while ~1M acyclic objects arrive
                gc.disable()
            self._chunks.setdefault(tid, []).extend(payload)
        elif kind == "done":
            self.running.discard(tid)
            lines = self._chunks.pop(tid, None)
            if lines is not None and isinstance(payload, dict) and payload.get("program") is not None:
                payload["program"].lines = lines
            if lines is not None:
                self._settle_gc()
            self.done.emit(tid, payload)
        elif kind == "error":
            self.running.discard(tid)
            if self._chunks.pop(tid, None) is not None:
                self._settle_gc()
            self.failed.emit(tid, payload)
