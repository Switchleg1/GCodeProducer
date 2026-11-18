"""Bounds and input events for editor history."""
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QSlider, QSpinBox, QTabBar)

HISTORY_LIMIT = 100
SIMPLE_WIDGET_STATES = (
    ((QSpinBox, QDoubleSpinBox, QSlider), 'value', 'value'),
    (QComboBox, 'combo', 'currentIndex'),
    (QTabBar, 'tab', 'currentIndex'),
)
DIRECT_RESTORE_SETTERS = {'value': 'setValue', 'combo': 'setCurrentIndex', 'tab': 'setCurrentIndex'}
SELECTION_STATES = frozenset(('list', 'tree', 'tab', 'view'))
INPUT_EVENTS = frozenset((QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                          QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.Wheel,
                          QEvent.Type.FocusOut))
SHORTCUTS = (
    ("Ctrl+Z", "Undo the last edit or selection"),
    ("Ctrl+Shift+Z / Ctrl+Y", "Redo"),
    ("Ctrl+L", "Place on face: then click a model face (Esc cancels)"),
    ("Ctrl+O", "Add models (FDM) / import model (CAM)"),
    ("Ctrl+D", "Prepare: copy the selected FDM model"),
    ("Ctrl+R", "Slice / generate paths"),
    ("Ctrl+S", "Save G-code"), ("Ctrl+,", "Settings"), ("Ctrl+Q", "Quit"),
    ("Ctrl+1 / Ctrl+2", "Prepare / Preview"),
    ("PgUp / PgDn", "Next / previous layer"),
    ("Home / End", "First / last layer"),
    ("Space", "Preview: play / pause (viewport or playback bar focused)"),
    ("Left / Right", "Preview: previous / next move (viewport or playback bar focused)"),
    ("F", "Viewport: fit"), ("1 / 2 / 3 / 4", "Viewport: iso / top / front / right"),
    ("Delete / Backspace", "Prepare: delete selected support block"),
    ("Esc", "Cancel face placement, block tools, CAM picking or reference drawing/editing"),
)
