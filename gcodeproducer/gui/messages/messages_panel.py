"""MessagesPanel — messages subsystem."""
from __future__ import annotations
import time
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from gcodeproducer.gui.messages.messages_constants import LEVEL_COLORS

class MessagesPanel(QWidget):
    """Every warning/error the application reports, including ones whose pop-up is disabled.

    Kept to a single row band: the counts go to the dock title (``summaryChanged``)
    and Clear sits beside the list, so nothing is wasted below it.
    """
    MAX = 2000
    summaryChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Time", "Level", "Message"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 70)
        self.tree.setColumnWidth(1, 70)
        self.tree.setWordWrap(False)
        layout.addWidget(self.tree, 1)
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(2)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip("Remove all messages from the list")
        self.clear_button.clicked.connect(self.clear)
        side.addWidget(self.clear_button)
        self.summary = QLabel("No messages")
        self.summary.setVisible(False)              # shown in the dock title instead
        side.addWidget(self.summary)
        side.addStretch(1)
        layout.addLayout(side)
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
        self.summaryChanged.emit(self.summary.text())

    def snapshot(self):
        return {'counts': dict(self.counts), 'rows': [
            ([item.text(c) for c in range(3)], item.toolTip(2))
            for item in (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))]}

    def restore(self, state):
        if self.snapshot() == state:
            return
        self.tree.clear()
        for columns, tooltip in state['rows']:
            item = QTreeWidgetItem(columns)
            item.setToolTip(2, tooltip)
            color = LEVEL_COLORS.get(columns[1].lower(), LEVEL_COLORS['info'])
            item.setForeground(1, color)
            item.setForeground(2, color)
            self.tree.addTopLevelItem(item)
        self.counts = dict(state['counts'])
        self._summary()

    def texts(self):
        return [self.tree.topLevelItem(i).toolTip(2) for i in range(self.tree.topLevelItemCount())]
