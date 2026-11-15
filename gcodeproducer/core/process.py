"""Process presets: saveable / loadable *workflow options*.

A process preset bundles a whole slice pipeline (which stages run, in what order,
with which parameters) for one workflow, so a user can keep e.g. "0.20 mm
Standard", "0.30 mm Draft" or "Vase" and switch between them.  Presets live in
their own library (``<root>/processes/*.json``), independent of machine /
material / nozzle / tool profiles.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import workflow as wf
from .pipeline import SlicePipeline

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", str(name).strip().lower()).strip("-")
    return s or "process"


@dataclass
class ProcessPreset:
    name: str
    workflow: str
    pipeline: dict = field(default_factory=dict)      # SlicePipeline.to_dict()
    id: str = ""
    path: Optional[str] = None

    def __post_init__(self):
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


class ProcessLibrary:
    """A collection of :class:`ProcessPreset`, backed by a directory."""

    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else None
        self._items: dict[str, ProcessPreset] = {}

    def add(self, preset: ProcessPreset) -> ProcessPreset:
        self._items[preset.id] = preset
        return preset

    def remove(self, preset_id: str) -> None:
        p = self._items.pop(preset_id, None)
        if p and self.directory:
            f = Path(self.directory) / f"{preset_id}.json"
            if f.exists():
                f.unlink()

    def get(self, preset_id: str) -> ProcessPreset:
        return self._items[preset_id]

    def all(self, workflow: Optional[str] = None) -> list:
        out = list(self._items.values())
        if workflow:
            out = [p for p in out if p.workflow == wf.normalize(workflow)]
        return out

    def ids(self) -> list:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def load_dir(self, directory: Optional[Path] = None) -> int:
        d = Path(directory) if directory else self.directory
        if not d or not d.is_dir():
            return 0
        self.directory = d
        n = 0
        for f in sorted(d.glob("*.json")):
            try:
                self.add(ProcessPreset.load(str(f)))
                n += 1
            except Exception:
                pass
        return n

    def save_all(self, directory: Optional[Path] = None) -> None:
        d = Path(directory) if directory else self.directory
        if not d:
            raise ValueError("no directory set for process library")
        d.mkdir(parents=True, exist_ok=True)
        for p in self._items.values():
            p.save(str(d / f"{p.id}.json"))
