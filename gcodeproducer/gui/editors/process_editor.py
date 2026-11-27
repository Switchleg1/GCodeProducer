"""ProcessEditor — editors subsystem."""
from __future__ import annotations
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.pipeline.step import Step
from gcodeproducer.gui.editors.param_editor import ParamEditor
from gcodeproducer.gui.editors.widgets import small_button
from gcodeproducer.gui.editors.section import Section

class ProcessEditor(QWidget):
    """Scrollable list of collapsible settings sections, one per pipeline step."""
    changed = pyqtSignal()
    seamTargetChanged = pyqtSignal(object)
    seamPickRequested = pyqtSignal()

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

    def _keys(self) -> list:
        counts: dict = {}
        out = []
        for step in self.pipeline.steps:
            counts[step.stage] = counts.get(step.stage, 0) + 1
            out.append((f"{step.stage}#{counts[step.stage]}", counts[step.stage]))
        return out

    def show_overrides(self, messages):
        """Warn on the output (speed) settings the machine caps; see core.fdm.value_overrides."""
        self._overrides = dict(messages)
        if getattr(self, "_seam_editor", None) is not None:
            self._seam_editor.set_warnings(self._overrides)

    def set_pipeline(self, pipeline: SlicePipeline) -> None:
        self.pipeline = pipeline
        self._seam_editor = None
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
        self._emit_seam_target()

    def _emit_seam_target(self):
        vals = self._seam_editor.values if self._seam_editor is not None else {}
        self.seamTargetChanged.emit((vals['seam_x'], vals['seam_y']) if vals.get('seam') == 'xy' else None)

    def set_seam_target(self, x, y):
        editor = self._seam_editor
        if editor is not None and editor.values['seam'] == 'xy':
            editor.set_numeric_values(seam_x=x, seam_y=y)

    def _expand_all(self, on: bool):
        for sec in self.sections:
            sec.set_expanded(on)

    def _title(self, step: Step, n: int = 1) -> str:
        from gcodeproducer.gui.editors.process_forms import _stage
        cls = _stage(step.stage)
        name = cls.name if cls else f"{step.stage} (missing plugin)"
        return name + (f" ({n})" if n > 1 else "")

    def _refresh_titles(self):
        from gcodeproducer.gui.editors.process_forms import summary
        for sec, step, (_k, n) in zip(self.sections, self.pipeline.steps, self._keys()):
            sec.set_title(self._title(step, n), summary(step))

    def _page(self, step: Step) -> QWidget:
        from gcodeproducer.gui.editors.process_forms import _stage
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

        editor = ParamEditor(cls.parameters(), cls.resolve(step.params), section_level=1)
        editor.setEnabled(step.enabled)
        if step is self.pipeline.step('fdm_emit'):
            self._seam_editor = editor
            editor.set_warnings(getattr(self, "_overrides", {}))

            def show_retraction_fields(values):
                mode = values['retraction_mode']
                editor.set_field_visible('min_travel_retract', mode != 'off')
                editor.set_field_visible('inside_travel_retract', mode == 'separate')

            show_retraction_fields(editor.values)
            editor.changed.connect(show_retraction_fields)
            seam = next(section for section in editor.sections if section.title() == 'Seam')
            pick = QPushButton('Pick on bed')
            pick.clicked.connect(self.seamPickRequested.emit)
            seam.body.addRow(pick)
            pick.setEnabled(editor.values['seam'] == 'xy')
            editor.changed.connect(lambda vals: pick.setEnabled(vals['seam'] == 'xy'))

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
            if editor is self._seam_editor:
                self._emit_seam_target()
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
