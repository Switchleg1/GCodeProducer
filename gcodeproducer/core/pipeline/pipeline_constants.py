"""Shared pipeline constants and declarative tables."""
from __future__ import annotations
import gcodeproducer.core.workflows.validation as wf

DEFAULT_PIPELINES = {
    wf.FDM: ["fdm_slice", "fdm_skirt_brim", "fdm_support", "fdm_perimeters", "fdm_top_bottom",
             "fdm_infill", "fdm_emit"],
    wf.CAM: ["cam_profile", "cam_emit"],
}

DEFAULT_DISABLED: set = set()
