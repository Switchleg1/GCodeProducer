"""Declarative parameter definitions shared by the CLI and the GUI."""
from __future__ import annotations

from gcodeproducer.core.parameters.param import Param
from gcodeproducer.core.parameters.parameters_constants import AUTO, ALL_ITEMS
from typing import Optional, Sequence


def resolve_params(params: Sequence[Param], values: Optional[dict]) -> dict:
    """Fill defaults and coerce values; raises ValueError on unknown names."""
    values = dict(values or {})
    known = {p.name: p for p in params}
    unknown = [k for k in values if k not in known]
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(unknown)}")
    return {p.name: p.coerce(values.get(p.name, p.default)) for p in params}
