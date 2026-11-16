"""GCodeTemplateEdit — editors subsystem."""
from __future__ import annotations

from .editors_constants import TEMPLATE_BLOCK_SNIPPETS
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
import gcodeproducer.core.gcode.variables as gcode_vars
from gcodeproducer.core.gcode.templates import check, render

class GCodeTemplateEdit(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, text: str = "", default: str = "", workflow: str = "fdm", parent=None):
        super().__init__(parent)
        self.default = default or ""
        self.workflow = workflow
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        self.edit = QPlainTextEdit()
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(9)
        self.edit.setFont(f)
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.edit.setMinimumHeight(150)
        self.edit.setPlaceholderText("(empty: the default is used)")
        self.edit.setPlainText(text if text is not None else "")
        lay.addWidget(self.edit)

        row = QHBoxLayout()
        self.b_reset = QPushButton("Reset to default")
        self.b_reset.setToolTip("Replace the text with the default template")
        self.b_reset.clicked.connect(self.reset)
        self.b_insert = QToolButton()
        self.b_insert.setText("Insert variable \u25be")
        self.b_insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.b_insert.setMenu(self._variables_menu())
        self.b_preview = QPushButton("Preview")
        self.b_preview.setToolTip("Show the template filled with example values")
        self.b_preview.clicked.connect(self.preview)
        row.addWidget(self.b_reset)
        row.addWidget(self.b_insert)
        row.addWidget(self.b_preview)
        row.addStretch(1)
        lay.addLayout(row)

        self.problems = QLabel("")
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color:#f0a040;")
        lay.addWidget(self.problems)

        self._timer = QTimer(self)                 # emit / check shortly after typing stops
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._commit)
        self.edit.textChanged.connect(self._timer.start)
        self._check()

    def text(self) -> str:
        return self.edit.toPlainText()

    def set_text(self, text: str) -> None:
        self.edit.setPlainText(text or "")
        self._commit()

    def reset(self) -> None:
        self.set_text(self.default)

    def is_default(self) -> bool:
        return self.text().strip() in ("", self.default.strip())

    def insert_variable(self, name: str) -> None:
        self.edit.insertPlainText("{" + name + "}")
        self.edit.setFocus()

    def _variables_menu(self) -> QMenu:
        menu = QMenu(self)
        by_cat: dict = {}
        for v in gcode_vars.variables_for(self.workflow):
            by_cat.setdefault(v.category, []).append(v)
        for cat, items in by_cat.items():
            sub = menu.addMenu(cat)
            sub.setToolTipsVisible(True)
            for v in items:
                act = sub.addAction(f"{{{v.name}}}   \u2014 {v.description}")
                act.setToolTip(f"{v.description}\nexample: {v.example}")
                act.triggered.connect(lambda _=False, n=v.name: self.insert_variable(n))
        menu.addSeparator()
        for label, snippet in TEMPLATE_BLOCK_SNIPPETS:
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, s=snippet: self.edit.insertPlainText(s))
        return menu

    def _check(self) -> list:
        problems = check(self.text() or self.default, gcode_vars.names_for(self.workflow))
        self.problems.setText("\n".join(problems))
        self.problems.setVisible(bool(problems))
        self.b_reset.setEnabled(self.text() != self.default)
        return problems

    def _commit(self):
        self._timer.stop()
        self._check()
        self.changed.emit(self.text())

    def rendered_example(self) -> str:
        text = self.text() if self.text().strip() else self.default
        out, _ = render(text, gcode_vars.example_values(self.workflow))
        return out

    def preview(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Template preview (example values)")
        dlg.resize(560, 420)
        v = QVBoxLayout(dlg)
        view = QPlainTextEdit(self.rendered_example())
        view.setReadOnly(True)
        view.setFont(self.edit.font())
        v.addWidget(view)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        dlg.exec()
