"""Step — pipeline subsystem."""
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class Step:
    stage: str
    params: dict = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"stage": self.stage, "enabled": self.enabled, "params": dict(self.params)}
