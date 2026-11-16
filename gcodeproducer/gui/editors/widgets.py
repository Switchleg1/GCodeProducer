"""Reusable widgets: parameter editor, G-code text view, workers."""
from __future__ import annotations

from gcodeproducer.gui.editors.param_editor import ParamEditor
from gcodeproducer.gui.inspection.gcode_model import GCodeModel
from gcodeproducer.gui.inspection.gcode_text_panel import GCodeTextPanel
from PyQt6.QtWidgets import QPushButton


# background worker


# parameter editor


# G-code text view


def small_button(text: str, tip: str = "", width: int = 34) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFixedWidth(width)
    return b
