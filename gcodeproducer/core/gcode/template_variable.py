"""Var — gcode subsystem."""
from __future__ import annotations
from dataclasses import dataclass
from gcodeproducer.core.workflows.workflows_constants import FDM, CAM

@dataclass(frozen=True)
class Var:
    name: str
    category: str
    description: str
    example: object
    workflows: tuple = (FDM, CAM)
