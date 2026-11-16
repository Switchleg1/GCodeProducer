"""ProcessPreset — libraries subsystem."""
from __future__ import annotations
import json, gcodeproducer.core.workflows.validation as wf
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline

@dataclass
class ProcessPreset:
    name: str
    workflow: str
    pipeline: dict = field(default_factory=dict)      # SlicePipeline.to_dict()
    id: str = ""
    path: Optional[str] = None

    def __post_init__(self):
        from gcodeproducer.core.libraries.processes import slugify
        self.workflow = wf.normalize(self.workflow)
        if not self.id:
            self.id = slugify(self.name)
        if not self.pipeline:
            self.pipeline = SlicePipeline.default(self.workflow).to_dict()

    def slice_pipeline(self) -> SlicePipeline:
        return SlicePipeline.from_dict(self.pipeline).ensure_defaults()

    @classmethod
    def import_file(cls, path: str) -> "ProcessPreset":
        """Load a preset from any file (also accepts a bare pipeline JSON)."""
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if "pipeline" not in d and "steps" in d:          # bare SlicePipeline file
            d = {"name": Path(path).stem, "workflow": d.get("workflow", wf.FDM), "pipeline": d}
        p = cls.from_dict(d)
        p.path = None
        return p

    def export_file(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    def set_pipeline(self, pipeline: SlicePipeline) -> None:
        self.pipeline = pipeline.to_dict()

    # ----------------------------------------------------------- persist
    def to_dict(self) -> dict:
        return {"name": self.name, "id": self.id, "workflow": self.workflow, "pipeline": self.pipeline}

    @classmethod
    def from_dict(cls, d: dict, path: Optional[str] = None) -> "ProcessPreset":
        return cls(name=d.get("name", d.get("id", "")), workflow=d.get("workflow", wf.FDM),
                   pipeline=dict(d.get("pipeline", {})), id=d.get("id", ""), path=path)

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        self.path = path

    @classmethod
    def load(cls, path: str) -> "ProcessPreset":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh), str(path))
