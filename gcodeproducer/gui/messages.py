"""Messages panel (warnings/errors history) and pop-ups with "Don't show this again"."""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

LEVEL_COLORS = {"error": QColor(255, 110, 110), "warning": QColor(255, 200, 90), "info": QColor(170, 190, 200)}


class MessagesPanel(QWidget):
    """Every warning/error the application reports, including ones whose pop-up is disabled."""
    MAX = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Time", "Level", "Message"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 70)
        self.tree.setColumnWidth(1, 70)
        self.tree.setWordWrap(False)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.summary = QLabel("No messages")
        row.addWidget(self.summary, 1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        layout.addLayout(row)
        self.counts = {"error": 0, "warning": 0, "info": 0}

    def add(self, level: str, text: str, source: str = ""):
        level = level if level in LEVEL_COLORS else "info"
        first, *rest = str(text).strip().splitlines() or [""]
        item = QTreeWidgetItem([time.strftime("%H:%M:%S"), level.title(),
                                (f"{source}: " if source else "") + first + (" \u2026" if rest else "")])
        item.setToolTip(2, str(text))
        item.setForeground(1, LEVEL_COLORS[level])
        item.setForeground(2, LEVEL_COLORS[level])
        self.tree.addTopLevelItem(item)
        while self.tree.topLevelItemCount() > self.MAX:
            self.tree.takeTopLevelItem(0)
        self.tree.scrollToItem(item)
        self.counts[level] += 1
        self._summary()

    def clear(self):
        self.tree.clear()
        self.counts = dict.fromkeys(self.counts, 0)
        self._summary()

    def _summary(self):
        c = self.counts
        self.summary.setText(f"{c['error']} errors, {c['warning']} warnings" if any(c.values()) else "No messages")

    def texts(self):
        return [self.tree.topLevelItem(i).toolTip(2) for i in range(self.tree.topLevelItemCount())]


def show_message(parent, prefs: dict, key: str, level: str, title: str, text: str,
                 question: bool = False) -> bool:
    """Pop-up with "Don't show this again". Returns True for OK/Yes (and when disabled).

    Disabled messages are not shown; a disabled *question* is answered Yes, so only
    questions whose skipping is safe (e.g. "outside build volume, continue?") use this.
    Unchecking writes into ``prefs['messages']``; the caller persists ``prefs``.
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
    check = QCheckBox("Don't show this again")
    check.setToolTip("Re-enable it in Settings \u2192 Messages. It is still recorded in the Messages panel.")
    box.setCheckBox(check)
    result = box.exec()
    accepted = not question or result == QMessageBox.StandardButton.Yes
    if check.isChecked() and (accepted or not question):
        # Remembering a "No" would silently cancel later actions; only accepted answers are remembered.
        messages[key] = False
    return accepted
