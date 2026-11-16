"""Process presets: saveable / loadable *workflow options*.

A process preset bundles a whole slice pipeline (which stages run, in what order,
with which parameters) for one workflow, so a user can keep e.g. "0.20 mm
Standard", "0.30 mm Draft" or "Vase" and switch between them.  Presets live in
their own library (``<root>/processes/*.json``), independent of machine /
material / nozzle / tool profiles.
"""
from __future__ import annotations

from gcodeproducer.core.libraries.process_preset import ProcessPreset
from gcodeproducer.core.libraries.process_library import ProcessLibrary
from gcodeproducer.core.libraries.libraries_constants import _SLUG_RE


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", str(name).strip().lower()).strip("-")
    return s or "process"
