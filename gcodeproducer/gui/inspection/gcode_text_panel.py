"""GCodeTextPanel — inspection subsystem."""
from __future__ import annotations
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QAbstractItemView, QLineEdit, QListView, QSpinBox, QVBoxLayout, QWidget
from gcodeproducer.gui.inspection.gcode_model import GCodeModel

class GCodeTextPanel(QWidget):
    lineClicked = pyqtSignal(int)
    lineActivated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = GCodeModel(self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setUniformItemSizes(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(9)
        self.view.setFont(f)
        self.view.clicked.connect(lambda idx: self.lineClicked.emit(idx.row()))
        self.view.doubleClicked.connect(lambda idx: self.lineActivated.emit(idx.row()))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find text (Enter = next)")
        self.find.returnPressed.connect(self._find_next)
        self.goto = QSpinBox()
        self.goto.setRange(1, 1)
        self.goto.setPrefix("Line ")
        self.goto.setKeyboardTracking(False)
        self.goto.editingFinished.connect(lambda: self._goto(self.goto.value() - 1))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(self.find)
        lay.addWidget(self.goto)
        lay.addWidget(self.view, 1)

    def set_program(self, prog):
        self.model.set_program(prog)
        self.goto.setRange(1, max(1, len(prog.lines) if prog else 1))

    def show_line(self, row: int):
        if self.model.prog is None or not (0 <= row < self.model.rowCount()):
            return
        idx = self.model.index(row)
        self.view.setCurrentIndex(idx)
        self.view.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _goto(self, row):
        self.show_line(row)
        self.lineClicked.emit(row)

    def _find_next(self):
        text = self.find.text().strip().lower()
        prog = self.model.prog
        if not text or prog is None:
            return
        start = self.view.currentIndex().row() + 1
        n = len(prog.lines)
        for k in range(n):
            i = (start + k) % n
            if text in prog.lines[i].text.lower():
                self._goto(i)
                return
