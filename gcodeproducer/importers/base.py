"""Geometry importer API.

An importer loads a source file (STL, OBJ, ...) into a geometry object stored
on the :class:`~gcodeproducer.core.job.Job` (``job.mesh``) for the slice
stages to consume.
"""
from __future__ import annotations

from ..core import workflow as wf


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
