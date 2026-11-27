"""WarningTooltip — the warning state shared by the number boxes."""
from __future__ import annotations
from .controls_constants import WARNING_COLOUR, WARNING_TIP_SEPARATOR


class WarningTooltip:
    """Mixin for a Qt spin box: an optional warning shown as orange text and leading its tooltip.

    The normal tooltip is kept: ``setToolTip`` sets it, ``set_warning`` puts a
    message in front of it and colours the value, ``set_warning(None)`` (or an
    empty message) restores both. The value itself is never changed.
    """

    def setToolTip(self, text):                      # noqa: N802 (Qt name)
        self._normal_tip = text or ""
        self._show_tip()

    def normal_tooltip(self):
        return getattr(self, "_normal_tip", "")

    def warning(self):
        """The current warning message, or None."""
        return getattr(self, "_warning", None)

    def set_warning(self, message=None):
        message = message or None
        if message == self.warning():
            return
        self._warning = message
        self.setStyleSheet(f"QAbstractSpinBox {{ color: {WARNING_COLOUR}; }}" if message else "")
        self._show_tip()

    def clear_warning(self):
        self.set_warning(None)

    def set_limits(self, minimum, maximum):
        """Allowed range; a value outside it is brought inside (by Qt)."""
        self.setRange(minimum, maximum)

    def _show_tip(self):
        normal, warning = self.normal_tooltip(), self.warning()
        text = warning + (WARNING_TIP_SEPARATOR + normal if normal else "") if warning else normal
        super().setToolTip(text)
