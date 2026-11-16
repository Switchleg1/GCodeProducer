"""PipelineResult — pipeline subsystem."""
from __future__ import annotations
from dataclasses import dataclass
from gcodeproducer.core.jobs.job import Job

@dataclass
class PipelineResult:
    job: Job
    steps: list

    @property
    def program(self):
        return self.job.program
