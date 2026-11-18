"""The slice job: the mutable object that flows through the stage pipeline.

The pipeline passes a :class:`Job` between stages, which add layers, toolpaths
and finally the emitted :class:`GCodeProgram`.
"""
from __future__ import annotations

from gcodeproducer.core.jobs.cut_condition import CutCondition
from gcodeproducer.core.jobs.path import Path
from gcodeproducer.core.jobs.layer import Layer
from gcodeproducer.core.jobs.job import Job
