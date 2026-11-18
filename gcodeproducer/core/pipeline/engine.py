"""The slice pipeline: an ordered list of stages that turns a Job into G-code.

The pipeline drives geometry-to-G-code production for one *workflow*. A default
pipeline per workflow is provided; the operator can enable / disable / reorder
optional stages and tune their parameters.
"""
from __future__ import annotations

from gcodeproducer.core.pipeline.step import Step
from gcodeproducer.core.pipeline.step_result import StepResult
from gcodeproducer.core.pipeline.pipeline_result import PipelineResult
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.pipeline.pipeline_constants import DEFAULT_PIPELINES, DEFAULT_DISABLED
import gcodeproducer.core.plugins.discovery as plugins


#: default stage order for each workflow (ids must exist once stages are loaded)

#: optional stages that are part of the default pipeline but start switched off


def _optional(stage_id: str) -> bool:
    try:
        return plugins.stages.get(stage_id).optional
    except KeyError:
        return True


def parse_stage_spec(spec: str) -> Step:
    if ":" in spec:
        sid, rest = spec.split(":", 1)
    else:
        sid, rest = spec, ""
    params = {}
    for part in filter(None, (p.strip() for p in rest.split(","))):
        if "=" not in part:
            raise ValueError(f"bad parameter '{part}' in '{spec}' (expected key=value)")
        k, v = part.split("=", 1)
        params[k.strip()] = v.strip()
    return Step(sid.strip(), params)
