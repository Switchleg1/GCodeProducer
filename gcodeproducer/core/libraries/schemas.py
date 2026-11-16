"""Profiles and libraries.

GCodeProducer keeps four kinds of reusable *profile* and stores each kind in
its **own library** (a directory of JSON files), so they can be shared and
versioned independently:

======================  ========  ==================================================
kind                    workflow  holds
======================  ========  ==================================================
``machine``             fdm/cam   build volume, kinematics, **speeds / feeds**,
                                  start / end G-code and the list of consumables it
                                  *allows* (which nozzles / materials / tools are
                                  available on this machine)
``material``            fdm       filament: temperatures, flow, cooling, retraction
``nozzle``              fdm       hot-end orifice: diameter, max flow, line width
``tool``                cam       cutter: type, diameter, flutes, feeds & speeds
======================  ========  ==================================================

A **machine** picks which tools / materials / nozzles are available (via its
``allowed_*`` fields); the slice pipeline only offers the operator consumables
the selected machine allows.  Speeds and feeds live on the machine profile, so
a given machine runs every material / tool at its own rates.

Each kind has a declarative :class:`~gcodeproducer.core.params.Param` schema,
so the GUI form and CLI options are generated the same way module parameters
are in GCodeTools.
"""
from __future__ import annotations

from gcodeproducer.core.libraries.profile import Profile
from gcodeproducer.core.libraries.library import Library
from gcodeproducer.core.libraries.library_set import LibrarySet
from gcodeproducer.core.libraries.libraries_constants import (
    KINDS,
    KIND_WORKFLOW,
    KIND_LABEL,
    _machine_schema,
    PROFILE_SCHEMAS,
    _SLUG_RE,
)
from pathlib import Path
import gcodeproducer.core.workflows.validation as wf

# Profile kinds and which workflow(s) they belong to


# Schemas


def schema(kind: str, workflow: str = wf.FDM) -> list:
    """Return the :class:`Param` list for a profile ``kind``."""
    if kind == "machine":
        return _machine_schema(wf.normalize(workflow))
    try:
        return list(PROFILE_SCHEMAS[kind])
    except KeyError:
        raise ValueError(f"unknown profile kind '{kind}'") from None


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", str(name).strip().lower()).strip("-")
    return s or "profile"


def default_root() -> Path:
    import os
    env = os.environ.get("GCODEPRODUCER_LIBRARY")
    if env:
        return Path(env)
    return Path.home() / ".gcodeproducer"
