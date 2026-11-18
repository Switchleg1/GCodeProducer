"""High-level driver that ties libraries, importer, job and pipeline together."""
from __future__ import annotations


from typing import Callable, Optional
import gcodeproducer.core.plugins.discovery as plugins, gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.jobs.job import Job
from gcodeproducer.core.pipeline.pipeline_result import PipelineResult
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.libraries.profile import Profile


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
              placement=None, support_blocks=None, support=None, cam_setup=None,
              preferences: Optional[dict] = None, plate_models=None) -> Job:
    workflow = wf.normalize(workflow)
    if machine.workflow != workflow:
        raise ValueError(f"machine '{machine.name}' is a {machine.workflow} machine, not {workflow}")
    return Job(workflow=workflow, machine=machine, material=material, nozzle=nozzle,
               tools=list(tools or []), mesh=mesh, model_path=model_path,
               settings=dict(settings or {}), placement=placement,
               support_blocks=list(support_blocks or []), support=support, cam_setup=cam_setup,
               preferences=dict(preferences or {}), plate_models=list(plate_models or []))


def place_mesh(job: Job) -> None:
    """Apply the job's placement to its mesh (default: centred on the bed for FDM,
    original XY for CAM; FDM bottom at Z0, CAM top at Z0)."""
    from gcodeproducer.core.jobs.placement import Placement
    from gcodeproducer.core.jobs.placement import bed_xy
    if job.plate_models:
        from gcodeproducer.core.fdm.plate import combine_meshes
        auto = bed_xy(job.machine, job.workflow)
        job.placed_models = [model.placement.apply(model.mesh, auto_xy=auto) for model in job.plate_models]
        job.mesh = combine_meshes(job.placed_models)
        if job.workflow == wf.FDM and len(job.plate_models) == 1:
            job.support = job.plate_models[0].support
            job.support_blocks = job.plate_models[0].blocks
        return
    if job.mesh is None:
        return
    pl = job.placement or Placement(z_anchor="top" if job.workflow == wf.CAM else "bottom")
    auto = bed_xy(job.machine, job.workflow) if job.workflow == wf.FDM else None
    job.mesh = pl.apply(job.mesh, auto_xy=auto)


def slice_job(job: Job, pipeline: Optional[SlicePipeline] = None,
              log: Optional[Callable[[str], None]] = None,
              progress: Optional[Callable[[float], None]] = None) -> PipelineResult:
    pipeline = pipeline or SlicePipeline.default(job.workflow)
    if job.cam_setup is not None and job.cam_setup.fingerprint:
        from gcodeproducer.core.cam.planning import fingerprint
        from gcodeproducer.core.cam.assembly import assembly_fingerprint
        current = (assembly_fingerprint(job.plate_models) if job.plate_models
                   else fingerprint(job.mesh) if job.mesh is not None else '')
        if current != job.cam_setup.fingerprint:
            raise ValueError("CAM model geometry changed; reselect operation geometry")
    place_mesh(job)
    return pipeline.run(job, log=log, progress=progress)
