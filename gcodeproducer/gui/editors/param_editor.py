"""ParamEditor — editors subsystem."""
from __future__ import annotations
from fnmatch import fnmatchcase
from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from gcodeproducer.core.parameters.parameters_constants import ALL_ITEMS, AUTO
from gcodeproducer.core.parameters.param import Param
from gcodeproducer.core.parameters.resolution import resolve_params

class ParamEditor(QWidget):
    """Builds a form from a list of :class:`Param` and edits a value dict."""
    changed = pyqtSignal(dict)

    def __init__(self, params: list, values: dict, parent=None, context: Optional[dict] = None):
        super().__init__(parent)
        self.params = params
        self.context = context or {}
        self.values = resolve_params(params, {p.name: values[p.name] for p in params if p.name in values})
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
            self._widgets[p.name] = cb
            self._setters[p.name] = lambda val, c=cb: c.setChecked(bool(val))
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
            from gcodeproducer.gui.editors.gcode_template_edit import GCodeTemplateEdit
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
        self._widgets[p.name] = le
        self._setters[p.name] = le.setText
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

    def commit(self):
        """Flush text still being edited before a form is saved or replaced.

        Numeric fields deliberately have keyboardTracking=False. Their text can
        differ from value() until focus-out/Enter, which need not happen before
        a dialog accepts or switches its profile. Do not rely on Qt focus order.
        """
        from PyQt6.QtWidgets import QAbstractSpinBox
        for spin in self.findChildren(QAbstractSpinBox):
            if spin.isEnabled():
                spin.interpretText()
        for name, widget in self._widgets.items():
            if isinstance(widget, QLineEdit):
                self.values[name] = widget.text()
        self.changed.emit(dict(self.values))

    def _set(self, name, value):
        self.values[name] = value
        self.changed.emit(dict(self.values))
