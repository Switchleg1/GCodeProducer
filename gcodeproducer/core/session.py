"""High-level driver that ties libraries, importer, job and pipeline together."""
from __future__ import annotations

from typing import Callable, Optional

from . import plugins
from . import workflow as wf
from .job import Job
from .pipeline import PipelineResult, SlicePipeline
from .profiles import LibrarySet, Profile


def find_importer(path: str):
    for cls in plugins.importers.all():
        if cls.handles(path):
            return cls
    raise ValueError(f"no importer for '{path}'")


def load_mesh(path: str):
    return find_importer(path)().load(path)


def build_job(workflow: str, machine: Profile, *, material: Optional[Profile] = None,
              nozzle: Optional[Profile] = None, tools: Optional[list] = None,
              mesh=None, model_path: Optional[str] = None, settings: Optional[dict] = None) -> Job:
    workflow = wf.normalize(workflow)
    if machine.workflow != workflow:
        raise ValueError(f"machine '{machine.name}' is a {machine.workflow} machine, not {workflow}")
    return Job(workflow=workflow, machine=machine, material=material, nozzle=nozzle,
               tools=list(tools or []), mesh=mesh, model_path=model_path,
               settings=dict(settings or {}))


def slice_job(job: Job, pipeline: Optional[SlicePipeline] = None,
              log: Optional[Callable[[str], None]] = None,
              progress: Optional[Callable[[float], None]] = None) -> PipelineResult:
    pipeline = pipeline or SlicePipeline.default(job.workflow)
    return pipeline.run(job, log=log, progress=progress)
