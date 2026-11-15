"""Slice stage API (the GCodeProducer analogue of GCodeTools' modules).

A stage is a class deriving from :class:`SliceStage`::

    from gcodeproducer.stages.base import SliceStage, Param, FDM

    class MyStage(SliceStage):
        id = "my_stage"
        name = "My stage"
        description = "What it adds to the job"
        workflows = (FDM,)           # REQUIRED: which workflow(s) it belongs to
        params = [Param("amount", "float", 1.0, unit="mm")]

        def run(self, job, params, ctx):
            ...                       # read job.mesh / job.layers, append paths
            return "summary text"

Stages run in order and mutate the shared :class:`~gcodeproducer.core.job.Job`.
A pipeline for a given workflow only ever runs stages that declare it, so FDM
stages (perimeters, infill, temperature) never run in a CAM job and vice versa.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..core import workflow as wf
from ..core.job import Job
from ..core.params import AUTO, Param, resolve_params
from ..core.workflow import ALL, CAM, FDM, IncompatibleWorkflowError

__all__ = ["SliceStage", "StageContext", "Param", "AUTO", "Job",
           "FDM", "CAM", "ALL", "IncompatibleWorkflowError"]


class StageContext:
    def __init__(self, log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[float], None]] = None):
        self._log = log
        self._progress = progress
        self.cancelled = False
        self.messages: list = []

    def log(self, msg: str) -> None:
        self.messages.append(msg)
        if self._log:
            self._log(msg)

    def progress(self, fraction: float) -> None:
        if self._progress:
            self._progress(max(0.0, min(1.0, fraction)))


class SliceStage:
    id: str = ""
    name: str = ""
    description: str = ""
    category: str = "General"
    version: str = "1.0"
    #: REQUIRED workflow(s) this stage belongs to: (FDM,), (CAM,) or (FDM, CAM)
    workflows: tuple = ()
    #: whether the operator may disable this stage (core stages like slice/emit cannot)
    optional: bool = True
    params: list = []

    @classmethod
    def parameters(cls) -> list:
        return list(cls.params)

    @classmethod
    def defaults(cls) -> dict:
        return {p.name: p.default for p in cls.parameters()}

    @classmethod
    def resolve(cls, values: Optional[dict]) -> dict:
        return resolve_params(cls.parameters(), values)

    @classmethod
    def workflow_set(cls) -> tuple:
        return wf.normalize_all(cls.workflows)

    @classmethod
    def applies_to(cls, workflow: str) -> bool:
        return wf.normalize(workflow) in cls.workflow_set()

    @classmethod
    def target_tag(cls) -> str:
        return wf.tag(cls.workflow_set())

    def execute(self, job: Job, params: dict, ctx: StageContext) -> Optional[str]:
        if not self.applies_to(job.workflow):
            raise IncompatibleWorkflowError(
                f"{self.name} ({self.target_tag()}) can not run in a "
                f"{wf.label(job.workflow)} job")
        return self.run(job, params, ctx)

    def run(self, job: Job, params: dict, ctx: StageContext) -> Optional[str]:
        raise NotImplementedError

    @classmethod
    def help_text(cls) -> str:
        lines = [f"{cls.id} - {cls.name}", "", cls.description, "",
                 f"Workflows: {cls.target_tag()}", "", "Parameters:"]
        for p in cls.parameters():
            lines.append("  " + p.describe())
        return "\n".join(lines)
