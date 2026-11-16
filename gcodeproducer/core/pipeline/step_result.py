"""StepResult — pipeline subsystem."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class StepResult:
    stage: str
    summary: str
    seconds: float
    skipped: bool = False
