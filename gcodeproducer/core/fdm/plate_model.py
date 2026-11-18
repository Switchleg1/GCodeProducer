"""One independently placed FDM instance; copies can share source geometry."""
from dataclasses import dataclass, field

from gcodeproducer.core.fdm.model_support import ModelSupport
from gcodeproducer.core.jobs.placement import Placement


@dataclass(eq=False)
class PlateModel:
    path: str
    mesh: object
    placement: Placement
    blocks: list = field(default_factory=list)
    support: ModelSupport = field(default_factory=ModelSupport)
    persistent: bool = True   # cloned instances must not overwrite file defaults
