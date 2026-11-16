"""Profile — libraries subsystem."""
from __future__ import annotations
import json, gcodeproducer.core.workflows.validation as wf
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from gcodeproducer.core.parameters.parameters_constants import ALL_ITEMS
from gcodeproducer.core.parameters.resolution import resolve_params
from gcodeproducer.core.libraries.libraries_constants import KIND_WORKFLOW

@dataclass
class Profile:
    """One reusable profile (machine / material / nozzle / tool)."""
    kind: str
    name: str
    values: dict = field(default_factory=dict)
    workflow: str = wf.FDM               # machine: its workflow; others: fixed by kind
    id: str = ""
    path: Optional[str] = None           # file it was loaded from / saved to

    def __post_init__(self):
        from gcodeproducer.core.libraries.schemas import slugify
        if self.kind in KIND_WORKFLOW:
            self.workflow = KIND_WORKFLOW[self.kind]
        else:
            self.workflow = wf.normalize(self.workflow)
        if not self.id:
            self.id = slugify(self.name)

    # ------------------------------------------------------------- schema
    def schema(self) -> list:
        from gcodeproducer.core.libraries.schemas import schema
        return schema(self.kind, self.workflow)

    def resolved(self) -> dict:
        """Values with defaults filled and coerced to the right types.

        Keys that are no longer part of the schema (settings removed or moved, e.g.
        the speeds that moved from the machine to the process) are ignored, so older
        profile files keep loading."""
        known = {p.name for p in self.schema()}
        return resolve_params(self.schema(), {k: v for k, v in self.values.items() if k in known})

    def get(self, key: str, default=None):
        v = self.resolved()
        return v.get(key, default)

    # ---------------------------------------------------- allowed (machine)
    def allows(self, kind: str, profile_id: str) -> bool:
        """Machine only: True if ``profile_id`` of ``kind`` is available here."""
        if self.kind != "machine":
            return True
        sel = self.get(f"allowed_{kind}s")
        if sel in (ALL_ITEMS, None) or sel == []:
            return sel != []        # [] = none allowed, "*"/None = all allowed
        return profile_id in sel

    # ----------------------------------------------------------- persist
    def to_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, "name": self.name,
                "workflow": self.workflow, "values": dict(self.values)}

    @classmethod
    def from_dict(cls, d: dict, path: Optional[str] = None) -> "Profile":
        return cls(kind=d["kind"], name=d.get("name", d.get("id", "")),
                   values=dict(d.get("values", {})), workflow=d.get("workflow", wf.FDM),
                   id=d.get("id", ""), path=path)

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        self.path = path

    @classmethod
    def load(cls, path: str) -> "Profile":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh), str(path))
