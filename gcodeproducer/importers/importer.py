"""Importer — importers subsystem."""
from __future__ import annotations
import gcodeproducer.core.workflows.validation as wf

class Importer:
    id: str = ""
    name: str = ""
    extensions: tuple = ()               # e.g. (".stl",)
    workflows: tuple = (wf.FDM, wf.CAM)

    @classmethod
    def handles(cls, path: str) -> bool:
        p = str(path).lower()
        return any(p.endswith(e) for e in cls.extensions)

    def load(self, path: str):
        raise NotImplementedError
