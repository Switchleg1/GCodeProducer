"""GCodeProducer main window.

Layout follows GCodeTools:

* toolbar             import / slice / save, camera views
* left dock  Prepare  Setup (workflow, machine, consumables) -> Model -> Process
                      (load / save / edit the workflow options) -> Slice
* centre              3D viewer, vertical layer slider, position-in-layer slider
* right docks         View (colours, visibility, features, camera) and tabbed
                      G-code / Statistics / Log
"""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QFileDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                             QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSlider,
                             QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QToolButton, QVBoxLayout,
                             QWidget)

from .. import __version__
from ..core import defaults, plugins
from ..core import workflow as wf
from ..core.features import feature_color, feature_label
from ..core.geometry import Mesh
from ..core.pipeline import SlicePipeline
from ..core.process import ProcessPreset
from ..core.profiles import LibrarySet
from ..core.session import build_job, find_importer, load_mesh, slice_job
from ..core.toolpath import SOLID_KINDS, build_toolpath, format_duration
from .camera import Camera
from .library_dialog import LibraryDialog
from .process_editor import PipelineDialog, ProcessEditor
from .view_state import COLOR_MODES, ViewState
from .viewer import GCodeViewer
from .widgets import GCodeTextPanel, Worker, small_button

MODEL_FILTER = "Meshes (*.stl)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GCodeProducer {__version__}")
        self.resize(1600, 950)
        self.setAcceptDrops(True)
        self.settings = QSettings("GCodeProducer", os.environ.get("GCODEPRODUCER_SETTINGS", "GCodeProducer"))

        self.libset = LibrarySet().load()
        defaults.seed(self.libset)
        self.workflow = wf.FDM
        self.pipelines = {w: SlicePipeline.default(w) for w in wf.ALL}
        self.process_id = {w: None for w in wf.ALL}
        self.dirty = {w: False for w in wf.ALL}
        self.mesh = None
        self.model_path = None
        self.program = None
        self.tp = None
        self._fitted_for = None
        self._worker = None
        self._loading = False

        self.camera = Camera()
        self.state = ViewState()
        self._build_central()
        self._build_docks()
        self._build_toolbar()
        self._build_menu()
        self.status_line = QLabel("")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.statusBar().addWidget(self.status_line, 1)
        self.statusBar().addPermanentWidget(self.progress)
        for key, fn in (("PgUp", lambda: self.step_layer(1)), ("PgDown", lambda: self.step_layer(-1)),
                        ("Home", lambda: self.step_layer(-10 ** 6)), ("End", lambda: self.step_layer(10 ** 6))):
            QShortcut(QKeySequence(key), self, activated=fn)

        self._restore()
        for e in plugins.load_errors():
            self.log(f"Plugin load error: {e}")
        self._update_enabled()

    # ======================================================================
    # UI construction
    # ======================================================================
    def _build_central(self):
        self.viewer = GCodeViewer(self.camera, self.state, "")
        self.viewer.glError.connect(lambda m: (self.log(m), QMessageBox.critical(self, "OpenGL", m)))
        self.viewer.lineSelected.connect(self._on_viewer_pick)

        self.layer_slider = QSlider(Qt.Orientation.Vertical)
        self.layer_slider.setRange(0, 0)
        self.layer_slider.setToolTip("Top visible layer (PgUp / PgDn)")
        self.layer_slider.valueChanged.connect(self._on_layer_slider)
        self.layer_lbl = QLabel("-")
        self.layer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layer_lbl.setMinimumWidth(70)
        lv = QVBoxLayout()
        lv.addWidget(self.layer_lbl)
        lv.addWidget(self.layer_slider, 1, Qt.AlignmentFlag.AlignHCenter)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.viewer, 1)
        top.addLayout(lv)

        self.line_slider = QSlider(Qt.Orientation.Horizontal)
        self.line_slider.setToolTip("Position within the top layer")
        self.line_slider.valueChanged.connect(self._on_line_slider)
        self.single_layer = QCheckBox("Single layer")
        self.single_layer.toggled.connect(lambda _v: self._apply_layers())
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("In layer"))
        bottom.addWidget(self.line_slider, 1)
        bottom.addWidget(self.single_layer)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(4, 4, 4, 4)
        v.addLayout(top, 1)
        v.addLayout(bottom)
        self.setCentralWidget(central)

    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        # ---------------------------------------------------- prepare dock
        pw = QWidget()
        pl = QVBoxLayout(pw)

        setup = QGroupBox("Setup")
        self.setup_form = QFormLayout(setup)
        self.cb_workflow = QComboBox()
        for w in wf.ALL:
            self.cb_workflow.addItem(wf.label(w), w)
        self.cb_workflow.currentIndexChanged.connect(self._on_workflow)
        self.setup_form.addRow("Workflow", self.cb_workflow)
        self.cb_machine = QComboBox()
        self.cb_machine.currentIndexChanged.connect(self._on_machine)
        self.setup_form.addRow("Machine", self._with_edit(self.cb_machine, "machine"))
        self.cons_rows: dict = {}      # kind -> (label, row widget, combo)
        for kind in ("material", "nozzle", "tool"):
            cb = QComboBox()
            cb.currentIndexChanged.connect(lambda _i: self._save_selection())
            row = self._with_edit(cb, kind)
            lab = QLabel(kind.capitalize())
            self.setup_form.addRow(lab, row)
            self.cons_rows[kind] = (lab, row, cb)
        pl.addWidget(setup)

        model = QGroupBox("Model")
        ml = QHBoxLayout(model)
        self.lbl_model = QLabel("No model \u2014 import an STL or drop it on the window")
        self.lbl_model.setWordWrap(True)
        b_imp = QPushButton("Import\u2026")
        b_imp.clicked.connect(self.import_dialog)
        ml.addWidget(self.lbl_model, 1)
        ml.addWidget(b_imp)
        pl.addWidget(model)

        proc = QGroupBox("Process")
        prl = QVBoxLayout(proc)
        r1 = QHBoxLayout()
        self.cb_process = QComboBox()
        self.cb_process.setToolTip("Saved workflow options (layer height, walls, infill, adhesion\u2026)")
        self.cb_process.currentIndexChanged.connect(self._on_process_combo)
        r1.addWidget(self.cb_process, 1)
        self.lbl_dirty = QLabel("")
        self.lbl_dirty.setStyleSheet("color:#e0a030;font-weight:bold;")
        self.lbl_dirty.setToolTip("Unsaved changes")
        r1.addWidget(self.lbl_dirty)
        prl.addLayout(r1)
        r2 = QHBoxLayout()
        self.b_psave = QPushButton("Save")
        self.b_psave.setToolTip("Save changes to the selected process")
        self.b_psave.clicked.connect(lambda: self.process_save())
        b_psaveas = QPushButton("Save as\u2026")
        b_psaveas.clicked.connect(lambda: self.process_save_as())
        self.b_prevert = QPushButton("Revert")
        self.b_prevert.setToolTip("Discard unsaved changes")
        self.b_prevert.clicked.connect(self.process_revert)
        more = QToolButton()
        more.setText("More \u25be")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        mm = QMenu(more)
        mm.addAction("Import process\u2026", self.process_import)
        mm.addAction("Export process\u2026", self.process_export)
        mm.addSeparator()
        mm.addAction("Rename\u2026", self.process_rename)
        mm.addAction("Delete", self.process_delete)
        mm.addSeparator()
        mm.addAction("Edit pipeline stages\u2026", self.edit_pipeline)
        more.setMenu(mm)
        for b in (self.b_psave, b_psaveas, self.b_prevert):
            r2.addWidget(b)
        r2.addWidget(more)
        prl.addLayout(r2)
        self.process_editor = ProcessEditor()
        self.process_editor.changed.connect(self._mark_dirty)
        prl.addWidget(self.process_editor, 1)
        pl.addWidget(proc, 1)

        self.slice_btn = QPushButton("\u25b6  Slice")
        self.slice_btn.setMinimumHeight(34)
        self.slice_btn.setStyleSheet("font-weight:bold;")
        self.slice_btn.clicked.connect(self.run_slice)
        self.save_btn = QPushButton("Save G-code\u2026")
        self.save_btn.clicked.connect(self.save_gcode)
        rb = QHBoxLayout()
        rb.addWidget(self.slice_btn, 2)
        rb.addWidget(self.save_btn, 1)
        pl.addLayout(rb)
        self.dock_prepare = self._dock("Prepare", pw, Qt.DockWidgetArea.LeftDockWidgetArea, "dock_prepare")

        # ------------------------------------------------------- view dock
        vw = QWidget()
        vl = QVBoxLayout(vw)
        form = QFormLayout()
        self.color_combo = QComboBox()
        for k, lab in COLOR_MODES:
            if k in ("feature", "type", "speed", "layer"):
                self.color_combo.addItem(lab, k)
        self.color_combo.currentIndexChanged.connect(self._on_color_mode)
        form.addRow("Color by", self.color_combo)
        vl.addLayout(form)
        self.legend = QLabel("")
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("color:#9aa;")
        vl.addWidget(self.legend)
        show = QGroupBox("Show")
        sg = QVBoxLayout(show)
        for attr, lab, what in (("show_travel", "Travel / rapid moves", "colors"),
                                ("show_retracts", "Retraction points", "colors"),
                                ("show_tool", "Tool head", "view"), ("show_grid", "Grid", "view"),
                                ("dim_lower", "Dim layers below top", "view")):
            cb = QCheckBox(lab)
            cb.setChecked(getattr(self.state, attr))
            cb.toggled.connect(lambda val, a=attr, w=what: self.state.set(w, **{a: val}))
            sg.addWidget(cb)
        vl.addWidget(show)
        fbox = QGroupBox("Features (click to toggle)")
        fl = QVBoxLayout(fbox)
        self.feature_list = QListWidget()
        self.feature_list.itemChanged.connect(self._on_feature_toggled)
        fl.addWidget(self.feature_list)
        vl.addWidget(fbox, 1)
        cam = QGroupBox("Camera")
        cl = QVBoxLayout(cam)
        self.ortho_cb = QCheckBox("Orthographic")
        self.ortho_cb.toggled.connect(self._on_ortho)
        cl.addWidget(self.ortho_cb)
        ch = QHBoxLayout()
        for name in ("iso", "top", "front", "right"):
            b = QPushButton(name.capitalize())
            b.clicked.connect(lambda _=False, n=name: self.camera.set_view(n))
            ch.addWidget(b)
        bf = QPushButton("Fit")
        bf.clicked.connect(self.viewer.fit)
        ch.addWidget(bf)
        cl.addLayout(ch)
        vl.addWidget(cam)
        self.dock_view = self._dock("View", vw, Qt.DockWidgetArea.RightDockWidgetArea, "dock_view")

        # --------------------------------------- g-code / statistics / log
        self.text_panel = GCodeTextPanel()
        self.text_panel.lineClicked.connect(self._on_text_click)
        self.text_panel.lineActivated.connect(self._on_text_activate)
        self.dock_text = self._dock("G-code", self.text_panel, Qt.DockWidgetArea.RightDockWidgetArea, "dock_text")
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["", "Value"])
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.horizontalHeader().setStretchLastSection(True)
        self.dock_info = self._dock("Statistics", self.info_table, Qt.DockWidgetArea.RightDockWidgetArea, "dock_info")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.dock_log = self._dock("Log", self.log_view, Qt.DockWidgetArea.RightDockWidgetArea, "dock_log")
        self.tabifyDockWidget(self.dock_text, self.dock_info)
        self.tabifyDockWidget(self.dock_info, self.dock_log)
        self.dock_text.raise_()

    def _with_edit(self, combo, kind) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(combo, 1)
        b = small_button("\u270e", f"Edit {kind} library")
        b.clicked.connect(lambda _=False, k=kind, c=combo: self.edit_libraries(k, c.currentData()))
        h.addWidget(b)
        return w

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("toolbar_main")
        self.addToolBar(tb)
        self.act_import = self._act("Import model\u2026", self.import_dialog, QKeySequence.StandardKey.Open)
        self.act_slice = self._act("Slice", self.run_slice, "Ctrl+R")
        self.act_save = self._act("Save G-code\u2026", self.save_gcode, QKeySequence.StandardKey.Save)
        self.act_libs = self._act("Libraries\u2026", lambda: self.edit_libraries("machine"))
        for a in (self.act_import, self.act_slice, self.act_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_libs)
        tb.addSeparator()
        for name, key in (("Iso", "iso"), ("Top", "top"), ("Front", "front"), ("Right", "right")):
            tb.addAction(self._act(name, lambda _=False, k=key: self.camera.set_view(k)))
        tb.addAction(self._act("Fit", self.viewer.fit))

    def _act(self, text, slot, shortcut=None):
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        return a

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        m.addAction(self.act_import)
        self.recent_menu = m.addMenu("Recent models")
        m.addSeparator()
        m.addAction(self.act_save)
        m.addSeparator()
        m.addAction(self._act("Import process\u2026", self.process_import))
        m.addAction(self._act("Export process\u2026", self.process_export))
        m.addSeparator()
        m.addAction(self.act_libs)
        m.addSeparator()
        m.addAction(self._act("Exit", self.close, "Ctrl+Q"))
        p = self.menuBar().addMenu("&Process")
        p.addAction(self._act("Save", lambda: self.process_save()))
        p.addAction(self._act("Save as\u2026", lambda: self.process_save_as()))
        p.addAction(self._act("Revert", self.process_revert))
        p.addAction(self._act("Rename\u2026", self.process_rename))
        p.addAction(self._act("Delete", self.process_delete))
        p.addSeparator()
        p.addAction(self._act("Edit pipeline stages\u2026", self.edit_pipeline))
        v = self.menuBar().addMenu("&View")
        for d in (self.dock_prepare, self.dock_view, self.dock_text, self.dock_info, self.dock_log):
            v.addAction(d.toggleViewAction())
        h = self.menuBar().addMenu("&Help")
        h.addAction(self._act("Controls", self._show_help))
        h.addAction(self._act("About", lambda: QMessageBox.about(
            self, "GCodeProducer", f"GCodeProducer {__version__}\nSlicer / CAM: produces G-code from models.\n"
                                   "Licensed under the GNU GPL v3.")))

    # ======================================================================
    # persistence
    # ======================================================================
    def _restore(self):
        s = self.settings
        if s.value("geometry") is not None:
            self.restoreGeometry(s.value("geometry"))
        if s.value("windowState") is not None:
            self.restoreState(s.value("windowState"))
        else:
            QTimer.singleShot(0, lambda: self.resizeDocks([self.dock_prepare, self.dock_view],
                                                          [420, 330], Qt.Orientation.Horizontal))
        for w in wf.ALL:
            pid = s.value(f"process/{w}") or None
            if pid and pid in self.libset.processes.ids():
                self.process_id[w] = pid
            elif self.libset.processes.all(w):
                self.process_id[w] = self.libset.processes.all(w)[0].id
            self.pipelines[w] = self._preset_pipeline(w)
            work = s.value(f"working/{w}")          # unsaved edits survive a restart
            if work:
                try:
                    self.pipelines[w] = SlicePipeline.from_dict(json.loads(work)).ensure_defaults()
                    self.dirty[w] = True
                except Exception:
                    pass
        w = s.value("workflow") or wf.FDM
        self._loading = True
        self.cb_workflow.setCurrentIndex(max(0, self.cb_workflow.findData(w)))
        self._loading = False
        self._on_workflow()
        self._refresh_recent()

    def closeEvent(self, ev):
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        s.setValue("workflow", self.workflow)
        for w in wf.ALL:
            s.setValue(f"process/{w}", self.process_id[w] or "")
            s.setValue(f"working/{w}", json.dumps(self.pipelines[w].to_dict()) if self.dirty[w] else "")
        self._save_selection()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(ev)

    def _save_selection(self):
        if self._loading:
            return
        s = self.settings
        mid = self.cb_machine.currentData()
        if mid:
            s.setValue(f"machine/{self.workflow}", mid)
            for kind, (_l, _r, cb) in self.cons_rows.items():
                if cb.isVisibleTo(self) or cb.count():
                    if cb.currentData():
                        s.setValue(f"consumable/{mid}/{kind}", cb.currentData())

    def _refresh_recent(self):
        self.recent_menu.clear()
        for f in self._recent():
            self.recent_menu.addAction(self._act(f, lambda _=False, f=f: self.open_model(f)))
        self.recent_menu.setEnabled(bool(self._recent()))

    def _recent(self) -> list:
        r = self.settings.value("recent", [])
        if isinstance(r, str):
            r = [r]
        return [x for x in (r or []) if x]

    def _add_recent(self, path):
        r = [path] + [x for x in self._recent() if x != path]
        self.settings.setValue("recent", r[:10])
        self._refresh_recent()

    # ======================================================================
    # setup: workflow / machine / consumables
    # ======================================================================
    def _on_workflow(self, _i=0):
        if self._loading:
            return
        self.workflow = self.cb_workflow.currentData()
        self._reload_machines()
        self._reload_processes()
        self.process_editor.set_pipeline(self.pipelines[self.workflow])
        self._update_dirty()
        self._update_enabled()

    def _reload_machines(self, select: str | None = None):
        select = select or self.settings.value(f"machine/{self.workflow}") or None
        self._loading = True
        self.cb_machine.clear()
        for p in self.libset.machines.all(self.workflow):
            self.cb_machine.addItem(p.name, p.id)
        i = self.cb_machine.findData(select) if select else -1
        self.cb_machine.setCurrentIndex(max(0, i))
        self._loading = False
        self._on_machine()

    def _on_machine(self, _i=0):
        if self._loading:
            return
        machine = self._machine()
        kinds = [k for k in wf.LIBRARIES[self.workflow] if k != "machine"]
        self._loading = True
        for kind, (lab, row, cb) in self.cons_rows.items():
            show = kind in kinds
            self.setup_form.setRowVisible(row, show)
            cb.clear()
            if not show or machine is None:
                continue
            for p in self.libset.consumables_for(machine, kind):
                cb.addItem(p.name, p.id)
            if cb.count() == 0:
                cb.addItem(f"(no {kind} allowed on this machine)", None)
            last = self.settings.value(f"consumable/{machine.id}/{kind}")
            i = cb.findData(last) if last else -1
            cb.setCurrentIndex(max(0, i))
        self._loading = False
        self._save_selection()
        self._update_enabled()

    def _machine(self):
        mid = self.cb_machine.currentData()
        try:
            return self.libset.machines.get(mid) if mid else None
        except KeyError:
            return None

    def _consumable(self, kind):
        cb = self.cons_rows[kind][2]
        pid = cb.currentData()
        try:
            return self.libset[kind].get(pid) if pid else None
        except KeyError:
            return None

    def edit_libraries(self, kind="machine", profile_id=None):
        dlg = LibraryDialog(self.libset, self, kind, profile_id)
        if dlg.exec():
            self.libset.save()
        else:                                    # discard in-memory edits
            procs = self.libset.processes
            self.libset = LibrarySet(self.libset.root).load()
            self.libset.processes = procs
        self._reload_machines(self.cb_machine.currentData())

    # ======================================================================
    # process (workflow options)
    # ======================================================================
    def _preset_pipeline(self, w) -> SlicePipeline:
        pid = self.process_id[w]
        if pid:
            try:
                return self.libset.processes.get(pid).slice_pipeline()
            except KeyError:
                pass
        return SlicePipeline.default(w)

    def _reload_processes(self):
        self._loading = True
        self.cb_process.clear()
        for p in sorted(self.libset.processes.all(self.workflow), key=lambda p: p.name.lower()):
            self.cb_process.addItem(p.name, p.id)
        if self.cb_process.count() == 0:
            self.cb_process.addItem("(default \u2014 not saved)", None)
        i = self.cb_process.findData(self.process_id[self.workflow])
        self.cb_process.setCurrentIndex(max(0, i))
        self._loading = False
        self.process_id[self.workflow] = self.cb_process.currentData()

    def _on_process_combo(self, _i=0):
        if self._loading:
            return
        new = self.cb_process.currentData()
        if new == self.process_id[self.workflow]:
            return
        if not self._confirm_discard():
            self._loading = True
            self.cb_process.setCurrentIndex(max(0, self.cb_process.findData(self.process_id[self.workflow])))
            self._loading = False
            return
        self.select_process(new)

    def select_process(self, pid):
        """Load a saved process into the editor (discarding unsaved edits)."""
        self.process_id[self.workflow] = pid
        self.pipelines[self.workflow] = self._preset_pipeline(self.workflow)
        self.dirty[self.workflow] = False
        self._loading = True
        self.cb_process.setCurrentIndex(max(0, self.cb_process.findData(pid)))
        self._loading = False
        self.process_editor.set_pipeline(self.pipelines[self.workflow])
        self._update_dirty()

    def _confirm_discard(self) -> bool:
        if not self.dirty[self.workflow]:
            return True
        r = QMessageBox.question(
            self, "Unsaved process changes", "The current process has unsaved changes. Save them first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.process_save()
        return r == QMessageBox.StandardButton.Discard

    def _mark_dirty(self):
        self.dirty[self.workflow] = True
        self._update_dirty()

    def _update_dirty(self):
        d = self.dirty[self.workflow]
        self.lbl_dirty.setText("\u25cf modified" if d else "")
        self.b_prevert.setEnabled(d)

    def _current_preset(self):
        pid = self.process_id[self.workflow]
        try:
            return self.libset.processes.get(pid) if pid else None
        except KeyError:
            return None

    def process_save(self) -> bool:
        preset = self._current_preset()
        if preset is None:
            return self.process_save_as()
        preset.set_pipeline(self.pipelines[self.workflow])
        self.libset.processes.save_all()
        self.dirty[self.workflow] = False
        self._update_dirty()
        self.statusBar().showMessage(f"Saved process '{preset.name}'", 4000)
        return True

    def process_save_as(self, *, name: str | None = None) -> bool:
        if name is None:
            cur = self._current_preset()
            name, ok = QInputDialog.getText(self, "Save process as", "Name:",
                                            text=(cur.name + " copy") if cur else "")
            if not ok or not name.strip():
                return False
        preset = ProcessPreset(name.strip(), self.workflow, pipeline=self.pipelines[self.workflow].to_dict())
        self._add_preset(preset)
        return True

    def _add_preset(self, preset: ProcessPreset):
        base, n = preset.id, 2
        while preset.id in self.libset.processes.ids():
            preset.id = f"{base}-{n}"
            n += 1
        self.libset.processes.add(preset)
        self.libset.processes.save_all()
        self.process_id[self.workflow] = preset.id
        self.dirty[self.workflow] = False
        self._reload_processes()
        self._update_dirty()
        self.statusBar().showMessage(f"Saved process '{preset.name}'", 4000)

    def process_revert(self):
        self.select_process(self.process_id[self.workflow])

    def process_rename(self):
        preset = self._current_preset()
        if preset is None:
            return
        name, ok = QInputDialog.getText(self, "Rename process", "Name:", text=preset.name)
        if ok and name.strip():
            preset.name = name.strip()
            self.libset.processes.save_all()
            self._reload_processes()

    def process_delete(self):
        preset = self._current_preset()
        if preset is None:
            return
        if QMessageBox.question(self, "Delete process", f"Delete process '{preset.name}'?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.libset.processes.remove(preset.id)
        rest = self.libset.processes.all(self.workflow)
        self.process_id[self.workflow] = rest[0].id if rest else None
        self._reload_processes()
        self.select_process(self.process_id[self.workflow])

    def process_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import process", "", "Process (*.json)")
        if not path:
            return
        try:
            preset = ProcessPreset.import_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        if not self._confirm_discard():
            return
        if preset.workflow != self.workflow:
            self.cb_workflow.setCurrentIndex(self.cb_workflow.findData(preset.workflow))
        self._add_preset(preset)
        self.select_process(preset.id)
        self.log(f"Imported process '{preset.name}' from {path}")

    def process_export(self):
        cur = self._current_preset()
        name = cur.name if cur else "process"
        path, _ = QFileDialog.getSaveFileName(self, "Export process", f"{name}.json", "Process (*.json)")
        if path:
            ProcessPreset(name, self.workflow, pipeline=self.pipelines[self.workflow].to_dict()).export_file(path)
            self.statusBar().showMessage(f"Exported process to {path}", 4000)

    def edit_pipeline(self):
        dlg = PipelineDialog(self.pipelines[self.workflow], self)
        if dlg.exec():
            self.pipelines[self.workflow] = dlg.pipeline
            self.process_editor.set_pipeline(dlg.pipeline)
            self._mark_dirty()

    # ======================================================================
    # model
    # ======================================================================
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        urls = ev.mimeData().urls()
        if urls:
            self.open_model(urls[0].toLocalFile())

    def import_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import model", "", MODEL_FILTER)
        if path:
            self.open_model(path)

    def open_model(self, path: str):
        try:
            find_importer(path)
            mesh = load_mesh(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.mesh, self.model_path = mesh, path
        lo, hi = mesh.bounds
        sz = hi - lo
        self.lbl_model.setText(f"<b>{Path(path).name}</b><br>{sz[0]:.1f} \u00d7 {sz[1]:.1f} \u00d7 {sz[2]:.1f} mm, "
                               f"{len(mesh.triangles):,} triangles")
        self.lbl_model.setToolTip(path)
        self._add_recent(path)
        self.log(f"Loaded {path}")
        self._update_enabled()

    # ======================================================================
    # slicing
    # ======================================================================
    def _update_enabled(self):
        busy = self._worker is not None and self._worker.isRunning()
        ok = self.mesh is not None and self._machine() is not None and not busy
        self.slice_btn.setEnabled(ok)
        self.act_slice.setEnabled(ok)
        self.save_btn.setEnabled(self.program is not None and not busy)
        self.act_save.setEnabled(self.program is not None and not busy)

    def run_slice(self):
        if self.mesh is None:
            QMessageBox.information(self, "No model", "Import a model first.")
            return
        machine = self._machine()
        if machine is None:
            QMessageBox.information(self, "No machine", "Create a machine for this workflow (Libraries\u2026).")
            return
        kw = {}
        if self.workflow == wf.FDM:
            kw["material"] = self._consumable("material")
            kw["nozzle"] = self._consumable("nozzle")
        else:
            t = self._consumable("tool")
            kw["tools"] = [t] if t else []
        mesh = Mesh(self.mesh.vertices.copy(), self.mesh.triangles)   # stages may move the mesh
        try:
            job = build_job(self.workflow, machine, mesh=mesh, model_path=self.model_path, **kw)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot slice", str(exc))
            return
        pipe = copy.deepcopy(self.pipelines[self.workflow])
        self.log(f"Slicing {Path(self.model_path).name} ({wf.short(self.workflow)}, {machine.name}, "
                 f"process '{self.cb_process.currentText()}'{' *modified*' if self.dirty[self.workflow] else ''})")

        def task(worker, job=job, pipe=pipe):
            res = slice_job(job, pipe, log=worker.message.emit, progress=worker.progressed.emit)
            tp = build_toolpath(res.program) if res.program is not None else None
            return res, tp

        self._t0 = time.perf_counter()
        self._worker = Worker(task)
        self._worker.message.connect(self.log)
        self._worker.progressed.connect(lambda f: self.progress.setValue(int(f * 100)))
        self._worker.done.connect(self._slice_done)
        self._worker.failed.connect(self._slice_failed)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.statusBar().showMessage("Slicing\u2026")
        self._worker.start()
        self._update_enabled()

    def _slice_done(self, out):
        res, tp = out
        self.progress.setVisible(False)
        self._worker = None
        if res.program is None:
            self.log("The pipeline produced no G-code (is an output stage enabled?)")
            self._update_enabled()
            return
        self.program, self.tp = res.program, tp
        self.viewer.set_toolpath(tp)
        if self._fitted_for != self.model_path:
            self.viewer.fit()
            self._fitted_for = self.model_path
        self.text_panel.set_program(self.program)
        self._setup_layers()
        self._refresh_feature_list()
        self._update_stats()
        self._update_legend()
        self._update_enabled()
        dt = time.perf_counter() - self._t0
        self.statusBar().showMessage(f"Sliced in {dt:.1f}s \u2014 {self.program.num_layers} layers, "
                                     f"{len(self.program.lines):,} lines, "
                                     f"est. {format_duration(tp.stats.get('est_time_s', 0))}", 8000)

    def _slice_failed(self, tb):
        self.progress.setVisible(False)
        self._worker = None
        self.log(tb)
        self._update_enabled()
        QMessageBox.critical(self, "Slice failed", tb.strip().splitlines()[-1])

    def save_gcode(self):
        if self.program is None:
            return
        ext = ".gcode" if self.workflow == wf.FDM else ".nc"
        base = Path(self.model_path).with_suffix(ext) if self.model_path else Path("out" + ext)
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code", str(base), "G-code (*.gcode *.nc *.g *.tap)")
        if path:
            self.program.save(path)
            self.statusBar().showMessage(f"Saved {path}", 5000)
            self.log(f"Saved {path}")

    # ======================================================================
    # viewer: layers / cursor
    # ======================================================================
    def _setup_layers(self):
        nl = max(1, self.program.num_layers)
        self.layer_slider.blockSignals(True)
        self.layer_slider.setRange(0, nl - 1)
        self.layer_slider.setValue(nl - 1)
        self.layer_slider.blockSignals(False)
        self.state.layer_min, self.state.layer_max = 0, nl - 1
        self._apply_layers()

    def _on_layer_slider(self, v):
        self.state.layer_max = v
        self._apply_layers()

    def step_layer(self, d):
        if self.program is None:
            return
        self.layer_slider.setValue(max(0, min(self.layer_slider.maximum(), self.layer_slider.value() + d)))

    def _apply_layers(self):
        if self.program is None or self.tp is None:
            return
        st = self.state
        st.layer_min = st.layer_max if self.single_layer.isChecked() else 0
        z = self.program.layer_z[st.layer_max] if 0 <= st.layer_max < len(self.program.layer_z) else None
        self.layer_lbl.setText(f"{st.layer_max + 1} / {self.program.num_layers}" +
                               (f"\nZ {z:.2f}" if z is not None else ""))
        lo, hi = self.tp.layer_line_range(st.layer_max)
        if st.layer_max == self.layer_slider.maximum():
            hi = len(self.program.lines) - 1           # include the end G-code on the top layer
        self.line_slider.blockSignals(True)
        self.line_slider.setRange(lo, max(lo, hi))
        self.line_slider.setValue(max(lo, hi))
        self.line_slider.blockSignals(False)
        self.viewer.set_cursor(max(lo, hi))
        st.changed.emit("view")

    def _on_line_slider(self, v):
        self.viewer.set_cursor(v)
        self.text_panel.show_line(v)
        self._update_status(v)

    def _on_viewer_pick(self, line):
        self.text_panel.show_line(line)
        self._update_status(line)
        self.dock_text.raise_()

    def _on_text_click(self, line):
        self.viewer.set_selected(line)
        self._update_status(line)

    def _on_text_activate(self, line):
        if self.tp is None:
            return
        layer = int(self.tp.line_layer[line])
        self.layer_slider.setValue(layer)
        self.line_slider.setValue(line)

    def _update_status(self, line):
        if self.program is None or not (0 <= line < len(self.program.lines)):
            return
        ln = self.program.lines[line]
        x, y, z = self.tp.line_pos[line] if len(self.tp.line_pos) else (0, 0, 0)
        parts = [f"Line {line + 1}: {ln.text[:70]}", f"layer {ln.layer + 1}", feature_label(ln.feature),
                 f"X{x:.2f} Y{y:.2f} Z{z:.2f}"]
        f = ln.get("F")
        if f is not None:
            parts.append(f"F{f:g} ({f / 60:.1f} mm/s)")
        self.status_line.setText("   |   ".join(parts))

    def _on_ortho(self, v):
        self.camera.ortho = v
        self.camera.changed.emit()

    # ======================================================================
    # view panel
    # ======================================================================
    def _on_color_mode(self, _i):
        self.state.set("colors", color_mode=self.color_combo.currentData())
        self._update_legend()

    def _update_legend(self):
        mode = self.state.color_mode
        if mode == "speed" and self.tp is not None:
            lo, hi = self.state.feed_range(self.tp)
            if self.workflow == wf.CAM:
                self.legend.setText(f"Feed: blue = {lo:.0f} \u2026 red = {hi:.0f} mm/min")
            else:
                self.legend.setText(f"Speed: blue = {lo / 60:.0f} \u2026 red = {hi / 60:.0f} mm/s")
        elif mode == "layer":
            self.legend.setText("Layer: blue = first \u2026 red = last")
        else:
            self.legend.setText("")

    def _refresh_feature_list(self):
        tp = self.tp
        self.feature_list.blockSignals(True)
        self.feature_list.clear()
        if tp is not None:
            solid = np.isin(tp.kind, SOLID_KINDS)
            present = set(np.unique(tp.feature[solid]).tolist())
            for k, f in enumerate(tp.feature_names):
                if k not in present:
                    continue
                it = QListWidgetItem(feature_label(f))
                pm = QPixmap(14, 14)
                r, g, b = feature_color(f)
                pm.fill(QColor(int(r * 255), int(g * 255), int(b * 255)))
                it.setIcon(QIcon(pm))
                it.setData(Qt.ItemDataRole.UserRole, f)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked if f in self.state.hidden_features
                                 else Qt.CheckState.Checked)
                self.feature_list.addItem(it)
        self.feature_list.blockSignals(False)

    def _on_feature_toggled(self, it):
        f = it.data(Qt.ItemDataRole.UserRole)
        hidden = set(self.state.hidden_features)
        if it.checkState() == Qt.CheckState.Checked:
            hidden.discard(f)
        else:
            hidden.add(f)
        self.state.set("colors", hidden_features=hidden)

    def _update_stats(self):
        prog, tp = self.program, self.tp
        st = tp.stats
        rows = [("Workflow", wf.label(self.workflow)),
                ("Machine", self.cb_machine.currentText()),
                ("Process", self.cb_process.currentText() + (" (modified)" if self.dirty[self.workflow] else "")),
                ("Layers", str(st.get("layers", prog.num_layers))),
                ("Lines", f"{st.get('lines', len(prog.lines)):,}"),
                ("Est. time (no accel.)", format_duration(st.get("est_time_s", 0)))]
        if self.workflow == wf.FDM:
            mat = self._consumable("material")
            fil = self._filament_mm(prog)
            rows.append(("Filament", f"{fil / 1000:.2f} m"))
            if mat is not None:
                d = mat.get("filament_diameter", 1.75)
                grams = fil * np.pi * (d / 2) ** 2 / 1000.0 * mat.get("density", 1.24)
                rows.append(("Filament weight", f"{grams:.1f} g"))
            rows.append(("Retractions", f"{st.get('retractions', 0):,}"))
        rows += [("Print / cut length", f"{st.get('print_length_mm', 0) / 1000:.2f} m"),
                 ("Travel length", f"{st.get('travel_length_mm', 0) / 1000:.2f} m"),
                 ("Bounds min", ", ".join(f"{v:g}" for v in st.get("bounds_min", []))),
                 ("Bounds max", ", ".join(f"{v:g}" for v in st.get("bounds_max", [])))]
        self.info_table.setRowCount(len(rows))
        for r, (k, val) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(k))
            self.info_table.setItem(r, 1, QTableWidgetItem(val))
        self.info_table.resizeColumnsToContents()

    @staticmethod
    def _filament_mm(prog) -> float:
        from ..core.sim import simulate
        s = simulate(prog)
        return float(s.de[(s.de > 0) & s.moved].sum())

    # ======================================================================
    def log(self, msg: str):
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _show_help(self):
        QMessageBox.information(self, "Controls", (
            "Left drag: orbit    Right / middle drag: pan    Wheel: zoom\n"
            "Double-click: select the line under the cursor\n"
            "F / 1 2 3 4: fit / iso, top, front, right view\n"
            "PgUp / PgDn: next / previous layer    Home / End: first / last layer\n"
            "Ctrl+O import model    Ctrl+R slice    Ctrl+S save G-code"))
