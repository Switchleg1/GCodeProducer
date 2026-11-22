"""ComputeService — runtime subsystem."""
from __future__ import annotations
import atexit, gc, itertools, multiprocessing as mp
from PyQt6.QtCore import QObject, pyqtSignal
from gcodeproducer.gui.runtime.result_reader import _Reader
from .runtime_constants import MESSAGE_HANDLERS

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
        self._atexit = False

    # ------------------------------------------------------------ process
    def _ensure(self):
        if self._proc is not None and self._proc.is_alive():
            return
        from gcodeproducer.core.runtime.compute import worker_main
        self._task_q = self._ctx.Queue()
        self._out_q = self._ctx.Queue()
        # Not a daemon: the compute process starts its own pool of slicing workers, which daemon
        # processes may not do. It exits by itself when this process goes away (parent watch in
        # worker_main), and shutdown()/cancel() still terminate it.
        self._proc = self._ctx.Process(target=worker_main, args=(self._task_q, self._out_q),
                                       name="gcodeproducer-compute", daemon=False)
        self._proc.start()
        if not self._atexit:
            atexit.register(self._stop_process, False)
            self._atexit = True
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
        handler = MESSAGE_HANDLERS.get(kind)
        if handler is not None:
            getattr(self, handler)(tid, payload)

    def _receive_log(self, tid, payload):
        self.log.emit(tid, payload)

    def _receive_progress(self, tid, payload):
        self.progressed.emit(tid, payload)

    def _receive_chunk(self, tid, payload):
        if tid not in self._chunks:
            # No automatic full collections while ~1M acyclic objects arrive.
            gc.disable()
        self._chunks.setdefault(tid, []).extend(payload)

    def _receive_done(self, tid, payload):
        self.running.discard(tid)
        lines = self._chunks.pop(tid, None)
        if lines is not None and isinstance(payload, dict) and payload.get("program") is not None:
            payload["program"].lines = lines
        if lines is not None:
            self._settle_gc()
        self.done.emit(tid, payload)

    def _receive_error(self, tid, payload):
        self.running.discard(tid)
        if self._chunks.pop(tid, None) is not None:
            self._settle_gc()
        self.failed.emit(tid, payload)
