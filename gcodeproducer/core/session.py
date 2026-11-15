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
              mesh=None, model_path: Optional[str] = None, settings: Optional[dict] = None,
              placement=None, support_blocks=None, support=None) -> Job:
    workflow = wf.normalize(workflow)
    if machine.workflow != workflow:
        raise ValueError(f"machine '{machine.name}' is a {machine.workflow} machine, not {workflow}")
    return Job(workflow=workflow, machine=machine, material=material, nozzle=nozzle,
               tools=list(tools or []), mesh=mesh, model_path=model_path,
               settings=dict(settings or {}), placement=placement,
               support_blocks=list(support_blocks or []), support=support)


def place_mesh(job: Job) -> None:
    """Apply the job's placement to its mesh (default: centred on the bed for FDM,
    original XY for CAM; always dropped onto Z0)."""
    from .placement import Placement, bed_xy
    if job.mesh is None:
        return
    pl = job.placement or Placement()
    auto = bed_xy(job.machine, job.workflow) if job.workflow == wf.FDM else None
    job.mesh = pl.apply(job.mesh, auto_xy=auto)


def slice_job(job: Job, pipeline: Optional[SlicePipeline] = None,
              log: Optional[Callable[[str], None]] = None,
              progress: Optional[Callable[[float], None]] = None) -> PipelineResult:
    pipeline = pipeline or SlicePipeline.default(job.workflow)
    place_mesh(job)
    return pipeline.run(job, log=log, progress=progress)
