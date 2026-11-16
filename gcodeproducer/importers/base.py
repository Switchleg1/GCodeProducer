"""Geometry importer API.

An importer loads a source file (STL, OBJ, ...) into a geometry object stored
on the :class:`~gcodeproducer.core.job.Job` (``job.mesh``) for the slice
stages to consume.
"""
from __future__ import annotations

from gcodeproducer.importers.importer import Importer
