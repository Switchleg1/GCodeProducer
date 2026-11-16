"""Shared scalar conversions for forms, CLI values and preferences."""
from .parameters_constants import TRUE_STRINGS


def coerce_bool(value) -> bool:
    return value.strip().lower() in TRUE_STRINGS if isinstance(value, str) else bool(value)
