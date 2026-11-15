"""Process (workflow options) editor.

The process is stored as a stage pipeline, but the operator sees it as a set of
*settings sections* - Layers, Skirt / brim, Walls, Top / bottom, Infill,
Travel & output - one per stage, in an accordion.  Optional sections have an
*Enabled* switch.  Adding / removing / reordering stages is an advanced
operation done in :class:`PipelineDialog`.

Only process settings live here.  Machine speeds, material temperatures /
retraction and nozzle sizes come from their own libraries.
"""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
                             QToolButton, QVBoxLayout, QWidget)

from ..core import plugins
from ..core import workflow as wf
from ..core.pipeline import SlicePipeline, Step
from .widgets import ParamEditor, small_button


def _stage(sid):
    try:
        return plugins.stages.get(sid)
    except KeyError:
        return None


def summary(step: Step) -> str:
    """Short one-line summary of a step's settings for a collapsed section header."""
    cls = _stage(step.stage)
    if cls is None:
        return ""
    if not step.enabled:
        return "off"
    try:
        p = cls.resolve(step.params)
    except Exception:
        return ""
    g = p.get
    sid = step.stage
    if sid == "fdm_slice":
        first = g("first_layer_height")
        return f"{g('layer_height'):g} mm" + ("" if first == "auto" else f", first {first:g} mm")
    if sid == "fdm_perimeters":
        return f"{g('perimeters')} loops"
    if sid == "fdm_top_bottom":
        return f"top {g('top_layers')}, bottom {g('bottom_layers')}"
    if sid == "fdm_infill":
        return f"{g('density'):g}% {g('pattern')}"
    if sid == "fdm_skirt_brim":
        t = g("type")
        if t == "none":
            return "none"
        parts = []
        if t in ("skirt", "both"):
            parts.append(f"skirt {g('skirt_loops')}× @ {g('skirt_distance'):g} mm")
        if t in ("brim", "both"):
            parts.append(f"brim {g('brim_width'):g} mm")
        return ", ".join(parts)
    if sid == "fdm_support":
        if g("placement") == "blocks":
            return f"manual blocks, {g('density'):g}%"
        where = "everywhere" if g("placement") == "everywhere" else "build plate"
        return f"{where}, {g('overhang_angle'):g}°, {g('density'):g}%"
    if sid == "fdm_emit":
        return "retract on travel" if g("retract") else "no retraction"
    if sid == "cam_profile":
        return f"{g('side')}" + ("" if g("stepdown") == "auto" else f", {g('stepdown'):g} mm/pass")
    return ""


class Section(QWidget):
    """Collapsible section: a header button and a content widget."""
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, content: QWidget, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setMinimumHeight(26)
        self.header.setObjectName("sectionHeader")
        self.header.toggled.connect(self._on_toggle)
        self.content = content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(content)
        self.set_title(title)
        self._on_toggle(expanded, emit=False)

    def set_title(self, title: str, info: str = "") -> None:
        self._title = title
        text = title.replace("&", "&&")
        if info:
            text += f"   — {info.replace('&', '&&')}"
        self.header.setText(text)

    def _on_toggle(self, on: bool, emit: bool = True):
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.content.setVisible(on)
        if emit:
            self.toggled.emit(on)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)


