"""Slice stage API.

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

from gcodeproducer.stages.base.stage_context import StageContext
from gcodeproducer.stages.base.slice_stage import SliceStage
from gcodeproducer.core.jobs.job import Job
from gcodeproducer.core.parameters.parameters_constants import AUTO
from gcodeproducer.core.parameters.param import Param
from gcodeproducer.core.workflows.workflows_constants import ALL, CAM, FDM
from gcodeproducer.core.workflows.incompatible_workflow_error import IncompatibleWorkflowError

__all__ = ["SliceStage", "StageContext", "Param", "AUTO", "Job",
           "FDM", "CAM", "ALL", "IncompatibleWorkflowError"]
