"""Reusable widgets: parameter editor, G-code text view, workers."""
from __future__ import annotations

import traceback
from fnmatch import fnmatchcase
from typing import Optional

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                             QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..core.gcode import GCodeProgram
from ..core.params import ALL_ITEMS, AUTO, Param


# --------------------------------------------------------------------------
# background worker
# --------------------------------------------------------------------------
class Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    message = pyqtSignal(str)
    progressed = pyqtSignal(float)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.args = args

    def run(self):
        try:
            res = self.fn(self, *self.args)
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.done.emit(res)


# --------------------------------------------------------------------------
# parameter editor
# --------------------------------------------------------------------------
class ParamEditor(QWidget):
    """Builds a form from a list of :class:`Param` and edits a value dict."""
    changed = pyqtSignal(dict)

    def __init__(self, params: list, values: dict, parent=None, context: Optional[dict] = None):
        super().__init__(parent)
        self.params = params
        self.context = context or {}
        self.values = {p.name: values.get(p.name, p.default) for p in params}
        self._widgets = {}
        self._setters = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        groups: dict = {}
        rows: dict = {}
        for p in params:
            if getattr(p, "hidden", False):
                continue                   # value kept in self.values, edited elsewhere
            if p.group not in groups:
                box = QGroupBox(p.group.replace("&", "&&"))   # '&' is a mnemonic marker in Qt
                form = QFormLayout(box)
                form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                groups[p.group] = form
                outer.addWidget(box)
            form = groups[p.group]
            w = self._make(p)
            if p.row:
                if p.row not in rows:
                    h = QHBoxLayout()
                    h.setContentsMargins(0, 0, 0, 0)
                    rows[p.row] = h
                    lab = QLabel(p.row_label or p.row)
                    lab.setWordWrap(True)
                    form.addRow(lab, h)
                rows[p.row].addWidget(w, 1)
            elif p.type == "gcode":
                lab = QLabel(p.label)
                lab.setToolTip(p.help)
                form.addRow(lab)
                form.addRow(w)
            else:
                lab = QLabel(p.label + (f" [{p.unit}]" if p.unit else ""))
                lab.setWordWrap(True)
                lab.setToolTip(p.help)
                form.addRow(lab, w)
        outer.addStretch(1)

    def _make(self, p: Param) -> QWidget:
        v = self.values[p.name]
        if p.type in ("float", "int"):
            if p.type == "float":
                sb = QDoubleSpinBox()
                sb.setDecimals(p.decimals)
                sb.setSingleStep(p.step or (1.0 if p.decimals <= 1 else 0.1))
            else:
                sb = QSpinBox()
                sb.setSingleStep(int(p.step or 1))
            lo = p.min if p.min is not None else -1e6
            hi = p.max if p.max is not None else 1e6
            if p.type == "int":
                lo, hi = int(max(lo, -2**31)), int(min(hi, 2**31 - 1))
            sb.setRange(lo, hi)
            sb.setToolTip(p.help)
            sb.setKeyboardTracking(False)
            sb.setMinimumWidth(70)
            if v != AUTO and v is not None:
                sb.setValue(v)
            elif p.default not in (AUTO, None):
                sb.setValue(p.default)
            if not p.allow_auto:
                sb.valueChanged.connect(lambda val, n=p.name: self._set(n, val))
                self._widgets[p.name] = sb
                self._setters[p.name] = sb.setValue
                return sb
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox("auto")
            h.addWidget(sb, 1)
            h.addWidget(cb)
            real_min = sb.minimum()
            sentinel = real_min - (1 if p.type == "int" else 10 ** -p.decimals)
            sb.setSpecialValueText("auto")   # shown while the value sits on the sentinel
            manual = [v if v not in (AUTO, None) else (p.hint if p.hint is not None else
                                                        (p.default if p.default not in (AUTO, None) else real_min))]

            def show(auto):
                sb.blockSignals(True)
                if auto:
                    sb.setMinimum(sentinel)
                    sb.setValue(sentinel)
                else:
                    sb.setMinimum(real_min)
                    sb.setValue(manual[0])
                sb.setEnabled(not auto)
                sb.blockSignals(False)

            def on_value(val, n=p.name):
                if not cb.isChecked():
                    manual[0] = val
                    self._set(n, val)

            def on_auto(auto, n=p.name):
                show(auto)
                self._set(n, AUTO if auto else sb.value())

            cb.setChecked(v == AUTO)
            show(v == AUTO)
            sb.valueChanged.connect(on_value)
            cb.toggled.connect(on_auto)
            self._widgets[p.name] = box
            return box
        if p.type == "bool":
            cb = QCheckBox()
            cb.setChecked(bool(v))
            cb.setToolTip(p.help)
            cb.toggled.connect(lambda val, n=p.name: self._set(n, bool(val)))
            return cb
        if p.type == "choice":
            co = QComboBox()
            co.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            co.setMinimumContentsLength(6)
            for val, lab in zip(p.choice_values(), p.choice_labels()):
                co.addItem(lab, val)
            i = co.findData(v)
            co.setCurrentIndex(max(i, 0))
            co.setToolTip(p.help)

            def on_choice(_i, p=p, co=co):
                val = co.currentData()
                self._set(p.name, val)
                for other, ov in ((p.links or {}).get(val) or {}).items():
                    setter = self._setters.get(other)
                    if setter is not None:
                        setter(ov)
            co.currentIndexChanged.connect(on_choice)
            self._setters[p.name] = lambda val, co=co: co.setCurrentIndex(max(0, co.findData(val)))
            return co
        if p.type == "multi":
            return self._make_multi(p, v)
        if p.type == "gcode":
            from .gcode_edit import GCodeTemplateEdit
            # an empty stored value means 'the default': show the default text to edit
            ed = GCodeTemplateEdit(v if (v or "").strip() else (p.default or ""), p.default or "",
                                   self.context.get("workflow", "fdm"))
            ed.setToolTip(p.help)
            ed.changed.connect(lambda text, n=p.name: self._set(n, text))
            self._widgets[p.name] = ed
            self._setters[p.name] = ed.set_text
            return ed
        le = QLineEdit(str(v or ""))
        le.setToolTip(p.help)
        le.editingFinished.connect(lambda n=p.name, le=le: self._set(n, le.text()))
        return le

    def _make_multi(self, p: Param, v) -> QWidget:
        items = list(self.context.get(p.choices_from or "", []) or [])
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        if not items:
            lab = QLabel("All (load a file to choose)" if v == ALL_ITEMS else
                         "Selected: " + ", ".join(v if isinstance(v, list) else [str(v)]))
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#999;")
            lay.addWidget(lab)
            return box
        lw = QListWidget()
        sel = None if v == ALL_ITEMS else [s.lower() for s in (v if isinstance(v, list) else [v])]
        for name in items:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            on = sel is None or any(fnmatchcase(name.lower(), s) for s in sel)
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            lw.addItem(it)
        rows = min(len(items), 8)
        lw.setMaximumHeight(16777215)
        lw.setFixedHeight(lw.sizeHintForRow(0) * rows + 2 * lw.frameWidth() + 4)
        lay.addWidget(lw)
        row = QHBoxLayout()
        b_all, b_none = QPushButton("All"), QPushButton("None")
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch(1)
        lay.addLayout(row)

        def collect(*_a, n=p.name):
            checked = [lw.item(k).text() for k in range(lw.count())
                       if lw.item(k).checkState() == Qt.CheckState.Checked]
            self._set(n, ALL_ITEMS if len(checked) == lw.count() else checked)

        def set_all(state):
            lw.blockSignals(True)
            for k in range(lw.count()):
                lw.item(k).setCheckState(state)
            lw.blockSignals(False)
            collect()
        lw.itemChanged.connect(collect)
        b_all.clicked.connect(lambda: set_all(Qt.CheckState.Checked))
        b_none.clicked.connect(lambda: set_all(Qt.CheckState.Unchecked))
        self._widgets[p.name] = box
        return box

    def _set(self, name, value):
        self.values[name] = value
        self.changed.emit(dict(self.values))


# --------------------------------------------------------------------------
# G-code text view
# --------------------------------------------------------------------------
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


def small_button(text: str, tip: str = "", width: int = 34) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFixedWidth(width)
    return b
