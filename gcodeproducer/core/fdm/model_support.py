"""ModelSupport — fdm subsystem."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from gcodeproducer.core.fdm.fdm_constants import SUPPORT_MODES

@dataclass
class ModelSupport:
    """Where the *model* needs support - set in Model > Support, saved with the model.

    This belongs to the model (like its placement and support blocks), not to
    the process: switching process never changes it.  The process only decides
    how support is printed (density, pattern, gaps, interfaces...).
    """
    mode: str = "none"               # none | buildplate | everywhere | blocks
    overhang_angle: float = 50.0     # deg from vertical that needs support
    extend: float = 1.0              # mm the support reaches past the model's edges
    fill_holes: float = 0.0          # mm2: holes up to this area are supported across (0 = off)

    def __post_init__(self):
        if self.mode not in SUPPORT_MODES:
            raise ValueError(f"support mode '{self.mode}' not in {SUPPORT_MODES}")
        self.overhang_angle = float(self.overhang_angle)
        self.extend = max(0.0, float(self.extend))
        self.fill_holes = max(0.0, float(self.fill_holes))

    @property
    def enabled(self) -> bool:
        return self.mode != "none"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelSupport":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in (d or {}).items() if k in keys})
