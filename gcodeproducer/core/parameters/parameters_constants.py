"""Shared parameters constants and declarative tables."""
from __future__ import annotations

AUTO = "auto"

ALL_ITEMS = "*"     # value of a 'multi' parameter selecting every item

TRUE_STRINGS = frozenset(("1", "true", "yes", "on", "y"))

NUMBER_CASTS = {"float": float, "int": lambda value: int(float(value))}