class ProcessEditor(QWidget):
    """Scrollable list of collapsible settings sections, one per pipeline step."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pipeline: SlicePipeline | None = None
        self.sections: list[Section] = []
        self.expanded: set = {"fdm_slice#1", "cam_profile#1"}    # remembered across reloads
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        b_open = QPushButton("Expand all")
        b_open.setFlat(True)
        b_open.clicked.connect(lambda: self._expand_all(True))
        b_close = QPushButton("Collapse all")
        b_close.setFlat(True)
        b_close.clicked.connect(lambda: self._expand_all(False))
        bar.addStretch(1)
        bar.addWidget(b_open)
        bar.addWidget(b_close)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.scroll, 1)

    # ------------------------------------------------------------------
    def _keys(self) -> list:
        counts: dict = {}
        out = []
        for step in self.pipeline.steps:
            counts[step.stage] = counts.get(step.stage, 0) + 1
            out.append((f"{step.stage}#{counts[step.stage]}", counts[step.stage]))
        return out

    def set_pipeline(self, pipeline: SlicePipeline) -> None:
        self.pipeline = pipeline
        pos = self.scroll.verticalScrollBar().value()
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(3)
        self.sections = []
        for step, (key, n) in zip(pipeline.steps, self._keys()):
            sec = Section("", self._page(step), key in self.expanded)
            sec.toggled.connect(lambda on, k=key: (self.expanded.add(k) if on else self.expanded.discard(k)))
            self.sections.append(sec)
            v.addWidget(sec)
        v.addStretch(1)
        self.scroll.setWidget(body)
        self._refresh_titles()
        self.scroll.verticalScrollBar().setValue(pos)

    def _expand_all(self, on: bool):
        for sec in self.sections:
            sec.set_expanded(on)

    def _title(self, step: Step, n: int = 1) -> str:
        cls = _stage(step.stage)
        name = cls.name if cls else f"{step.stage} (missing plugin)"
        return name + (f" ({n})" if n > 1 else "")

    def _refresh_titles(self):
        for sec, step, (_k, n) in zip(self.sections, self.pipeline.steps, self._keys()):
            sec.set_title(self._title(step, n), summary(step))

    def _page(self, step: Step) -> QWidget:
        cls = _stage(step.stage)
        page = QFrame()
        page.setObjectName("sectionBody")
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 4, 2, 6)
        if cls is None:
            v.addWidget(QLabel(f"Stage '{step.stage}' is not installed; it will be skipped."))
            return page

        head = QHBoxLayout()
        desc = QLabel(cls.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#9aa;")
        head.addWidget(desc, 1)
        reset = small_button("\u21ba", "Reset this section to defaults")
        head.addWidget(reset, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)

        editor = ParamEditor(cls.parameters(), {**cls.defaults(), **step.params})
        editor.setEnabled(step.enabled)

        if cls.optional:
            en = QCheckBox("Enabled")
            en.setChecked(step.enabled)

            def on_enabled(val, s=step, ed=editor):
                s.enabled = bool(val)
                ed.setEnabled(s.enabled)
                self._refresh_titles()
                self.changed.emit()
            en.toggled.connect(on_enabled)
            v.addWidget(en)

        def on_params(vals, s=step):
            s.params = dict(vals)
            self._refresh_titles()
            self.changed.emit()
        editor.changed.connect(on_params)

        def on_reset(_=False, s=step):
            s.params = {}
            self.set_pipeline(self.pipeline)
            self.changed.emit()
        reset.clicked.connect(on_reset)

        if not cls.parameters():
            v.addWidget(QLabel("(no settings)"))
        v.addWidget(editor)
        return page


# ==========================================================================
class PipelineDialog(QDialog):
    """Advanced: add / remove / reorder / enable the stages of a process."""

    def __init__(self, pipeline: SlicePipeline, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Process pipeline \u2014 {wf.label(pipeline.workflow)}")
        self.resize(460, 420)
        self.pipeline = copy.deepcopy(pipeline)
        lay = QVBoxLayout(self)
        info = QLabel("Stages run top to bottom. Core stages cannot be removed or disabled. "
                      "A stage can be added more than once (e.g. a second infill pass).")
        info.setWordWrap(True)
        info.setStyleSheet("color:#9aa;")
        lay.addWidget(info)

        row = QHBoxLayout()
        self.cb_add = QComboBox()
        for cls in sorted(plugins.stages.all(), key=lambda c: (c.category, c.name)):
            if cls.applies_to(pipeline.workflow):
                self.cb_add.addItem(f"{cls.name}   [{cls.category}]", cls.id)
                self.cb_add.setItemData(self.cb_add.count() - 1, cls.description,
                                        Qt.ItemDataRole.ToolTipRole)
        b_add = QPushButton("Add")
        b_add.clicked.connect(self._add)
        row.addWidget(self.cb_add, 1)
        row.addWidget(b_add)
        lay.addLayout(row)

        self.lst = QListWidget()
        self.lst.itemChanged.connect(self._toggled)
        lay.addWidget(self.lst, 1)
        brow = QHBoxLayout()
        for text, tip, fn in (("\u25b2", "Move up", lambda: self._move(-1)),
                              ("\u25bc", "Move down", lambda: self._move(1)),
                              ("\u2715", "Remove", self._remove)):
            b = small_button(text, tip)
            b.clicked.connect(fn)
            brow.addWidget(b)
        brow.addStretch(1)
        b_def = QPushButton("Restore default stages")
        b_def.clicked.connect(self._defaults)
        brow.addWidget(b_def)
        lay.addLayout(brow)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#e0a030;")
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._reload(0)

    def _reload(self, row=0):
        self.lst.blockSignals(True)
        self.lst.clear()
        for s in self.pipeline.steps:
            cls = _stage(s.stage)
            it = QListWidgetItem((cls.name if cls else s.stage) + ("" if (cls and cls.optional) else "   (core)"))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if s.enabled else Qt.CheckState.Unchecked)
            it.setToolTip(cls.description if cls else "")
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        if self.lst.count():
            self.lst.setCurrentRow(min(max(row, 0), self.lst.count() - 1))

    def _core(self, row) -> bool:
        cls = _stage(self.pipeline.steps[row].stage)
        return cls is not None and not cls.optional

    def _toggled(self, it):
        row = self.lst.row(it)
        on = it.checkState() == Qt.CheckState.Checked
        if not on and self._core(row):
            self.msg.setText("Core stages always run.")
            self._reload(row)
            return
        self.pipeline.steps[row].enabled = on

    def _add(self):
        sid = self.cb_add.currentData()
        if not sid:
            return
        row = self.lst.currentRow()
        at = row + 1 if row >= 0 else len(self.pipeline.steps)
        self.pipeline.steps.insert(at, Step(sid))
        self._reload(at)

    def _remove(self):
        row = self.lst.currentRow()
        if row < 0:
            return
        if self._core(row):
            self.msg.setText("Core stages cannot be removed.")
            return
        del self.pipeline.steps[row]
        self._reload(row)

    def _move(self, d):
        row = self.lst.currentRow()
        new = row + d
        steps = self.pipeline.steps
        if 0 <= row < len(steps) and 0 <= new < len(steps):
            steps[row], steps[new] = steps[new], steps[row]
            self._reload(new)

    def _defaults(self):
        keep = {s.stage: s for s in self.pipeline.steps}
        fresh = SlicePipeline.default(self.pipeline.workflow)
        fresh.steps = [keep.get(s.stage, s) for s in fresh.steps]
        self.pipeline = fresh
        self._reload(0)
