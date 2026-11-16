"""STLImporter — importers subsystem."""
from __future__ import annotations
import gcodeproducer.core.geometry.kernel as geometry
from gcodeproducer.core.workflows.workflows_constants import CAM, FDM
from gcodeproducer.importers.importer import Importer

class STLImporter(Importer):
    id = "stl"
    name = "STL mesh"
    extensions = (".stl",)
    workflows = (FDM, CAM)

    def load(self, path: str):
        return geometry.load_stl(path)
