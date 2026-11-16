"""LibrarySet — libraries subsystem."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from gcodeproducer.core.libraries.profile import Profile
from gcodeproducer.core.libraries.library import Library
from gcodeproducer.core.libraries.libraries_constants import KINDS, KIND_WORKFLOW

class LibrarySet:
    """All libraries under one root directory (``<root>/<kind>s/*.json``)."""

    def __init__(self, root: Optional[Path] = None):
        from gcodeproducer.core.libraries.schemas import default_root
        from gcodeproducer.core.libraries.process_library import ProcessLibrary
        self.root = Path(root) if root else default_root()
        self.libraries = {k: Library(k, self.root / f"{k}s") for k in KINDS}
        self.processes = ProcessLibrary(self.root / "processes")

    def __getitem__(self, kind: str) -> Library:
        return self.libraries[kind]

    @property
    def machines(self) -> Library:
        return self.libraries["machine"]

    def load(self) -> "LibrarySet":
        for lib in self.libraries.values():
            lib.load_dir()
        self.processes.load_dir()
        return self

    def save(self) -> None:
        for lib in self.libraries.values():
            lib.save_all()
        self.processes.save_all()

    # ------------------------------------------- consumables for a machine
    def consumables_for(self, machine: Profile, kind: str) -> list:
        """Profiles of ``kind`` that ``machine`` allows (respecting workflow)."""
        wfl = KIND_WORKFLOW.get(kind)
        if wfl and wfl != machine.workflow:
            return []
        return [p for p in self.libraries[kind].all() if machine.allows(kind, p.id)]
