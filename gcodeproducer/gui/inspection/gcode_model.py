"""GCodeModel — inspection subsystem."""
from __future__ import annotations
from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt
from PyQt6.QtGui import QBrush, QColor
from gcodeproducer.core.gcode.program import GCodeProgram

class GCodeModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.prog: GCodeProgram | None = None
        self._ins = QBrush(QColor(40, 110, 50))
        self._mod = QBrush(QColor(120, 95, 25))
        self._comment = QBrush(QColor(130, 135, 140))

    def set_program(self, prog):
        self.beginResetModel()
        self.prog = prog
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if (self.prog is None or parent.isValid()) else len(self.prog.lines)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if self.prog is None:
            return None
        ln = self.prog.lines[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{index.row() + 1:>7}  {ln.text}"
        if role == Qt.ItemDataRole.BackgroundRole:
            if ln.origin is None:
                return self._ins
            if ln.dirty or ln.note:
                return self._mod
        elif role == Qt.ItemDataRole.ForegroundRole:
            if ln.cmd is None and not ln.params:
                return self._comment
        elif role == Qt.ItemDataRole.ToolTipRole:
            parts = [f"layer {ln.layer + 1}", f"feature: {ln.feature}"]
            if ln.origin is not None:
                parts.append(f"source line {ln.origin + 1}")
            if ln.note:
                parts.append(ln.note)
            return "\n".join(parts)
        return None
