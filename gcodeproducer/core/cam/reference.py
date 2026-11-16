"""Reference — cam subsystem."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Reference:
    kind: str
    indices: list
