"""_Reader — runtime subsystem."""
from __future__ import annotations
import queue
from PyQt6.QtCore import QThread, pyqtSignal

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
