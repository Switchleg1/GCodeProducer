"""PipelineDialog — editors subsystem."""
from __future__ import annotations
import copy, gcodeproducer.core.plugins.discovery as plugins, gcodeproducer.core.workflows.validation as wf
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.pipeline.step import Step
from gcodeproducer.gui.editors.widgets import small_button

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
        from gcodeproducer.gui.editors.process_forms import _stage
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
        from gcodeproducer.gui.editors.process_forms import _stage
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
