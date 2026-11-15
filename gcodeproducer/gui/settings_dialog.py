"""Global application settings dialog (core.app_settings schema)."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout

from ..core import app_settings
from .widgets import ParamEditor


class SettingsDialog(QDialog):
    def __init__(self, values: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 480)
        self.values = dict(values)
        layout = QVBoxLayout(self)
        note = QLabel("Global preferences apply to every model and machine; they are stored next to the "
                      "profile libraries, not in a machine or process profile.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.editor = ParamEditor(app_settings.SCHEMA, self.values)
        self.editor.changed.connect(self.values.update)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.editor)
        layout.addWidget(area, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        layout.addWidget(buttons)

    def _defaults(self):
        self.values = dict(app_settings.DEFAULTS)
        for name, value in self.values.items():
            setter = self.editor._setters.get(name)
            if setter:
                setter(value)

    def result_values(self) -> dict:
        return app_settings.validated(self.values)
