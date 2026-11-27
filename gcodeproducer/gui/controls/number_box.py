"""NumberBox — the application's decimal input."""
from __future__ import annotations
from PyQt6.QtWidgets import QDoubleSpinBox
from .warning_tooltip import WarningTooltip
from .controls_constants import NUMBER_LIMIT


class NumberBox(WarningTooltip, QDoubleSpinBox):
    """A decimal spin box with limits, display options and a warning state (see WarningTooltip).

    ``tracking=False`` reports a typed value only when editing finishes, not on
    every keystroke. ``step`` defaults to 1 (0.1 for one decimal or more).
    """

    def __init__(self, minimum=-NUMBER_LIMIT, maximum=NUMBER_LIMIT, value=None, *, decimals=3, step=None,
                 suffix="", prefix="", tooltip="", special="", tracking=True, parent=None):
        super().__init__(parent)
        self.setDecimals(decimals)
        self.set_limits(minimum, maximum)
        if step is not None:
            self.setSingleStep(step)
        if suffix:
            self.setSuffix(suffix)
        if prefix:
            self.setPrefix(prefix)
        if special:
            self.setSpecialValueText(special)
        self.setKeyboardTracking(tracking)
        self.setToolTip(tooltip)
        if value is not None:
            self.setValue(value)
