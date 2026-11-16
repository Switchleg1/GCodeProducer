"""Library — libraries subsystem."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.libraries.profile import Profile

class Library:
    """A collection of profiles of one ``kind``, backed by a directory."""

    def __init__(self, kind: str, directory: Optional[Path] = None):
        self.kind = kind
        self.directory = Path(directory) if directory else None
        self._items: dict[str, Profile] = {}

    def add(self, profile: Profile) -> Profile:
        if profile.kind != self.kind:
            raise ValueError(f"{profile.kind} profile added to {self.kind} library")
        self._items[profile.id] = profile
        return profile

    def remove(self, profile_id: str) -> None:
        self._items.pop(profile_id, None)

    def get(self, profile_id: str) -> Profile:
        return self._items[profile_id]

    def all(self, workflow: Optional[str] = None) -> list:
        out = list(self._items.values())
        if workflow and self.kind == "machine":
            out = [p for p in out if p.workflow == wf.normalize(workflow)]
        return out

    def ids(self) -> list:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    # ----------------------------------------------------------- persist
    def load_dir(self, directory: Optional[Path] = None) -> int:
        d = Path(directory) if directory else self.directory
        if not d or not d.is_dir():
            return 0
        self.directory = d
        n = 0
        for f in sorted(d.glob("*.json")):
            try:
                p = Profile.load(str(f))
                if p.kind == self.kind:
                    self.add(p)
                    n += 1
            except Exception:
                pass
        return n

    def save_all(self, directory: Optional[Path] = None) -> None:
        d = Path(directory) if directory else self.directory
        if not d:
            raise ValueError("no directory set for library")
        d.mkdir(parents=True, exist_ok=True)
        for p in self._items.values():
            p.save(str(d / f"{p.id}.json"))
