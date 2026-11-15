"""Declarative parameter definitions shared by the CLI and the GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

AUTO = "auto"
ALL_ITEMS = "*"     # value of a 'multi' parameter selecting every item


@dataclass
class Param:
    """Describes one module parameter.

    type: 'float' | 'int' | 'bool' | 'choice' | 'str' | 'multi'
    choices: for 'choice' a list of values or (value, label) tuples
    choices_from: for 'multi' the name of a list supplied by the application at
        edit time (e.g. "operations" = operation names of the loaded file).
        The value is ``"*"`` (all items) or a list of selected names; the CLI
        accepts a comma separated string (wildcards allowed)
    links: for 'choice' {choice_value: {other_param: value}} - values the GUI
        puts into other parameters when that choice is selected
    hidden: not shown in GUI forms (the value is still stored / resolved, and the
        CLI accepts it) - for settings edited somewhere else in the UI
    allow_auto: the value may be the string "auto" (module decides itself)
    group: GUI group box title
    row / row_label: params sharing a ``row`` key are laid out on one line
    """
    name: str
    type: str = "float"
    default: Any = None
    label: str = ""
    help: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    decimals: int = 3
    choices: Optional[Sequence] = None
    unit: str = ""
    allow_auto: bool = False
    group: str = "General"
    row: Optional[str] = None
    row_label: Optional[str] = None
    hint: Optional[float] = None   # GUI: value offered when 'auto' is switched off
    choices_from: Optional[str] = None
    links: Optional[dict] = None
    hidden: bool = False           # GUI: not shown in the generated form (set elsewhere in the UI)

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").capitalize()

    # ----------------------------------------------------------------------
    def choice_values(self) -> list:
        out = []
        for c in self.choices or []:
            out.append(c[0] if isinstance(c, (tuple, list)) else c)
        return out

    def choice_labels(self) -> list:
        out = []
        for c in self.choices or []:
            out.append(str(c[1]) if isinstance(c, (tuple, list)) else str(c))
        return out

    def coerce(self, value: Any) -> Any:
        """Convert ``value`` (possibly a string from the CLI / JSON) to the param type."""
        if value is None:
            return self.default
        if isinstance(value, str) and value.strip().lower() == AUTO:
            if not self.allow_auto:
                raise ValueError(f"parameter '{self.name}' does not accept 'auto'")
            return AUTO
        t = self.type
        if t == "multi":
            if isinstance(value, str):
                v = value.strip()
                if v.lower() in ("", ALL_ITEMS, "all", AUTO):
                    return ALL_ITEMS
                return [s.strip() for s in v.split(",") if s.strip()]
            if isinstance(value, (list, tuple, set)):
                return [str(s) for s in value]
            raise ValueError(f"parameter '{self.name}': expected a list or '*'")
        if t == "float":
            v = float(value)
        elif t == "int":
            v = int(float(value))
        elif t == "bool":
            if isinstance(value, str):
                v = value.strip().lower() in ("1", "true", "yes", "on", "y")
            else:
                v = bool(value)
            return v
        elif t == "choice":
            vals = self.choice_values()
            if value in vals:
                return value
            sv = str(value).strip().lower()
            for cv in vals:
                if str(cv).lower() == sv:
                    return cv
            raise ValueError(f"parameter '{self.name}': '{value}' not in {vals}")
        else:
            return str(value)
        if self.min is not None and v < self.min:
            raise ValueError(f"parameter '{self.name}': {v} < minimum {self.min}")
        if self.max is not None and v > self.max:
            raise ValueError(f"parameter '{self.name}': {v} > maximum {self.max}")
        return v

    def describe(self) -> str:
        s = f"{self.name} ({self.type}"
        if self.unit:
            s += f", {self.unit}"
        s += f", default={self.default!r}"
        if self.allow_auto:
            s += ", accepts 'auto'"
        if self.choices:
            s += f", choices={self.choice_values()}"
        s += ")"
        if self.help:
            s += f": {self.help}"
        return s


def resolve_params(params: Sequence[Param], values: Optional[dict]) -> dict:
    """Fill defaults and coerce values; raises ValueError on unknown names."""
    values = dict(values or {})
    known = {p.name: p for p in params}
    unknown = [k for k in values if k not in known]
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(unknown)}")
    return {p.name: p.coerce(values.get(p.name, p.default)) for p in params}
