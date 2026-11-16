"""SliceStage — base subsystem."""
from __future__ import annotations
from typing import Optional
import gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.jobs.job import Job
from gcodeproducer.core.parameters.resolution import resolve_params
from gcodeproducer.core.workflows.incompatible_workflow_error import IncompatibleWorkflowError
from gcodeproducer.stages.base.stage_context import StageContext

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
    def resolve(cls, values: Optional[dict], strict: bool = False) -> dict:
        """Fill defaults / coerce.  Unknown keys (e.g. settings removed from a stage but
        still present in an older saved process) are ignored unless ``strict``."""
        values = dict(values or {})
        if not strict:
            known = {p.name for p in cls.parameters()}
            values = {k: v for k, v in values.items() if k in known}
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
