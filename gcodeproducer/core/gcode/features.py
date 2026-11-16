"""Canonical feature types plus shared annotation helpers used by readers."""
from __future__ import annotations

from gcodeproducer.core.gcode.gcode_constants import (
    FEATURE_TABLE,
    FEATURE_IDS,
    FEATURE_LABELS,
    _FEATURE_COLORS,
    CAM_FEATURES,
    CAM_CUT_FEATURES,
    FEATURE_TOOLTIPS,
    PRINT_FEATURES,
    FDM_FEATURES,
)
import colorsys
import hashlib


def feature_label(fid: str) -> str:
    return FEATURE_LABELS.get(fid, fid)


def feature_color(fid: str) -> tuple:
    c = _FEATURE_COLORS.get(fid)
    if c is not None:
        return c
    # stable colour for dynamic names (e.g. CAM operation names)
    h = int(hashlib.md5(fid.encode("utf-8")).hexdigest()[:8], 16)
    hue = (h % 360) / 360.0
    return colorsys.hsv_to_rgb(hue, 0.65, 0.95)
