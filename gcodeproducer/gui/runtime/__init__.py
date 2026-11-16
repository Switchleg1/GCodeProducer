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

from gcodeproducer.gui.runtime.result_reader import _Reader
from gcodeproducer.gui.runtime.compute_service import ComputeService
