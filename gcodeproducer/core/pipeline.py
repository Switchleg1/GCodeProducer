"""The slice pipeline: an ordered list of stages that turns a Job into G-code.

Mirrors GCodeTools' ``Pipeline`` but, instead of transforming a loaded
program, it drives geometry -> G-code production for one *workflow*.  A default
pipeline per workflow is provided; the operator can enable / disable / reorder
optional stages and tune their parameters.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import plugins
from . import workflow as wf
from .job import Job


@dataclass
class Step:
    stage: str
    params: dict = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {"stage": self.stage, "enabled": self.enabled, "params": dict(self.params)}


@dataclass
class StepResult:
    stage: str
    summary: str
    seconds: float
    skipped: bool = False


@dataclass
class PipelineResult:
    job: Job
    steps: list

    @property
    def program(self):
        return self.job.program


#: default stage order for each workflow (ids must exist once stages are loaded)
DEFAULT_PIPELINES = {
    wf.FDM: ["fdm_slice", "fdm_perimeters", "fdm_top_bottom", "fdm_infill", "fdm_emit"],
    wf.CAM: ["cam_profile", "cam_emit"],
}


class SlicePipeline:
    def __init__(self, workflow: str, steps: Optional[list] = None):
        self.workflow = wf.normalize(workflow)
        self.steps: list[Step] = steps if steps is not None else []

    @classmethod
    def default(cls, workflow: str) -> "SlicePipeline":
        workflow = wf.normalize(workflow)
        steps = [Step(sid) for sid in DEFAULT_PIPELINES.get(workflow, [])]
        return cls(workflow, steps)

    # ------------------------------------------------------------- persist
    def to_dict(self) -> dict:
        return {"workflow": self.workflow, "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, d: dict) -> "SlicePipeline":
        steps = [Step(s["stage"], dict(s.get("params", {})), bool(s.get("enabled", True)))
                 for s in d.get("steps", [])]
        return cls(d.get("workflow", wf.FDM), steps)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "SlicePipeline":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def validate(self) -> None:
        for s in self.steps:
            plugins.stages.get(s.stage).resolve(s.params)

    # ----------------------------------------------------------------- run
    def run(self, job: Job, log: Optional[Callable[[str], None]] = None,
            progress: Optional[Callable[[float], None]] = None) -> PipelineResult:
        from ..stages.base import StageContext
        results = []
        active = [s for s in self.steps if s.enabled]
        for k, step in enumerate(active):
            cls = plugins.stages.get(step.stage)
            params = cls.resolve(step.params)
            if not cls.applies_to(job.workflow):
                msg = f"{cls.name}: skipped - {cls.target_tag()} stage, job is {wf.short(job.workflow)}"
                if log:
                    log(msg)
                results.append(StepResult(step.stage, msg, 0.0, True))
                continue

            def prog_cb(f, k=k):
                if progress:
                    progress((k + f) / max(1, len(active)))

            ctx = StageContext(log, prog_cb)
            t0 = time.perf_counter()
            summary = cls().execute(job, params, ctx) or "done"
            dt = time.perf_counter() - t0
            if log:
                log(f"{cls.name}: {summary} ({dt:.2f}s)")
            results.append(StepResult(step.stage, summary, dt))
        if progress:
            progress(1.0)
        return PipelineResult(job, results)


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
