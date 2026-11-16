"""ProcessLibrary — libraries subsystem."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.libraries.process_preset import ProcessPreset

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
