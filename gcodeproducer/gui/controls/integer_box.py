"""IntegerBox — the application's whole-number input."""
from __future__ import annotations
from PyQt6.QtWidgets import QSpinBox
from .warning_tooltip import WarningTooltip
from .controls_constants import INTEGER_LIMIT


class IntegerBox(WarningTooltip, QSpinBox):
    """A whole-number spin box with limits, display options and a warning state (see WarningTooltip)."""

    def __init__(self, minimum=-INTEGER_LIMIT, maximum=INTEGER_LIMIT, value=None, *, step=None,
                 suffix="", prefix="", tooltip="", special="", tracking=True, parent=None):
        super().__init__(parent)
        self.set_limits(int(max(minimum, -INTEGER_LIMIT)), int(min(maximum, INTEGER_LIMIT)))
        if step is not None:
            self.setSingleStep(int(step))
        if suffix:
            self.setSuffix(suffix)
        if prefix:
            self.setPrefix(prefix)
        if special:
            self.setSpecialValueText(special)
        self.setKeyboardTracking(tracking)
        self.setToolTip(tooltip)
        if value is not None:
            self.setValue(int(value))
