"""Process (workflow options) editor.

The process is stored as a stage pipeline, but the operator sees it as a set of
*settings sections* - Layers, Skirt / brim, Walls, Top / bottom, Infill,
Travel & output - one per stage, in an accordion.  Optional sections have an
*Enabled* switch.  Adding / removing / reordering stages is an advanced
operation done in :class:`PipelineDialog`.

Only process settings live here.  Machine speeds, material temperatures /
retraction and nozzle sizes come from their own libraries.
"""
from __future__ import annotations

from gcodeproducer.gui.editors.section import Section
from gcodeproducer.gui.editors.process_editor import ProcessEditor
from gcodeproducer.gui.editors.pipeline_dialog import PipelineDialog
import gcodeproducer.core.plugins.discovery as plugins
from gcodeproducer.core.pipeline.step import Step
from .editors_constants import STAGE_SUMMARY_TEMPLATES


def _stage(sid):
    try:
        return plugins.stages.get(sid)
    except KeyError:
        return None


def summary(step: Step) -> str:
    """Short one-line summary of a step's settings for a collapsed section header."""
    cls = _stage(step.stage)
    if cls is None:
        return ""
    if not step.enabled:
        return "off"
    try:
        p = cls.resolve(step.params)
    except Exception:
        return ""
    g = p.get
    sid = step.stage
    if sid == "fdm_slice":
        first = g("first_layer_height")
        return f"{g('layer_height'):g} mm" + ("" if first == "auto" else f", first {first:g} mm")
    if sid in STAGE_SUMMARY_TEMPLATES:
        return STAGE_SUMMARY_TEMPLATES[sid].format_map(p)
    if sid == "fdm_skirt_brim":
        t = g("type")
        if t == "none":
            return "none"
        parts = []
        if t in ("skirt", "both"):
            parts.append(f"skirt {g('skirt_loops')}× @ {g('skirt_distance'):g} mm")
        if t in ("brim", "both"):
            parts.append(f"brim {g('brim_width'):g} mm")
        return ", ".join(parts)
    if sid == "cam_profile":
        return f"{g('side')}" + ("" if g("stepdown") == "auto" else f", {g('stepdown'):g} mm/pass")
    return ""
