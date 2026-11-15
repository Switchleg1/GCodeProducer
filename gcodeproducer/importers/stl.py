"""STL mesh importer (binary and ASCII)."""
from __future__ import annotations

from ..core import geometry
from ..core.workflow import CAM, FDM
from .base import Importer


class STLImporter(Importer):
    id = "stl"
    name = "STL mesh"
    extensions = (".stl",)
    workflows = (FDM, CAM)

    def load(self, path: str):
        return geometry.load_stl(path)
