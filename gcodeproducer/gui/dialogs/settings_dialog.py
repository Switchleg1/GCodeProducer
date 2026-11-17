"""Global application settings dialog (core.app_settings schema)."""
from __future__ import annotations


from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)
import gcodeproducer.core.settings.preferences as app_settings
from gcodeproducer.gui.editors.param_editor import ParamEditor
from gcodeproducer.gui.editors.section import Section


class SettingsDialog(QDialog):
    def __init__(self, values: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 640)
        self.values = dict(values)
        layout = QVBoxLayout(self)
        note = QLabel("Global preferences apply to every model and machine; they are stored next to the "
                      "profile libraries, not in a machine or process profile.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.editor = ParamEditor(app_settings.SCHEMA, self.values)
        self.editor.changed.connect(lambda v: self.values.update(v))
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.editor)
        box = Section("Messages", key="settings.messages")
        ml = box.body
        hint = QLabel("Pop-ups to show. Unchecked messages are still recorded in the Messages panel "
                      "(View → Messages). Confirmations that protect output, such as exporting CAM "
                      "with warnings or deleting profiles, always ask. Deleting reference geometry is "
                      "the exception: its confirmation can be remembered and switched back on here.")
        hint.setWordWrap(True)
        ml.addWidget(hint)
        self.message_checks = {}
        messages = dict(self.values.get("messages") or {})
        for key, label in app_settings.MESSAGES.items():
            cb = QCheckBox(label)
            cb.setChecked(messages.get(key, True))
            cb.toggled.connect(self._messages_changed)
            ml.addWidget(cb)
            self.message_checks[key] = cb
        row = QHBoxLayout()
        enable = QPushButton("Show all")
        enable.clicked.connect(lambda: [c.setChecked(True) for c in self.message_checks.values()])
        row.addWidget(enable)
        row.addStretch(1)
        ml.addLayout(row)
        bl.addWidget(box)
        bl.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(body)
        layout.addWidget(area, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                   | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        layout.addWidget(buttons)
        from gcodeproducer.gui.history.dialog_state import settings_history
        self.history = settings_history(self)

    def _messages_changed(self, *_):
        self.values["messages"] = {k: c.isChecked() for k, c in self.message_checks.items()}

    def _defaults(self):
        defaults = {**app_settings.DEFAULTS, "messages": dict(app_settings.DEFAULTS["messages"])}
        # The editor re-emits its whole value dict per widget; seed it first so
        # partially-updated emissions never reintroduce old values.
        self.editor.values.update({k: v for k, v in defaults.items() if k in self.editor.values})
        for name, value in defaults.items():
            setter = self.editor._setters.get(name)
            if setter:
                setter(value)
        self.values = defaults
        for cb in self.message_checks.values():
            cb.setChecked(True)

    def result_values(self) -> dict:
        return app_settings.validated(self.values)
