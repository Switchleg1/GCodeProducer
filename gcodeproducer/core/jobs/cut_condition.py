"""CutCondition — jobs subsystem."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CutCondition:
    engagement: float                  # estimated radial engagement 0..1
    regime: str                        # air / hsm / cut / high / slot
    hand: str                          # climb / conventional / neutral / mixed / air (M3)
    feed_factor: float = 1.0            # multiplier of tool cutting feed
    conflict: bool = False              # segment cuts against the requested hand (highlighted, warned)
