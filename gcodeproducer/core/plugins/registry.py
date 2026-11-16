"""Registry — plugins subsystem."""
from __future__ import annotations

class Registry:
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict = {}

    def register(self, cls):
        if not getattr(cls, "id", ""):
            raise ValueError(f"{cls!r} has no id")
        self._validate(cls)
        self._items[cls.id] = cls
        return cls

    def _validate(self, cls):
        if self.kind == "stage":
            import gcodeproducer.core.workflows.validation as wf
            wfs = getattr(cls, "workflows", ()) or ()
            if not wfs:
                raise ValueError(f"stage '{cls.id}' must declare workflows, e.g. workflows=(FDM,)")
            cls.workflows = wf.normalize_all(wfs)

    def get(self, id_: str):
        from gcodeproducer.core.plugins.discovery import ensure_loaded
        ensure_loaded()
        try:
            return self._items[id_]
        except KeyError:
            raise KeyError(f"unknown {self.kind} '{id_}'. Available: {', '.join(sorted(self._items))}") from None

    def all(self) -> list:
        from gcodeproducer.core.plugins.discovery import ensure_loaded
        ensure_loaded()
        return list(self._items.values())

    def ids(self) -> list:
        return [c.id for c in self.all()]
