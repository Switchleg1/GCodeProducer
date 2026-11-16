"""IncompatibleWorkflowError — workflows subsystem."""
from __future__ import annotations

class IncompatibleWorkflowError(RuntimeError):
    """Raised when a stage is executed in a workflow it does not support."""
