"""GCodeProducer main window: pick workflow/machine/consumables, build a slice
pipeline, produce G-code and view it in 3D."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                             QPushButton, QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget)

from .. import __version__
from ..core import defaults, plugins
from ..core import workflow as wf
from ..core.pipeline import SlicePipeline, Step
from ..core.profiles import KINDS, LibrarySet, Profile, schema
from ..core.session import build_job, find_importer, load_mesh, slice_job
from .camera import Camera
from .view_state import COLOR_MODES, ViewState
from .viewer import GCodeViewer
from .widgets import GCodeTextPanel, ParamEditor, Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GCodeProducer {__version__}")
        self.resize(1360, 860)
        self.libset = LibrarySet().load()
        defaults.seed(self.libset)
        self.workflow = wf.FDM
        self.mesh = None
        self.model_path = None
        self.program = None
        self.pipelines = {w: SlicePipeline.default(w) for w in wf.ALL}
        self._worker = None

        self.camera = Camera()
        self.state = ViewState()
        self._build_ui()
        self._reload_workflow()

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._controls())
        split.addWidget(self._viewer_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([400, 960])
        self.setCentralWidget(split)
        self._menu()
        self.statusBar().showMessage("Ready")

    def _menu(self):
        m = self.menuBar().addMenu("&File")
        a_open = QAction("Import model…", self); a_open.triggered.connect(self.import_model)
        a_save = QAction("Save G-code…", self); a_save.triggered.connect(self.save_gcode)
        a_lib = QAction("Edit libraries…", self); a_lib.triggered.connect(self.edit_libraries)
        a_quit = QAction("Quit", self); a_quit.triggered.connect(self.close)
        for a in (a_open, a_save, a_lib):
            m.addAction(a)
        m.addSeparator(); m.addAction(a_quit)

    def _controls(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)

        # workflow
        box = QGroupBox("Workflow"); bl = QVBoxLayout(box)
        self.cb_workflow = QComboBox()
        for w in wf.ALL:
            self.cb_workflow.addItem(wf.label(w), w)
        self.cb_workflow.currentIndexChanged.connect(self._on_workflow)
        bl.addWidget(self.cb_workflow)
        lay.addWidget(box)

        # machine + consumables
        box = QGroupBox("Machine && consumables"); self.cons_form = QVBoxLayout(box)
        self.cb_machine = QComboBox(); self.cb_machine.currentIndexChanged.connect(self._on_machine)
        self.cons_form.addWidget(QLabel("Machine")); self.cons_form.addWidget(self.cb_machine)
        self.cons_widgets: dict = {}
        self.cons_container = QVBoxLayout(); self.cons_form.addLayout(self.cons_container)
        btn_lib = QPushButton("Edit libraries…"); btn_lib.clicked.connect(self.edit_libraries)
        self.cons_form.addWidget(btn_lib)
        lay.addWidget(box)

        # model
        box = QGroupBox("Model"); ml = QVBoxLayout(box)
        self.lbl_model = QLabel("No model loaded"); self.lbl_model.setWordWrap(True)
        btn_imp = QPushButton("Import model (STL)…"); btn_imp.clicked.connect(self.import_model)
        ml.addWidget(self.lbl_model); ml.addWidget(btn_imp)
        lay.addWidget(box)

        # pipeline
        box = QGroupBox("Slice pipeline"); pl = QVBoxLayout(box)
        self.lst_stages = QListWidget()
        self.lst_stages.currentRowChanged.connect(self._on_stage_selected)
        self.lst_stages.itemChanged.connect(self._on_stage_toggled)
        self.lst_stages.setMaximumHeight(150)
        pl.addWidget(self.lst_stages)
        self.param_area = QScrollArea(); self.param_area.setWidgetResizable(True)
        self.param_area.setMinimumHeight(160)
        pl.addWidget(self.param_area, 1)
        lay.addWidget(box, 1)

        # actions
        self.btn_slice = QPushButton("Slice  \u25b6"); self.btn_slice.clicked.connect(self.run_slice)
        self.btn_save = QPushButton("Save G-code…"); self.btn_save.clicked.connect(self.save_gcode)
        self.btn_save.setEnabled(False)
        row = QHBoxLayout(); row.addWidget(self.btn_slice); row.addWidget(self.btn_save)
        lay.addLayout(row)

        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        lay.addWidget(self.log_view)

        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(panel)
        sc.setMinimumWidth(380)
        return sc

    def _viewer_panel(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Colour"))
        self.cb_color = QComboBox()
        for cid, lab in COLOR_MODES:
            self.cb_color.addItem(lab, cid)
        self.cb_color.currentIndexChanged.connect(
            lambda: self.state.set("colors", color_mode=self.cb_color.currentData()))
        bar.addWidget(self.cb_color)
        self.chk_travel = QCheckBox("Travels")
        self.chk_travel.toggled.connect(lambda v: self.state.set("colors", show_travel=v))
        bar.addWidget(self.chk_travel)
        bar.addWidget(QLabel("Max layer"))
        self.sld_layer = QSlider(Qt.Orientation.Horizontal)
        self.sld_layer.valueChanged.connect(self._on_layer)
        bar.addWidget(self.sld_layer, 1)
        lay.addLayout(bar)

        self.viewer = GCodeViewer(self.camera, self.state, title="GCodeProducer")
        self.viewer.lineSelected.connect(lambda i: self.text_panel.show_line(i))
        self.text_panel = GCodeTextPanel()
        self.text_panel.lineClicked.connect(self.viewer.set_selected)
        vs = QSplitter(Qt.Orientation.Vertical)
        vs.addWidget(self.viewer); vs.addWidget(self.text_panel)
        vs.setStretchFactor(0, 3); vs.setStretchFactor(1, 1)
        lay.addWidget(vs, 1)
        return w

    # ------------------------------------------------------------ workflow
    def _on_workflow(self):
        self.workflow = self.cb_workflow.currentData()
        self._reload_workflow()

    def _reload_workflow(self):
        self.cb_machine.blockSignals(True)
        self.cb_machine.clear()
        for p in self.libset.machines.all(self.workflow):
            self.cb_machine.addItem(p.name, p.id)
        self.cb_machine.blockSignals(False)
        self._on_machine()
        self._reload_stages()

    def _on_machine(self):
        # rebuild consumable selectors for the selected machine
        while self.cons_container.count():
            it = self.cons_container.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cons_widgets.clear()
        machine = self._machine()
        if machine is None:
            return
        kinds = [k for k in wf.LIBRARIES[self.workflow] if k != "machine"]
        for kind in kinds:
            self.cons_container.addWidget(QLabel(kind.capitalize()))
            cb = QComboBox()
            for p in self.libset.consumables_for(machine, kind):
                cb.addItem(p.name, p.id)
            self.cons_container.addWidget(cb)
            self.cons_widgets[kind] = cb

    def _machine(self):
        mid = self.cb_machine.currentData()
        try:
            return self.libset.machines.get(mid) if mid else None
        except KeyError:
            return None

    # ------------------------------------------------------------- stages
    def _reload_stages(self):
        self.lst_stages.blockSignals(True)
        self.lst_stages.clear()
        pipe = self.pipelines[self.workflow]
        for step in pipe.steps:
            cls = plugins.stages.get(step.stage)
            it = QListWidgetItem(f"{cls.name}")
            it.setData(Qt.ItemDataRole.UserRole, step.stage)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            optional = cls.optional
            it.setCheckState(Qt.CheckState.Checked if step.enabled else Qt.CheckState.Unchecked)
            if not optional:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                it.setToolTip("core stage (always runs)")
            self.lst_stages.addItem(it)
        self.lst_stages.blockSignals(False)
        if self.lst_stages.count():
            self.lst_stages.setCurrentRow(0)

    def _on_stage_toggled(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        for step in self.pipelines[self.workflow].steps:
            if step.stage == sid:
                step.enabled = item.checkState() == Qt.CheckState.Checked

    def _on_stage_selected(self, row):
        if row < 0:
            return
        pipe = self.pipelines[self.workflow]
        step = pipe.steps[row]
        cls = plugins.stages.get(step.stage)
        params = cls.parameters()
        values = {**cls.defaults(), **step.params}
        editor = ParamEditor(params, values)
        editor.changed.connect(lambda vals, s=step: s.params.update(vals))
        self.param_area.setWidget(editor)

    # -------------------------------------------------------------- model
    def import_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import model", "", "Meshes (*.stl)")
        if path:
            self.open_model(path)

    def open_model(self, path: str):
        try:
            find_importer(path)
            self.mesh = load_mesh(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.model_path = path
        lo, hi = self.mesh.bounds
        size = hi - lo
        self.lbl_model.setText(f"{Path(path).name}\n{size[0]:.1f} \u00d7 {size[1]:.1f} \u00d7 {size[2]:.1f} mm")
        self.log(f"Loaded {path}")

    # -------------------------------------------------------------- slice
    def run_slice(self):
        if self.mesh is None:
            QMessageBox.information(self, "No model", "Import a model first.")
            return
        machine = self._machine()
        if machine is None:
            QMessageBox.information(self, "No machine", "Add / select a machine for this workflow.")
            return
        kw = dict(material=None, nozzle=None, tools=[])
        if self.workflow == wf.FDM:
            kw["material"] = self._consumable("material")
            kw["nozzle"] = self._consumable("nozzle")
        else:
            t = self._consumable("tool")
            kw["tools"] = [t] if t else []
        try:
            job = build_job(self.workflow, machine, mesh=self.mesh, model_path=self.model_path, **kw)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot slice", str(exc)); return
        pipe = self.pipelines[self.workflow]

        self.btn_slice.setEnabled(False)
        self.log_view.clear()
        self.log(f"Slicing ({wf.short(self.workflow)})…")

        def task(worker, job=job, pipe=pipe):
            return slice_job(job, pipe, log=worker.message.emit, progress=worker.progressed.emit)

        self._worker = Worker(task)
        self._worker.message.connect(self.log)
        self._worker.progressed.connect(lambda f: self.statusBar().showMessage(f"Slicing… {f*100:.0f}%"))
        self._worker.done.connect(self._slice_done)
        self._worker.failed.connect(self._slice_failed)
        self._worker.start()

    def _consumable(self, kind):
        cb = self.cons_widgets.get(kind)
        if not cb or cb.currentData() is None:
            return None
        return self.libset[kind].get(cb.currentData())

    def _slice_done(self, result):
        self.btn_slice.setEnabled(True)
        self.program = result.program
        if self.program is None:
            self.log("No program produced."); return
        self.btn_save.setEnabled(True)
        self._show_program(self.program)
        self.statusBar().showMessage(
            f"Done: {len(self.program.lines)} lines, {self.program.num_layers} layers", 6000)

    def _slice_failed(self, tb):
        self.btn_slice.setEnabled(True)
        self.log(tb)
        QMessageBox.critical(self, "Slice failed", tb.strip().splitlines()[-1])

    def _show_program(self, prog):
        from ..core.toolpath import build_toolpath
        tp = build_toolpath(prog)
        self.viewer.set_toolpath(tp)
        lo, hi = tp.bounds(solid_only=False)
        self.camera.fit(lo, hi)
        self.text_panel.set_program(prog)
        n = prog.num_layers
        self.sld_layer.blockSignals(True)
        self.sld_layer.setRange(1, max(1, n))
        self.sld_layer.setValue(max(1, n))
        self.sld_layer.blockSignals(False)
        self.state.set("colors", layer_max=1 << 30)

    def _on_layer(self, v):
        self.state.set("colors", layer_max=v - 1)

    # -------------------------------------------------------------- output
    def save_gcode(self):
        if self.program is None:
            return
        base = Path(self.model_path).with_suffix(".gcode").name if self.model_path else "out.gcode"
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code", base, "G-code (*.gcode *.nc *.g)")
        if path:
            self.program.save(path)
            self.statusBar().showMessage(f"Saved {path}", 5000)

    def edit_libraries(self):
        dlg = LibraryDialog(self.libset, self)
        if dlg.exec():
            self.libset.save()
            self._reload_workflow()

    def log(self, msg: str):
        self.log_view.appendPlainText(str(msg))


# ==========================================================================
class LibraryDialog(QDialog):
    """Add / duplicate / delete / edit profiles across all libraries."""

    def __init__(self, libset: LibrarySet, parent=None):
        super().__init__(parent)
        self.libset = libset
        self.setWindowTitle("Libraries")
        self.resize(720, 560)
        lay = QHBoxLayout(self)

        left = QVBoxLayout()
        self.cb_kind = QComboBox()
        for k in KINDS:
            self.cb_kind.addItem(k.capitalize(), k)
        self.cb_kind.currentIndexChanged.connect(self._reload)
        left.addWidget(self.cb_kind)
        self.lst = QListWidget()
        self.lst.currentRowChanged.connect(self._select)
        left.addWidget(self.lst, 1)
        row = QHBoxLayout()
        for lbl, fn in (("New", self._new), ("Duplicate", self._dup), ("Delete", self._del)):
            b = QPushButton(lbl); b.clicked.connect(fn); row.addWidget(b)
        left.addLayout(row)
        lay.addLayout(left, 0)

        self.editor_area = QScrollArea(); self.editor_area.setWidgetResizable(True)
        lay.addWidget(self.editor_area, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        outer = QVBoxLayout()
        wrap = QWidget(); wrap.setLayout(lay)
        outer_w = QWidget(); ol = QVBoxLayout(outer_w); ol.addWidget(wrap); ol.addWidget(bb)
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(outer_w)
        self._reload()

    def _kind(self):
        return self.cb_kind.currentData()

    def _reload(self):
        self.lst.clear()
        for p in self.libset[self._kind()].all():
            tag = f"  [{p.workflow}]" if p.kind == "machine" else ""
            it = QListWidgetItem(p.name + tag)
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            self.lst.addItem(it)
        if self.lst.count():
            self.lst.setCurrentRow(0)
        else:
            self.editor_area.setWidget(QWidget())

    def _current(self):
        it = self.lst.currentItem()
        if not it:
            return None
        return self.libset[self._kind()].get(it.data(Qt.ItemDataRole.UserRole))

    def _context(self, profile):
        # machine allowed_* multiselect needs names from the consumable libraries
        if profile.kind != "machine":
            return {}
        ctx = {}
        for kind in ("material", "nozzle", "tool"):
            ctx[kind] = [p.id for p in self.libset[kind].all()]
        return ctx

    def _select(self, row):
        p = self._current()
        if p is None:
            return
        params = schema(p.kind, p.workflow)
        values = p.resolved()
        editor = ParamEditor(params, values, context=self._context(p))
        editor.changed.connect(lambda vals, pr=p: pr.values.update(vals))
        self.editor_area.setWidget(editor)

    def _new(self):
        kind = self._kind()
        workflow = wf.FDM
        if kind == "machine":
            choices = [wf.label(w) for w in wf.ALL]
            sel, ok = QInputDialog.getItem(self, "New machine", "Workflow:", choices, 0, False)
            if not ok:
                return
            workflow = wf.ALL[choices.index(sel)]
        name, ok = QInputDialog.getText(self, f"New {kind}", "Name:")
        if not ok or not name.strip():
            return
        p = Profile(kind, name.strip(), workflow=workflow)
        self.libset[kind].add(p)
        self._reload()

    def _dup(self):
        p = self._current()
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Duplicate", "New name:", text=p.name + " copy")
        if not ok or not name.strip():
            return
        np_ = Profile(p.kind, name.strip(), values=dict(p.values), workflow=p.workflow)
        self.libset[p.kind].add(np_)
        self._reload()

    def _del(self):
        p = self._current()
        if p and QMessageBox.question(self, "Delete", f"Delete '{p.name}'?") == QMessageBox.StandardButton.Yes:
            lib = self.libset[p.kind]
            lib.remove(p.id)
            if lib.directory:
                f = Path(lib.directory) / f"{p.id}.json"
                if f.exists():
                    f.unlink()
            self._reload()
