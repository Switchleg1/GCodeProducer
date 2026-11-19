"""Messages panel (warnings/errors history) and pop-ups with "Don't show this again"."""
from __future__ import annotations

from gcodeproducer.gui.messages.messages_panel import MessagesPanel
from gcodeproducer.gui.messages.messages_constants import LEVEL_COLORS
from PyQt6.QtWidgets import QCheckBox, QMessageBox


def show_message(parent, prefs: dict, key: str, level: str, title: str, text: str,
                 question: bool = False, default_no: bool = False) -> bool:
    """Pop-up with "Don't show this again". Returns True for OK/Yes (and when disabled).

    Disabled messages are not shown; a disabled *question* permits the action as
    if the user chose Yes. Checking "Don't show this again" stores the preference
    in ``prefs['messages']``; the caller persists ``prefs``.
    """
    messages = prefs.setdefault("messages", {})
    if not messages.get(key, True):
        return True
    box = QMessageBox(parent)
    box.setIcon({"error": QMessageBox.Icon.Critical, "warning": QMessageBox.Icon.Warning}.get(level, QMessageBox.Icon.Information))
    box.setWindowTitle(title)
    box.setText(text)
    if question:
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No if default_no else QMessageBox.StandardButton.Yes)
    check = QCheckBox("Don't show this again")
    check.setToolTip("Re-enable it in Settings \u2192 Messages. It is still recorded in the Messages panel.")
    box.setCheckBox(check)
    result = box.exec()
    accepted = not question or result == QMessageBox.StandardButton.Yes
    if check.isChecked() and (accepted or not question):
        # Remembering a "No" would silently cancel later actions; only accepted answers are remembered.
        messages[key] = False
    return accepted
