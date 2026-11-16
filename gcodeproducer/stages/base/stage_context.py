"""StageContext — base subsystem."""
from __future__ import annotations
from typing import Callable, Optional

class StageContext:
    def __init__(self, log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[float], None]] = None):
        self._log = log
        self._progress = progress
        self.cancelled = False
        self.messages: list = []

    def log(self, msg: str) -> None:
        self.messages.append(msg)
        if self._log:
            self._log(msg)

    def progress(self, fraction: float) -> None:
        if self._progress:
            self._progress(max(0.0, min(1.0, fraction)))
