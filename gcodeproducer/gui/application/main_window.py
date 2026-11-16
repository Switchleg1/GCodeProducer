"""GCodeProducer main window.

Layout follows GCodeTools:

* toolbar             import / slice / save, Prepare / Preview switch, camera views
* left dock  Prepare  Setup (workflow, machine, consumables) -> Model (placement,
                      support) -> Process (load / save / edit the workflow options) -> Slice
* centre              two views sharing one camera:
                      Prepare - the build plate with the model to place
                      Preview - the sliced tool path, layer slider, in-layer slider
* right docks         View (colours, visibility, features, camera) and tabbed
                      G-code / Statistics / Log
"""
from __future__ import annotations

from .application_constants import SHOW_OPTIONS, CAMERA_VIEW_KEYS, CAMERA_VIEWS, ROTATION_BUTTONS
from gcodeproducer.gui.application.application_constants import MODEL_FILTER
import copy, hashlib, json, os, time, numpy as np, gcodeproducer.core.settings.preferences as app_settings, gcodeproducer.core.libraries.defaults as defaults, gcodeproducer.core.plugins.discovery as plugins, gcodeproducer.core.workflows.validation as wf
from pathlib import Path
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from gcodeproducer import __version__
from gcodeproducer.core.gcode.gcode_constants import FEATURE_TOOLTIPS, SOLID_KINDS
from gcodeproducer.core.gcode.features import feature_color, feature_label
from gcodeproducer.core.geometry.mesh import Mesh
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from gcodeproducer.core.jobs.placement import Placement, bed_rect, bed_xy, fits
from gcodeproducer.core.libraries.process_preset import ProcessPreset
from gcodeproducer.core.fdm.model_support import ModelSupport
from gcodeproducer.core.fdm.support_block import SupportBlock
from gcodeproducer.core.fdm.support import (
    block_at as support_block_at,
    generate_blocks as support_generate,
)
from gcodeproducer.core.libraries.library_set import LibrarySet
from gcodeproducer.core.jobs.session import build_job, find_importer, load_mesh
from gcodeproducer.core.gcode.toolpath import format_duration
from gcodeproducer.gui.rendering.camera import Camera
from gcodeproducer.gui.dialogs.library_dialog import LibraryDialog
from gcodeproducer.gui.dialogs.settings_dialog import SettingsDialog
from gcodeproducer.gui.messages.messages_panel import MessagesPanel
from gcodeproducer.gui.messages.popup import show_message
from gcodeproducer.gui.rendering.model_viewer import ModelViewer
from gcodeproducer.gui.editors.pipeline_dialog import PipelineDialog
from gcodeproducer.gui.editors.process_editor import ProcessEditor
from gcodeproducer.gui.rendering.rendering_constants import COLOR_MODES
from gcodeproducer.gui.rendering.view_state import ViewState
from gcodeproducer.gui.rendering.gcode_viewer import GCodeViewer
from gcodeproducer.gui.runtime.compute_service import ComputeService
from gcodeproducer.gui.inspection.gcode_text_panel import GCodeTextPanel
from gcodeproducer.gui.editors.widgets import small_button


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"GCodeProducer {__version__}")
        self.resize(1600, 950)
        self.setAcceptDrops(True)
        self.settings = QSettings("GCodeProducer", os.environ.get("GCODEPRODUCER_SETTINGS", "GCodeProducer"))

        self.libset = LibrarySet().load()
        self.preferences = app_settings.load(self.libset.root)
        defaults.seed(self.libset)
        self.workflow = wf.FDM
        self.pipelines = {w: SlicePipeline.default(w) for w in wf.ALL}
        self.process_id = {w: None for w in wf.ALL}
        self.dirty = {w: False for w in wf.ALL}
        self.mesh = None
        self.model_path = None
        self.placement = Placement()
        self.placed = None              # placement applied to the mesh (what gets sliced)
        self._pl_prev = None            # last placement (to move support blocks with the model)
        self.blocks: list = []          # manual support blocks (belong to the model, like placement)
        self.model_support = ModelSupport()   # Model > Support (belongs to the model, not the process)
        self.sel_block = -1
        self._block_origin = None
        self.mode = "prepare"
        self.stale = False              # preview no longer matches model / settings
        self.program = None
        self.tp = None
        self._fitted_for = None
        self._loading = False
        self._worker = None             # id of the running slice task (None = idle)
        self._cam_pick_task = None
        self._cam_highlight_task = None
        self._cam_pick_operation = None
        self._blocks_task = None        # id of the running Auto-generate task
        self._filament_mm = 0.0
        self.cam_warnings = []
        self.material_results = []
        self.compute = ComputeService(self)  # slicing etc. run in a separate process
        self.compute.log.connect(self._on_compute_log)
        self.compute.progressed.connect(self._on_compute_progress)
        self.compute.done.connect(self._on_compute_done)
        self.compute.failed.connect(self._on_compute_failed)

        self._cam_highlight_timer = QTimer(self)
        self._cam_highlight_timer.setSingleShot(True)
        self._cam_highlight_timer.setInterval(180)
        self._cam_highlight_timer.timeout.connect(self._submit_cam_highlight)
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

    # UI construction
    def _build_central(self):
        # ---- mode switch (shared actions: toolbar, View menu, Ctrl+1 / Ctrl+2)
        self.act_prepare = QAction("Prepare", self)
        self.act_prepare.setToolTip("Place the model: position, rotation, scale, support (Ctrl+1)")
        self.act_prepare.setShortcut(QKeySequence("Ctrl+1"))
        self.act_preview = QAction("Preview", self)
        self.act_preview.setToolTip("The sliced tool path (Ctrl+2)")
        self.act_preview.setShortcut(QKeySequence("Ctrl+2"))
        grp = QActionGroup(self)
        for a, mode in ((self.act_prepare, "prepare"), (self.act_preview, "preview")):
            a.setCheckable(True)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, m=mode: self.set_mode(m))
        self.act_prepare.setChecked(True)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(0)
        for a in (self.act_prepare, self.act_preview):
            b = QToolButton()
            b.setDefaultAction(a)
            b.setObjectName("modeButton")
            b.setMinimumWidth(110)
            bar.addWidget(b)
        bar.addSpacing(12)
        self.stale_lbl = QLabel("")
        self.stale_lbl.setStyleSheet("color:#e0a030;")
        bar.addWidget(self.stale_lbl)
        bar.addStretch(1)

        # ---- prepare page: build plate + model
        self.model_viewer = ModelViewer(self.camera)
        self.state.changed.connect(self._on_view_state)
        self.model_viewer.glError.connect(lambda m: self.notify("opengl", "error", "OpenGL", m))
        self.model_viewer.moved.connect(self._on_model_dragged)
        self.model_viewer.moveFinished.connect(self._save_placement)
        self.model_viewer.faceClicked.connect(self._on_face_clicked)
        self.model_viewer.blockPressed.connect(self._on_block_pressed)
        self.model_viewer.blockDragged.connect(self._on_block_dragged)
        self.model_viewer.blockReleased.connect(self._on_block_released)
        self.model_viewer.blockDeleteRequested.connect(self.remove_block)
        self.model_viewer.placeBlockClicked.connect(self._on_place_block_click)
        self.model_viewer.placeModeExited.connect(self._end_block_tools)

        # ---- preview page: sliced tool path
        self.viewer = GCodeViewer(self.camera, self.state, "")
        self.viewer.glError.connect(lambda m: self.notify("opengl", "error", "OpenGL", m))
        self.viewer.lineSelected.connect(self._on_viewer_pick)

        self.layer_slider = QSlider(Qt.Orientation.Vertical)
        self.layer_slider.setRange(0, 0)
        self.layer_slider.setToolTip("Top visible layer (PgUp / PgDn)")
        self.layer_slider.valueChanged.connect(self._on_layer_slider)
        self.layer_lbl = QLabel("-")
        self.layer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layer_lbl.setFixedWidth(84)        # fixed: the view area must not change width
        lv = QVBoxLayout()
        lv.addWidget(self.layer_lbl)
        lv.addWidget(self.layer_slider, 1, Qt.AlignmentFlag.AlignHCenter)

        self.line_slider = QSlider(Qt.Orientation.Horizontal)
        self.line_slider.setToolTip("Position within the top layer")
        self.line_slider.valueChanged.connect(self._on_line_slider)
        self.single_layer = QCheckBox("Single layer")
        self.single_layer.toggled.connect(lambda _v: self._apply_layers())
        self.lbl_in_layer = QLabel("In layer")
        bottom = QHBoxLayout()
        bottom.addWidget(self.lbl_in_layer)
        bottom.addWidget(self.line_slider, 1)
        bottom.addWidget(self.single_layer)

        # both views share one area (and one camera): the layer controls sit outside
        # it, so Prepare and Preview have exactly the same size and framing; the
        # controls are disabled in Prepare
        self.stack = QStackedWidget()
        self.stack.addWidget(self.model_viewer)
        self.stack.addWidget(self.viewer)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.stack, 1)
        top.addLayout(lv)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(4, 4, 4, 4)
        v.addLayout(bar)
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
        # ------------------------------------------- model dock (setup, placement, support)
        mw = QWidget()
        pl = QVBoxLayout(mw)

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
            cb.currentIndexChanged.connect(lambda _i: (self._save_selection(), self._set_stale()))
            row = self._with_edit(cb, kind)
            lab = QLabel(kind.capitalize())
            self.setup_form.addRow(lab, row)
            self.cons_rows[kind] = (lab, row, cb)
        pl.addWidget(setup)

        pl.addWidget(self._build_model_box())
        # A single movable slot: FDM support / CAM material always stay together.
        self.model_options = QStackedWidget()
        self.model_options.addWidget(self._build_support_box())
        from gcodeproducer.gui.editors.stock_editor import StockEditor
        self.stock_editor = StockEditor()
        self.stock_editor.changed.connect(self._stock_changed)
        self.stock_editor.autoRequested.connect(self._auto_stock)
        self.model_options.addWidget(self.stock_editor)
        pl.addWidget(self.model_options)
        pl.addStretch(1)
        msc = QScrollArea()
        msc.setWidgetResizable(True)
        msc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        msc.setWidget(mw)
        self.dock_prepare = self._dock("Model", msc, Qt.DockWidgetArea.LeftDockWidgetArea, "dock_model")

        # ------------------------------------------------- process dock (settings + slice)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        proc = QGroupBox("Process")
        self.fdm_process_box = proc
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
        from gcodeproducer.gui.editors.cam_editor import CAMEditor
        self.cam_editor = CAMEditor()
        self.cam_editor.defaults = self.preferences
        self.stock_editor.set_stock(self.cam_editor.setup.stock)
        self.stock_editor.tabs.set_setup(self.cam_editor.setup)
        self.stock_editor.tabs.changed.connect(self._cam_changed)
        self.stock_editor.tabs.modeRequested.connect(self._cam_pick_mode)
        self.cam_editor.setVisible(False)
        self.cam_editor.changed.connect(self._cam_changed)
        self.cam_editor.selectionChanged.connect(self._cam_highlight)
        self.cam_editor.pickModeChanged.connect(self._cam_pick_mode)
        self.cam_editor.references.anchorChanged.connect(self.model_viewer.set_reference_anchor)
        # Ignore picks computed from an older outline list (especially deleted shapes).
        self.cam_editor.references.changed.connect(lambda: setattr(self, "_cam_pick_task", None))
        self.model_viewer.camPickRequested.connect(self._cam_pick)
        self.model_viewer.camSelectionExited.connect(self._cam_selection_exited)
        self.cam_scroll = QScrollArea()
        self.cam_scroll.setWidgetResizable(True)
        self.cam_scroll.setWidget(self.cam_editor)
        self.cam_scroll.setVisible(False)
        pl.addWidget(self.cam_scroll, 1)

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
        self.dock_process = self._dock("Process", pw, Qt.DockWidgetArea.LeftDockWidgetArea, "dock_process")
        self.splitDockWidget(self.dock_prepare, self.dock_process, Qt.Orientation.Vertical)

        # ------------------------------------------------------- view dock
        vw = QWidget()
        vl = QVBoxLayout(vw)
        form = QFormLayout()
        self.color_combo = QComboBox()
        for k, lab in COLOR_MODES:
            if k in ("feature", "type", "speed", "layer", "engagement"):
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
        for attr, lab, what in SHOW_OPTIONS:
            cb = QCheckBox(lab)
            cb.setChecked(getattr(self.state, attr))
            cb.toggled.connect(lambda val, a=attr, w=what: self.state.set(w, **{a: val}))
            sg.addWidget(cb)
            if attr=="show_material":self.show_material_cb=cb
        self.material_output = QComboBox()
        self.material_output.addItem("No calculated material output")
        self.material_output.setEnabled(False)
        self.material_output.currentIndexChanged.connect(self._on_material_output)
        sg.addWidget(QLabel("Calculated operation output"))
        sg.addWidget(self.material_output)
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
        for name in CAMERA_VIEW_KEYS:
            b = QPushButton(name.capitalize())
            b.clicked.connect(lambda _=False, n=name: self.camera.set_view(n))
            ch.addWidget(b)
        bf = QPushButton("Fit")
        bf.clicked.connect(self.fit_view)
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
        self.messages = MessagesPanel()
        self.dock_messages = self._dock("Messages", self.messages, Qt.DockWidgetArea.BottomDockWidgetArea, "dock_messages")

    def _build_model_box(self) -> QGroupBox:
        """Model: file, placement (position / rotation / scale) and support."""
        model = QGroupBox("Model")
        ml = QVBoxLayout(model)
        top = QHBoxLayout()
        self.lbl_model = QLabel("No model \u2014 import an STL or drop it on the window")
        self.lbl_model.setWordWrap(True)
        b_imp = QPushButton("Import\u2026")
        b_imp.clicked.connect(self.import_dialog)
        top.addWidget(self.lbl_model, 1)
        top.addWidget(b_imp, 0, Qt.AlignmentFlag.AlignTop)
        ml.addLayout(top)

        self.place_box = QWidget()
        g = QGridLayout(self.place_box)
        g.setContentsMargins(0, 2, 0, 0)
        g.setHorizontalSpacing(4)
        g.setVerticalSpacing(3)

        def spin(lo, hi, dec, suffix, step=1.0):
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setDecimals(dec)
            sb.setSuffix(suffix)
            sb.setSingleStep(step)
            sb.setKeyboardTracking(False)
            sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return sb

        # 4 columns: label | three equal fields; buttons get their own rows so a narrow
        # dock never clips them
        for c in (1, 2, 3):
            g.setColumnStretch(c, 1)

        def button(text, tip, slot, checkable=False):
            bt = QPushButton(text)
            bt.setToolTip(tip)
            bt.setCheckable(checkable)
            (bt.toggled if checkable else bt.clicked).connect(slot)
            bt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return bt

        # position: X / Y = centre on the bed, Z = height of the lowest point above the bed
        g.addWidget(QLabel("Position"), 0, 0)
        self.sp_x = spin(-5000, 5000, 2, "")
        self.sp_y = spin(-5000, 5000, 2, "")
        self.sp_z = spin(0, 5000, 2, "")
        for c, (sb, a, tip) in enumerate(((self.sp_x, "X", "Model centre X (mm)"),
                                          (self.sp_y, "Y", "Model centre Y (mm)"),
                                          (self.sp_z, "Z", "Height of the model's lowest point above the bed "
                                                           "(mm); above 0 the model floats and needs support "
                                                           "underneath")), start=1):
            sb.setPrefix(f"{a} ")
            sb.setToolTip(tip)
            sb.setMinimumWidth(60)
            g.addWidget(sb, 0, c)
        g.addWidget(button("Center", "Centre the model on the bed (X / Y)", self.center_model), 1, 1)
        self.b_drop = button("Drop to bed", "Put the model back on the bed (Z = 0)", self.drop_model)
        g.addWidget(self.b_drop, 1, 2)
        # rotation: value + rotate -90 / +90 about the world axis
        self.sp_rot = {}
        for r, axis in enumerate(("x", "y", "z"), start=2):
            g.addWidget(QLabel(f"Rotate {axis.upper()}"), r, 0)
            sb = spin(-360, 360, 1, "\u00b0", 5.0)
            sb.setWrapping(True)
            self.sp_rot[axis] = sb
            g.addWidget(sb, r, 1)
            for c, d in ROTATION_BUTTONS:
                arrow = "\u21ba" if d < 0 else "\u21bb"
                g.addWidget(button(f"{arrow} 90\u00b0", f"Rotate {d:+d}\u00b0 about the {axis.upper()} axis",
                                   lambda _=False, a=axis, dd=d: self.rotate_model(a, dd)), r, c)
        # scale
        g.addWidget(QLabel("Scale"), 5, 0)
        self.sp_scale = spin(0.1, 100000, 1, " %", 5.0)
        g.addWidget(self.sp_scale, 5, 1)
        self.lbl_size = QLabel("")
        self.lbl_size.setStyleSheet("color:#9aa;")
        g.addWidget(self.lbl_size, 5, 2, 1, 2)
        # orientation helpers
        g.addWidget(button("Lay flat", "Rest the largest flat face on the bed", self.lay_flat), 6, 1)
        self.b_face = button("Place on face", "Then click a face of the model in the Prepare view",
                             self._on_place_on_face, checkable=True)
        g.addWidget(self.b_face, 6, 2)
        g.addWidget(button("Reset", "Reset rotation, scale and Z and centre the model", self.reset_placement), 6, 3)
        for sb in (self.sp_x, self.sp_y, self.sp_z, self.sp_scale, *self.sp_rot.values()):
            sb.valueChanged.connect(self._on_placement_spin)
        ml.addWidget(self.place_box)

        self.place_box.setEnabled(False)
        return model

    def _build_support_box(self) -> QGroupBox:
        """Support: mode + overhang angle (process settings) and the manual support blocks."""
        box = QGroupBox("Support")
        self.support_box = box
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.cb_support = QComboBox()
        self.cb_support.addItem("None", "none")
        self.cb_support.addItem("Touching build plate", "buildplate")
        self.cb_support.addItem("Everywhere", "everywhere")
        self.cb_support.addItem("Manual blocks", "blocks")
        self.cb_support.setToolTip("Process setting (Support section). Manual blocks: support only inside "
                                   "the support blocks below")
        self.cb_support.currentIndexChanged.connect(self._on_support_combo)
        row.addWidget(self.cb_support, 1)
        self.sp_overhang = QDoubleSpinBox()
        self.sp_overhang.setRange(0, 89)
        self.sp_overhang.setDecimals(0)
        self.sp_overhang.setSuffix("\u00b0")
        self.sp_overhang.setToolTip("Overhang angle (from vertical) that needs support")
        self.sp_overhang.setKeyboardTracking(False)
        self.sp_overhang.valueChanged.connect(self._on_overhang_spin)
        row.addWidget(self.sp_overhang)
        self.cb_show_over = QCheckBox("Show")
        self.cb_show_over.setToolTip("Highlight overhangs that need support in red")
        self.cb_show_over.setChecked(True)
        self.cb_show_over.toggled.connect(lambda _v: self._update_scene())
        row.addWidget(self.cb_show_over)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Extend past edge"))
        self.sp_extend = QDoubleSpinBox()
        self.sp_extend.setRange(0, 20)
        self.sp_extend.setDecimals(2)
        self.sp_extend.setSingleStep(0.1)
        self.sp_extend.setSuffix(" mm")
        self.sp_extend.setKeyboardTracking(False)
        self.sp_extend.setToolTip("How far the support reaches past the model's edges (and into holes too large "
                                  "to fill) so the perimeters along every edge sit on support. 0 = stop at the "
                                  "edge. Process setting (Support section).")
        self.sp_extend.valueChanged.connect(self._on_extend_spin)
        row.addWidget(self.sp_extend)
        row.addSpacing(8)
        row.addWidget(QLabel("Fill holes \u2264"))
        self.sp_fill_holes = QDoubleSpinBox()
        self.sp_fill_holes.setRange(0, 100000)
        self.sp_fill_holes.setDecimals(0)
        self.sp_fill_holes.setSingleStep(10)
        self.sp_fill_holes.setSuffix(" mm\u00b2")
        self.sp_fill_holes.setSpecialValueText("off")
        self.sp_fill_holes.setKeyboardTracking(False)
        self.sp_fill_holes.setToolTip("Off: holes are edges like the outside of the model (support stops "
                                      "'Extend past edge' into them). Otherwise holes up to this area are "
                                      "treated as solid and supported right across. Process setting.")
        self.sp_fill_holes.valueChanged.connect(self._on_fill_holes_spin)
        row.addWidget(self.sp_fill_holes)
        row.addStretch(1)
        v.addLayout(row)

        # ---- manual support blocks
        self.blocks_box = QWidget()
        bl = QVBoxLayout(self.blocks_box)
        bl.setContentsMargins(0, 2, 0, 0)
        r1 = QHBoxLayout()
        b_gen = QPushButton("Auto-generate")
        self.b_gen_blocks = b_gen
        b_gen.setToolTip("Replace the blocks with automatic support, tiled with blocks of the Block size")
        b_gen.clicked.connect(lambda: self.generate_blocks())
        self.cb_gen_everywhere = QCheckBox("Allow on model")
        self.cb_gen_everywhere.setToolTip("Auto-generate support that may stand on the model "
                                          "(otherwise only from the build plate)")
        r1.addWidget(b_gen)
        r1.addWidget(self.cb_gen_everywhere)
        r1.addStretch(1)
        bl.addLayout(r1)
        # pick and place: click the model / bed to drop a block of this size there
        rp = QHBoxLayout()
        self.b_place_block = QPushButton("Place blocks")
        self.b_place_block.setCheckable(True)
        self.b_place_block.setToolTip("Click the bed or a surface of the model in the Prepare view to place a "
                                      "block that fills the gap up to the model above (Esc = done)")
        self.b_place_block.toggled.connect(self._on_place_block_mode)
        rp.addWidget(self.b_place_block, 1)
        self.b_remove_block = QPushButton("Remove blocks")
        self.b_remove_block.setCheckable(True)
        self.b_remove_block.setToolTip("Click support blocks in the Prepare view to delete them (Esc = done)")
        self.b_remove_block.toggled.connect(self._on_remove_block_mode)
        rp.addWidget(self.b_remove_block, 1)
        bl.addLayout(rp)
        rp = QHBoxLayout()
        rp.addWidget(QLabel("Block size"))
        self.sp_place_size = QDoubleSpinBox()
        self.sp_place_size.setRange(0.5, 500)
        self.sp_place_size.setDecimals(1)
        self.sp_place_size.setSingleStep(1.0)
        self.sp_place_size.setSuffix(" mm")
        self.sp_place_size.setToolTip("Width and depth of the blocks placed by clicking and of the tiles "
                                      "Auto-generate covers the support with")
        self.sp_place_size.setValue(float(self.settings.value("place_block_size", 5.0)))
        self.sp_place_size.valueChanged.connect(lambda v: self.settings.setValue("place_block_size", v))
        rp.addWidget(self.sp_place_size)
        rp.addStretch(1)
        bl.addLayout(rp)
        r2 = QHBoxLayout()
        for text, tip, fn in (("+ Add", "Add a block under the model", self.add_block),
                              ("Delete selected", "Delete the selected block (Delete key)", self.remove_block),
                              ("Clear", "Remove all blocks", self.clear_blocks)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            r2.addWidget(b)
        bl.addLayout(r2)
        self.lst_blocks = QListWidget()
        self.lst_blocks.setMaximumHeight(90)
        self.lst_blocks.currentRowChanged.connect(self._on_block_row)
        bl.addWidget(self.lst_blocks)
        self.block_edit = QWidget()
        ge = QGridLayout(self.block_edit)
        ge.setContentsMargins(0, 0, 0, 0)
        ge.setHorizontalSpacing(4)
        ge.addWidget(QLabel("Position"), 0, 0)
        ge.addWidget(QLabel("Size"), 1, 0)
        self.sp_block = {}
        tips = {"cx": "Block centre X", "cy": "Block centre Y", "z0": "Block bottom Z",
                "w": "Width (X)", "d": "Depth (Y)", "h": "Height (Z)"}
        for k, (key, label, lo) in enumerate((("cx", "X", -5000), ("cy", "Y", -5000), ("z0", "Z", 0),
                                              ("w", "W", 0.1), ("d", "D", 0.1), ("h", "H", 0.1))):
            sb = QDoubleSpinBox()
            sb.setRange(lo, 5000)
            sb.setDecimals(2)
            sb.setPrefix(f"{label} ")
            sb.setKeyboardTracking(False)
            sb.setToolTip(tips[key] + " (mm)")
            sb.valueChanged.connect(self._on_block_spin)
            self.sp_block[key] = sb
            ge.addWidget(sb, k // 3, 1 + k % 3)
        bl.addWidget(self.block_edit)
        self.lbl_blocks_hint = QLabel("")
        self.lbl_blocks_hint.setWordWrap(True)
        self.lbl_blocks_hint.setStyleSheet("color:#9aa;")
        bl.addWidget(self.lbl_blocks_hint)
        v.addWidget(self.blocks_box)
        return box

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
        self.act_settings = self._act("Settings\u2026", self.edit_settings, "Ctrl+,")
        for a in (self.act_import, self.act_slice, self.act_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_prepare)
        tb.addAction(self.act_preview)
        tb.addSeparator()
        tb.addAction(self.act_libs)
        tb.addSeparator()
        for name, key in CAMERA_VIEWS:
            tb.addAction(self._act(name, lambda _=False, k=key: self.camera.set_view(k)))
        tb.addAction(self._act("Fit", self.fit_view))

    def _act(self, text, slot, shortcut=None):
        a = QAction(text, self)
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        return a

    def edit_settings(self):
        dlg = SettingsDialog(self.preferences, self)
        if dlg.exec():
            new = dlg.result_values()
            changed = new != self.preferences
            self.preferences = new
            self.cam_editor.defaults = new
            try:
                app_settings.save(new, self.libset.root)
            except OSError as exc:
                self.notify("settings_save_failed", "error", "Settings", f"Could not save settings: {exc}")
            if changed and self.workflow == wf.CAM:
                self._set_stale()      # generated output depends on CAM preferences

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        m.addAction(self.act_import)
        self.recent_menu = m.addMenu("Recent models")
        m.addSeparator()
        m.addAction(self.act_save)
        m.addSeparator()
        self.act_process_import = self._act("Import process\u2026", self.process_import)
        self.act_process_export = self._act("Export process\u2026", self.process_export)
        m.addAction(self.act_process_import)
        m.addAction(self.act_process_export)
        m.addSeparator()
        m.addAction(self.act_libs)
        m.addAction(self.act_settings)
        m.addSeparator()
        m.addAction(self._act("Exit", self.close, "Ctrl+Q"))
        p = self.menuBar().addMenu("&Process")
        self.process_menu = p
        p.addAction(self._act("Save", lambda: self.process_save()))
        p.addAction(self._act("Save as\u2026", lambda: self.process_save_as()))
        p.addAction(self._act("Revert", self.process_revert))
        p.addAction(self._act("Rename\u2026", self.process_rename))
        p.addAction(self._act("Delete", self.process_delete))
        p.addSeparator()
        p.addAction(self._act("Edit pipeline stages\u2026", self.edit_pipeline))
        v = self.menuBar().addMenu("&View")
        v.addAction(self.act_prepare)
        v.addAction(self.act_preview)
        v.addSeparator()
        for d in (self.dock_prepare, self.dock_process, self.dock_view, self.dock_text, self.dock_info,
                  self.dock_log, self.dock_messages):
            v.addAction(d.toggleViewAction())
        h = self.menuBar().addMenu("&Help")
        h.addAction(self._act("Controls", self._show_help))
        h.addAction(self._act("About", lambda: QMessageBox.about(
            self, "GCodeProducer", f"GCodeProducer {__version__}\nSlicer / CAM: produces G-code from models.\n"
                                   "Licensed under the GNU GPL v3.")))

    # persistence
    def _restore(self):
        s = self.settings
        if s.value("geometry") is not None:
            self.restoreGeometry(s.value("geometry"))
        if s.value("windowState") is not None:
            self.restoreState(s.value("windowState"))
            if not s.value("messagesDockPlaced"):
                # Saved layouts predating the Messages dock: keep it at the bottom, a few lines tall.
                QTimer.singleShot(0, lambda: self.resizeDocks([self.dock_messages], [110], Qt.Orientation.Vertical))
        else:
            QTimer.singleShot(0, self._default_dock_sizes)
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

    def _default_dock_sizes(self):
        self.resizeDocks([self.dock_messages], [110], Qt.Orientation.Vertical)   # a few lines only
        self.resizeDocks([self.dock_prepare, self.dock_view], [430, 330], Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_prepare, self.dock_process], [430, 520], Qt.Orientation.Vertical)

    def closeEvent(self, ev):
        self._cam_highlight_timer.stop()
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        s.setValue("messagesDockPlaced", True)
        s.setValue("workflow", self.workflow)
        for w in wf.ALL:
            s.setValue(f"process/{w}", self.process_id[w] or "")
            s.setValue(f"working/{w}", json.dumps(self.pipelines[w].to_dict()) if self.dirty[w] else "")
        self._save_selection()
        self.compute.shutdown()
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

    # setup: workflow / machine / consumables
    def _on_workflow(self, _i=0):
        if self._loading:
            return
        if self.model_path:
            self._save_placement()
        self.workflow = self.cb_workflow.currentData()
        if self.material_results:self._reset_material_outputs()
        self.fdm_process_box.setVisible(self.workflow == wf.FDM)
        self.cam_editor.setVisible(self.workflow == wf.CAM)
        self.cam_scroll.setVisible(self.workflow == wf.CAM)
        self.show_material_cb.setEnabled(self.workflow == wf.CAM)
        ei = self.color_combo.findData("engagement")
        self.color_combo.model().item(ei).setEnabled(self.workflow == wf.CAM)
        if self.workflow != wf.CAM and self.color_combo.currentData() == "engagement":
            self.color_combo.setCurrentIndex(0)
        self._cam_pick_mode("")
        self.process_menu.setEnabled(self.workflow == wf.FDM)
        self.act_process_import.setEnabled(self.workflow == wf.FDM)
        self.act_process_export.setEnabled(self.workflow == wf.FDM)
        self.dock_process.setWindowTitle("CAM setup" if self.workflow == wf.CAM else "Process")
        self._reload_machines()
        if self.model_path:
            self.placement = self._load_workflow_placement(self.model_path)
            self._pl_prev = copy.deepcopy(self.placement)
            self._sync_placement_controls()
        self._reload_processes()
        self.process_editor.set_pipeline(self.pipelines[self.workflow])
        self._update_dirty()
        self._sync_support_controls()
        self._update_scene()
        self._set_stale()
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
            show = kind in kinds and kind != "tool"   # CAM tools belong to the tool-change tree
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
        self.cam_editor.set_tools(self.libset.consumables_for(machine, "tool")
                                  if machine is not None and self.workflow == wf.CAM else [])
        self._save_selection()
        self._update_scene()
        self._set_stale()
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

    # process (workflow options)
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
        self._set_stale()

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
        self._set_stale()

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
            self.notify("import_failed", "error", "Import failed", str(exc))
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

    # model
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
            self.notify("import_failed", "error", "Import failed", str(exc))
            return
        self._reset_material_outputs()
        self.mesh, self.model_path = mesh, path
        from gcodeproducer.core.cam.cam_setup import CAMSetup
        from gcodeproducer.core.cam.planning import fingerprint
        raw = self.settings.value(self._model_key("cam", path))
        try:
            setup = CAMSetup.from_dict(json.loads(raw)) if raw else CAMSetup()
        except (ValueError, KeyError, TypeError):
            setup = CAMSetup()
        current = fingerprint(mesh)
        if setup.fingerprint and setup.fingerprint != current:
            self.log("CAM geometry changed: cleared old operations to avoid stale geometry references")
            setup = CAMSetup()
        setup.fingerprint = current
        self.cam_editor.set_setup(setup)
        self.model_viewer.set_reference_geometry()
        self.stock_editor.set_stock(setup.stock)
        self.lbl_model.setText(f"<b>{Path(path).name}</b><br>{len(mesh.triangles):,} triangles")
        self.lbl_model.setToolTip(path)
        self.placement, self.blocks, self.model_support = self._load_model_state(path)
        self._pl_prev = copy.deepcopy(self.placement)
        self.sel_block = 0 if self.blocks else -1
        self._refresh_block_list(keep=True)
        self.b_face.setChecked(False)
        self.place_box.setEnabled(True)
        # a new model invalidates the old tool path
        self.program = self.tp = None
        self.viewer.set_toolpath(None)
        self.text_panel.set_program(None)
        self.feature_list.clear()
        self.stale = False
        self._sync_placement_controls()
        self._sync_support_controls()
        self._update_scene()
        self.set_mode("prepare")
        self.camera.set_view("iso")
        self.model_viewer.fit()
        self._add_recent(path)
        self.log(f"Loaded {path}")
        self._update_enabled()

    # ------------------------------------------------------------- placement
    def _auto_xy(self):
        return bed_xy(self._machine(), self.workflow) or (0.0, 0.0)

    def _model_key(self, kind, path) -> str:
        return f"{kind}/" + hashlib.md5(str(Path(path).resolve()).lower().encode()).hexdigest()

    def _load_model_state(self, path):
        """Remembered placement and support blocks of a model (or defaults)."""
        placement, blocks = None, []
        raw = self.settings.value(self._model_key("placement_cam" if self.workflow == wf.CAM else "placement", path))
        if raw:
            try:
                placement = Placement.from_dict(json.loads(raw))
            except Exception:
                placement = None
        if placement is None:
            x, y = self._auto_xy()
            placement = Placement(x=x, y=y, z_anchor="top" if self.workflow == wf.CAM else "bottom")
        if self.workflow == wf.CAM and placement.z_anchor != "top":
            placement.z_anchor, placement.z = "top", 0.0
        raw = self.settings.value(self._model_key("blocks", path))
        if raw:
            try:
                blocks = [SupportBlock.from_dict(d) for d in json.loads(raw)]
            except Exception:
                blocks = []
        model_support = ModelSupport()
        raw = self.settings.value(self._model_key("support", path))
        if raw:
            try:
                model_support = ModelSupport.from_dict(json.loads(raw))
            except Exception:
                model_support = ModelSupport()
        return placement, blocks, model_support

    def _load_workflow_placement(self, path):
        return self._load_model_state(path)[0]

    def _save_placement(self):
        if self.model_path:
            self.settings.setValue(self._model_key("placement_cam" if self.workflow == wf.CAM else "placement", self.model_path),
                                   json.dumps(self.placement.to_dict()))
            self.settings.setValue(self._model_key("blocks", self.model_path),
                                   json.dumps([b.to_dict() for b in self.blocks]))
            self.settings.setValue(self._model_key("support", self.model_path),
                                   json.dumps(self.model_support.to_dict()))

    def _sync_placement_controls(self):
        self.sp_z.blockSignals(True)
        self.sp_z.setMinimum(-5000 if self.workflow == wf.CAM else 0)
        self.sp_z.setToolTip("Model TOP Z; normally 0, with the part below the material surface" if self.workflow == wf.CAM
                             else "Height of the model's lowest point above the bed (mm)")
        self.sp_z.blockSignals(False)
        self.b_drop.setText("Top to Z0" if self.workflow == wf.CAM else "Drop to bed")
        pl = self.placement
        vals = ((self.sp_x, pl.x if pl.x is not None else self._auto_xy()[0]),
                (self.sp_y, pl.y if pl.y is not None else self._auto_xy()[1]),
                (self.sp_z, pl.z),
                (self.sp_rot["x"], pl.rx), (self.sp_rot["y"], pl.ry), (self.sp_rot["z"], pl.rz),
                (self.sp_scale, pl.scale))
        for sb, v in vals:
            sb.blockSignals(True)
            sb.setValue(v)
            sb.blockSignals(False)

    def _on_placement_spin(self, _v=0.0):
        pl = self.placement
        pl.x, pl.y, pl.z = self.sp_x.value(), self.sp_y.value(), self.sp_z.value()
        pl.rx, pl.ry, pl.rz = (self.sp_rot[a].value() for a in "xyz")
        pl.scale = self.sp_scale.value()
        self._placement_changed()

    def _follow_model(self):
        """Keep the support blocks attached to the model.

        Moving the model moves its blocks with it; rotating or scaling it makes
        them meaningless, so they are removed (re-run Auto-generate).
        """
        old, new = self._pl_prev, self.placement
        if old is not None and self.blocks:
            if (old.rx, old.ry, old.rz, old.scale) != (new.rx, new.ry, new.rz, new.scale):
                n = len(self.blocks)
                self.blocks, self.sel_block = [], -1
                self._refresh_block_list()
                self.statusBar().showMessage(
                    f"{n} support block(s) removed because the model was rotated / scaled "
                    f"\u2014 use Auto-generate to recreate them", 8000)
            else:
                dx = (new.x or 0.0) - (old.x or 0.0)
                dy = (new.y or 0.0) - (old.y or 0.0)
                dz = new.z - old.z
                if dx or dy or dz:
                    for blk in self.blocks:
                        blk.translate(dx, dy, dz)
                    self._refresh_block_list(keep=True)
        self._pl_prev = copy.deepcopy(new)

    def _placement_changed(self):
        self._follow_model()
        self._save_placement()
        self._update_scene()
        self._set_stale()
        if self.mode != "prepare":
            self.set_mode("prepare")

    def _on_model_dragged(self, x, y):
        self.placement.x, self.placement.y = round(x, 2), round(y, 2)
        self._follow_model()
        self._sync_placement_controls()
        self._update_scene()
        self._set_stale()

    def center_model(self):
        self.placement.x, self.placement.y = self._auto_xy()
        self._sync_placement_controls()
        self._placement_changed()

    def drop_model(self):
        self.placement.z = 0.0
        self._sync_placement_controls()
        self._placement_changed()

    def rotate_model(self, axis, degrees):
        self.placement.rotate_by(axis, degrees)
        self._sync_placement_controls()
        self._placement_changed()

    def lay_flat(self):
        if self.mesh is None:
            return
        self.placement.lay_flat(self.mesh)
        self._sync_placement_controls()
        self._placement_changed()

    def reset_placement(self):
        x, y = self._auto_xy()
        self.placement = Placement(x=x, y=y, z_anchor="top" if self.workflow == wf.CAM else "bottom")
        self._sync_placement_controls()
        self._placement_changed()

    def _on_place_on_face(self, on):
        if on and self.mode != "prepare":
            self.set_mode("prepare")
        if on:
            self.cam_editor.pick.setCurrentIndex(0)
            self._end_block_tools()
        self.model_viewer.set_place_on_face(on)

    def _on_face_clicked(self, normal):
        if normal is not None:
            self.placement.place_on_face(normal)
            self._sync_placement_controls()
            self._placement_changed()
        self.b_face.setChecked(False)

    def _support_step(self):
        """The process' support step (printing style only)."""
        return self.pipelines[self.workflow].step("fdm_support") if self.workflow == wf.FDM else None

    def _support_mode(self) -> str:
        return self.model_support.mode if self.workflow == wf.FDM else "none"

    def _update_scene(self):
        """Re-place the model and refresh the Prepare view (bed, overhangs, bounds, blocks)."""
        machine = self._machine()
        rect = bed_rect(machine, self.workflow) if machine is not None else (0, 0, 220, 220, 250)
        show_blocks = self._support_mode() == "blocks"
        self.model_viewer.set_blocks(self.blocks, self.sel_block, show_blocks)
        self.viewer.set_bed(rect)                     # Preview shows the same machine plate
        stock = self.cam_editor.setup.stock if self.workflow == wf.CAM else None
        self.model_viewer.set_stock(stock)
        self.viewer.set_stock(stock)
        if self.mesh is None:
            self.placed = None
            self.lbl_size.setText("")
            self.model_viewer.set_scene(None, rect, (0, 0))
            return
        self.placed = self.placement.apply(self.mesh, self._auto_xy())
        lo, hi = self.placed.bounds
        sz = hi - lo
        inside = fits(self.placed, rect)
        self.lbl_size.setText(f"{sz[0]:.1f} \u00d7 {sz[1]:.1f} \u00d7 {sz[2]:.1f} mm")
        self.lbl_size.setStyleSheet("color:#9aa;" if inside else "color:#f0a040;")
        angle = None
        if self.workflow == wf.FDM and self.cb_show_over.isChecked():
            angle = self.model_support.overhang_angle
        self.model_viewer.set_scene(self.placed, rect, (self.placement.x, self.placement.y), angle, inside)
        self._cam_pick_task = None
        self._cam_highlight()

    # --------------------------------------------------------------- CAM
    def _stock_changed(self):
        self._cam_changed()
        self._update_scene()

    def _auto_stock(self):
        if self.placed is None:
            return
        self.cam_editor.setup.stock.auto(self.placed)
        self.stock_editor.set_stock(self.cam_editor.setup.stock)
        self._stock_changed()

    def _cam_changed(self):
        self._cam_highlight()
        if self.model_path:
            self.settings.setValue(self._model_key("cam", self.model_path),
                                   json.dumps(self.cam_editor.setup.to_dict()))
        self._set_stale()

    def _cam_selection_exited(self):
        self.stock_editor.tabs.end_mode()
        self.cam_editor.references.end_mode()
        self.cam_editor.pick.setCurrentIndex(0)
        self.model_viewer.set_cam_mode("")

    def _cam_pick_mode(self, mode):
        self._cam_pick_task = None
        if not mode.startswith("draw_"):
            self.cam_editor.references.end_mode()
        else:
            self.cam_editor.pick.blockSignals(True)
            self.cam_editor.pick.setCurrentIndex(0)
            self.cam_editor.pick.blockSignals(False)
        if not mode.startswith("tab"):
            self.stock_editor.tabs.end_mode()
        else:
            self.cam_editor.pick.blockSignals(True)
            self.cam_editor.pick.setCurrentIndex(0)
            self.cam_editor.pick.blockSignals(False)
        if mode and self.workflow == wf.CAM:
            if mode.startswith("stock_") or (mode in ("face", "edge") and self.cam_editor.pick_source.currentData() == "both"):
                self.show_material_cb.setChecked(True)
            self.b_face.setChecked(False)
            self.b_place_block.setChecked(False)
            self.b_remove_block.setChecked(False)
            self.set_mode("prepare")
        self.model_viewer.set_cam_mode(mode if self.workflow == wf.CAM else "")

    def _cam_pick(self, payload):
        if self.workflow != wf.CAM or self._worker is not None:
            return
        if payload[0].startswith("draw_"):
            if self.placed is None:
                self.cam_editor.references.status.setText("Import a model before drawing reference geometry.")
            else:
                self.cam_editor.references.accept_ray(payload[1],payload[2])
            return
        if self.placed is None:
            return
        self._cam_pick_operation = self.cam_editor.operation()
        self._cam_pick_kind = payload[0]
        if payload[0].startswith("tab"):
            self._cam_pick_task = self.compute.submit("cam_tab_pick", (self.placed, copy.deepcopy(self.cam_editor.setup), *payload))
        else:
            if self.cam_editor.pick_source.currentData() == "both" and payload[0] in ("face", "edge"):
                payload = ("mixed_"+payload[0], *payload[1:])
            self._cam_pick_task = self.compute.submit("cam_pick", (self.placed, *payload,
                                                       copy.deepcopy(self.cam_editor.setup.stock),
                                                       copy.deepcopy(self.cam_editor.setup.reference_shapes)))

    def _cam_highlight(self):
        self.stock_editor.tabs.set_setup(self.cam_editor.setup)
        if self.workflow != wf.CAM or self.placed is None:
            self.model_viewer.set_reference_geometry()
        if self.workflow != wf.CAM:
            self.model_viewer.set_tab_bounds([])
            self.viewer.set_tab_bounds([])
        # Scalar rate calculation is cheap; do not leave locked rate fields stale
        # while a large topology task is running in the compute process.
        if self.workflow==wf.CAM:
            op=self.cam_editor.operation()
            gi,_=self.cam_editor.indices()
            tool=(next((t for t in self.cam_editor.tools if t.id==self.cam_editor.setup.groups[gi].tool_id),None)
                  if gi is not None else None)
            if op and tool and self._machine():
                from gcodeproducer.core.cam.cutting import resolve_cutting
                from dataclasses import asdict
                try:
                    data=resolve_cutting(self._machine(),tool,self.cam_editor.setup.stock,op)
                    self.cam_editor.cutting_summary.setText(data.summary())
                    self.cam_editor.set_calculated(asdict(data))
                except ValueError as exc:self.cam_editor.cutting_summary.setText(str(exc))
        self._cam_highlight_task = None
        self._cam_highlight_timer.stop()
        self.model_viewer.set_cam_selection()
        if self.workflow == wf.CAM and self.placed is not None:
            self._cam_highlight_timer.start()

    def _submit_cam_highlight(self):
        if self.workflow != wf.CAM or self.placed is None or self._worker is not None:
            return
        op = self.cam_editor.operation()
        context = None
        if op:
            gi,_=self.cam_editor.indices()
            tool=next((t for t in self.cam_editor.tools if t.id==self.cam_editor.setup.groups[gi].tool_id),None)
            context={"tool":tool,"machine":self._machine()} if tool and self._machine() else None
        self._cam_highlight_task = self.compute.submit("cam_highlight", (self.placed, copy.deepcopy(op),
            copy.deepcopy(self.cam_editor.setup.stock), copy.deepcopy(context), copy.deepcopy(self.cam_editor.setup.tabs),
            copy.deepcopy(self.cam_editor.setup.reference_shapes)))

    # --------------------------------------------------------------- support
    def _sync_support_controls(self):
        """Show the model's support settings (they belong to the model, not the process)."""
        ms = self.model_support
        self.model_options.setCurrentIndex(0 if self.workflow == wf.FDM else 1)
        self.support_box.setVisible(self.workflow == wf.FDM)
        self.stock_editor.setVisible(self.workflow == wf.CAM)
        self.stock_editor.auto.setEnabled(self.mesh is not None)
        self.cam_editor.references.setEnabled(self.mesh is not None)
        self.support_box.setEnabled(self.workflow == wf.FDM)
        widgets = (self.cb_support, self.sp_overhang, self.sp_extend, self.sp_fill_holes)
        for w in widgets:
            w.blockSignals(True)
        self.cb_support.setCurrentIndex(max(0, self.cb_support.findData(ms.mode)))
        self.sp_overhang.setValue(ms.overhang_angle)
        self.sp_extend.setValue(ms.extend)
        self.sp_fill_holes.setValue(ms.fill_holes)
        for w in widgets:
            w.blockSignals(False)
        self.blocks_box.setVisible(self._support_mode() == "blocks")
        if self._support_mode() != "blocks":
            self._end_block_tools()
        self._update_blocks_hint()

    def _support_changed(self):
        """Model > Support edited: model state only - the process is untouched."""
        self._save_placement()
        self._sync_support_controls()
        self._update_scene()
        self._set_stale()

    def _on_support_combo(self, _i=0):
        self.model_support.mode = self.cb_support.currentData()
        self._support_changed()

    def _on_fill_holes_spin(self, v):
        self.model_support.fill_holes = float(v)
        self._support_changed()

    def _on_extend_spin(self, v):
        self.model_support.extend = float(v)
        self._support_changed()

    def _on_overhang_spin(self, v):
        self.model_support.overhang_angle = float(v)
        self._support_changed()

    # ---------------------------------------------------------- support blocks
    def _blocks_changed(self, keep_row=True):
        self._refresh_block_list(keep=keep_row)
        self._save_placement()
        self._update_scene()
        self._set_stale()

    def _refresh_block_list(self, keep: bool = False):
        row = self.sel_block if keep else min(self.sel_block, len(self.blocks) - 1)
        self.lst_blocks.blockSignals(True)
        self.lst_blocks.clear()
        for k, blk in enumerate(self.blocks):
            w, d, h = blk.size
            cx, cy = blk.center
            self.lst_blocks.addItem(f"Block {k + 1}:  {w:.1f} \u00d7 {d:.1f} \u00d7 {h:.1f} mm  "
                                    f"at ({cx:.1f}, {cy:.1f}, Z{blk.z0:.1f})")
        self.sel_block = row if 0 <= row < len(self.blocks) else -1
        self.lst_blocks.setCurrentRow(self.sel_block)
        self.lst_blocks.blockSignals(False)
        self._sync_block_spins()
        self._update_blocks_hint()

    def _update_blocks_hint(self):
        if not hasattr(self, "lbl_blocks_hint"):
            return
        if not self.blocks:
            txt = "No blocks \u2014 click Auto-generate, or Place blocks and click under the model. " \
                  "Support is only generated inside blocks, where the model is above."
        else:
            txt = "Click a block in the view to select it, drag to move it, Delete or Remove blocks "                   "removes it."
        self.lbl_blocks_hint.setText(txt)

    def _sync_block_spins(self):
        blk = self.blocks[self.sel_block] if 0 <= self.sel_block < len(self.blocks) else None
        self.block_edit.setEnabled(blk is not None)
        if blk is None:
            return
        (cx, cy), (w, d, h) = blk.center, blk.size
        for key, val in (("cx", cx), ("cy", cy), ("z0", blk.z0), ("w", w), ("d", d), ("h", h)):
            sb = self.sp_block[key]
            sb.blockSignals(True)
            sb.setValue(val)
            sb.blockSignals(False)

    def _on_block_row(self, row):
        self.sel_block = row
        self._sync_block_spins()
        self.model_viewer.set_blocks(self.blocks, self.sel_block, self._support_mode() == "blocks")

    def _on_block_spin(self, _v=0.0):
        if not 0 <= self.sel_block < len(self.blocks):
            return
        g = {k: sb.value() for k, sb in self.sp_block.items()}
        self.blocks[self.sel_block].set_geometry(g["cx"], g["cy"], g["z0"], g["w"], g["d"], g["h"])
        self._blocks_changed()

    def _on_block_pressed(self, index):
        self.sel_block = index
        self._block_origin = copy.deepcopy(self.blocks[index])
        self._refresh_block_list(keep=True)
        self.model_viewer.set_blocks(self.blocks, self.sel_block, True)

    def _on_block_dragged(self, index, dx, dy):
        if not 0 <= index < len(self.blocks) or self._block_origin is None:
            return
        blk, org = self.blocks[index], self._block_origin
        blk.x0, blk.x1 = org.x0 + dx, org.x1 + dx
        blk.y0, blk.y1 = org.y0 + dy, org.y1 + dy
        self._sync_block_spins()
        self.model_viewer.set_blocks(self.blocks, self.sel_block, True)

    def _on_block_released(self, _index):
        self._block_origin = None
        self._blocks_changed()

    def generate_blocks(self, wait: bool = False):
        """Auto-generate: one block per island of automatic support, for the placed model."""
        if self.placed is None:
            self.notify("no_model", "warning", "No model", "Import a model first.")
            return
        pipe = self.pipelines[self.workflow]
        sl = plugins.stages.get("fdm_slice").resolve(pipe.step("fdm_slice").params if pipe.step("fdm_slice")
                                                     else {})
        sp = plugins.stages.get("fdm_support").resolve(self._support_step().params)
        lh = float(sl["layer_height"])
        flh = lh if sl["first_layer_height"] == "auto" else float(sl["first_layer_height"])
        noz = self._consumable("nozzle")
        lw = (noz.get("line_width", 0.45) if noz else 0.45) or 0.45
        if sp["line_width"] != "auto":
            lw = float(sp["line_width"])
        ms = self.model_support
        kwargs = dict(mesh=self.placed, layer_height=lh, line_width=lw, angle=ms.overhang_angle,
                      everywhere=self.cb_gen_everywhere.isChecked(), xy_distance=sp["xy_distance"],
                      gap=sp["z_gap_layers"], bottom_gap=sp["bottom_z_gap_layers"], min_area=sp["min_area"],
                      first_layer_height=flh, block_size=self.sp_place_size.value(),
                      fill_holes=ms.fill_holes, edge_margin=ms.extend)
        if wait:                                      # synchronous (tests / scripting)
            self._blocks_done(support_generate(**kwargs))
            return
        if self._blocks_task is not None:
            return
        self._blocks_task = self.compute.submit("blocks", kwargs)
        self._update_blocks_busy()
        self.statusBar().showMessage("Generating support blocks\u2026")

    def _update_blocks_busy(self):
        busy = self._blocks_task is not None
        self.b_gen_blocks.setEnabled(not busy)
        self.b_gen_blocks.setText("Generating\u2026" if busy else "Auto-generate")

    def _blocks_done(self, blocks):
        self._blocks_task = None
        self._update_blocks_busy()
        self.blocks = blocks
        self.sel_block = 0 if blocks else -1
        self._blocks_changed(keep_row=True)
        msg = (f"Generated {len(blocks)} support block(s) of {self.sp_place_size.value():g} mm"
               if blocks else "No support needed \u2014 no blocks")
        self.statusBar().showMessage(msg, 6000)
        self.log(msg)

    def _on_place_block_mode(self, on):
        if on:
            if self.mode != "prepare":
                self.set_mode("prepare")
            self.b_face.setChecked(False)
            self.b_remove_block.setChecked(False)       # the two block tools are exclusive
        self.model_viewer.set_place_block(on)

    def _on_remove_block_mode(self, on):
        if on:
            if self.mode != "prepare":
                self.set_mode("prepare")
            self.b_face.setChecked(False)
            self.b_place_block.setChecked(False)
        self.model_viewer.set_remove_block(on)

    def _end_block_tools(self):
        self.b_place_block.setChecked(False)
        self.b_remove_block.setChecked(False)

    def _on_place_block_click(self, x, y, z, facing_down):
        """A click in place-blocks mode: fill the vertical gap at that point with a block."""
        if self.placed is None:
            return
        blk = support_block_at(self.placed, x, y, z, self.sp_place_size.value(), facing_down=facing_down)
        if blk is None:
            what = "below" if facing_down else "above"
            self.statusBar().showMessage(f"Nothing of the model {what} that point \u2014 no block placed", 4000)
            return
        self.blocks.append(blk)
        self.sel_block = len(self.blocks) - 1
        self._blocks_changed()
        self.statusBar().showMessage(f"Block {len(self.blocks)}: Z {blk.z0:.2f} \u2192 {blk.z1:.2f} mm", 4000)

    def add_block(self):
        if self.placed is None:
            return
        lo, hi = self.placed.bounds
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        self.blocks.append(SupportBlock(cx - 5, cy - 5, 0.0, cx + 5, cy + 5, float(hi[2])))
        self.sel_block = len(self.blocks) - 1
        self._blocks_changed()

    def remove_block(self, index=None):
        i = self.sel_block if index is None or isinstance(index, bool) else index
        if 0 <= i < len(self.blocks):
            del self.blocks[i]
            self.sel_block = min(i, len(self.blocks) - 1)
            self._blocks_changed()

    def clear_blocks(self):
        self.blocks, self.sel_block = [], -1
        self._blocks_changed()

    # ----------------------------------------------------------------- views
    def set_mode(self, mode: str):
        if mode == "preview" and self.program is None:
            mode = "prepare"
        self.mode = mode
        self.stack.setCurrentIndex(0 if mode == "prepare" else 1)
        for w in (self.layer_slider, self.layer_lbl, self.line_slider, self.single_layer, self.lbl_in_layer):
            w.setEnabled(mode == "preview")
        (self.act_prepare if mode == "prepare" else self.act_preview).setChecked(True)
        if mode == "preview" and self.b_face.isChecked():
            self.b_face.setChecked(False)
        if mode == "preview":
            self._end_block_tools()
        self._update_stale_label()

    def fit_view(self):
        (self.model_viewer if self.mode == "prepare" else self.viewer).fit()

    def _reset_material_outputs(self):
        self.material_results=[]
        self.material_output.blockSignals(True)
        self.material_output.clear()
        self.material_output.addItem("No calculated material output")
        self.material_output.setEnabled(False)
        self.material_output.blockSignals(False)
        self.viewer.set_material_surface(None)
        self.viewer.set_info("")
        self.layer_slider.setEnabled(True);self.line_slider.setEnabled(True)

    def _on_view_state(self,_what):
        self.model_viewer.show_material=self.state.show_material
        self.model_viewer.update()

    def _on_material_output(self,index):
        if not 0<=index<len(self.material_results):
            self.viewer.set_material_surface(None)
            return
        result=self.material_results[index]
        self.viewer.set_material_surface(result["positions"])
        last=result["last_layer"]
        if self.program is not None:
            self.set_mode("preview")
            if last<0:
                # -1 means unlimited to the GL shader, not an empty range.
                self.state.set("view",layer_min=1,layer_max=0)
                self.layer_slider.setEnabled(False);self.line_slider.setEnabled(False)
                self.layer_lbl.setText("Initial stock")
                self.viewer.set_cursor(-1)
                self.viewer.set_selected(-1)
            else:
                self.layer_slider.setEnabled(True);self.line_slider.setEnabled(True)
                self.layer_slider.setValue(last)
                self._on_layer_slider(last)
        self.viewer.set_info(f"{result['label']} • calculated material grid {result['resolution']:.3f} mm")

    def _set_stale(self):
        if self.workflow==wf.CAM and self.material_results:self._reset_material_outputs()
        if self.program is not None and not self.stale:
            self.stale = True
            self._update_stale_label()

    def _update_stale_label(self):
        if self.program is not None and self.stale:
            self.stale_lbl.setText("\u26a0 Preview is out of date \u2014 press Slice")
        elif self.program is None and self.mesh is not None:
            self.stale_lbl.setText("Press Slice (Ctrl+R) to generate the tool path")
        else:
            self.stale_lbl.setText("")

    # slicing
    def _update_enabled(self):
        busy = self._worker is not None
        ok = self.mesh is not None and self._machine() is not None
        # while slicing the Slice button cancels
        self.slice_btn.setEnabled(ok or busy)
        self.slice_btn.setText("\u25a0  Cancel" if busy else
                               ("\u25b6  Generate paths" if self.workflow == wf.CAM else "\u25b6  Slice"))
        self.slice_btn.setToolTip("Stop generation" if busy else "Generate toolpaths (Ctrl+R)")
        self.act_slice.setEnabled(ok and not busy)
        self.cam_editor.setEnabled(not busy)
        self.cb_workflow.setEnabled(not busy)
        self.cb_machine.setEnabled(not busy)
        self.stock_editor.setEnabled(not busy)
        self.save_btn.setEnabled(self.program is not None and not busy)
        self.act_save.setEnabled(self.program is not None and not busy)
        self.act_preview.setEnabled(self.program is not None)
        self._update_stale_label()

    def run_slice(self):
        if self._worker is not None:             # the button reads 'Cancel' while slicing
            self.cancel_slice()
            return
        if self.mesh is None:
            self.notify("no_model", "warning", "No model", "Import a model first.")
            return
        machine = self._machine()
        if machine is None:
            self.notify("no_machine", "warning", "No machine", "Create a machine for this workflow (Libraries\u2026).")
            return
        kw = {}
        if self.workflow == wf.FDM:
            kw["material"] = self._consumable("material")
            kw["nozzle"] = self._consumable("nozzle")
        else:
            kw["tools"] = self.libset.consumables_for(machine, "tool")
            kw["cam_setup"] = copy.deepcopy(self.cam_editor.setup)
        mesh = Mesh(self.mesh.vertices.copy(), self.mesh.triangles)   # stages may move the mesh
        placed = self.placement.apply(mesh, self._auto_xy())
        if not fits(placed, bed_rect(machine, self.workflow)):
            if not self.notify("outside_volume", "warning", "Outside the build volume",
                               "The model does not fit inside the machine's build volume.\nSlice anyway?",
                               question=True):
                return
        try:
            job = build_job(self.workflow, machine, mesh=mesh, model_path=self.model_path,
                            placement=copy.deepcopy(self.placement),
                            support_blocks=copy.deepcopy(self.blocks),
                            support=copy.deepcopy(self.model_support) if self.workflow == wf.FDM else None,
                            preferences=dict(self.preferences), **kw)
        except ValueError as exc:
            self.notify("cannot_slice", "error", "Cannot slice", str(exc))
            return
        pipe = (SlicePipeline.default(wf.CAM) if self.workflow == wf.CAM
                else copy.deepcopy(self.pipelines[self.workflow]))
        detail = (f"{len(self.cam_editor.setup.groups)} tool-change groups" if self.workflow == wf.CAM
                  else f"process '{self.cb_process.currentText()}'{' *modified*' if self.dirty[self.workflow] else ''}")
        self.log(f"Slicing {Path(self.model_path).name} ({wf.short(self.workflow)}, {machine.name}, {detail})")
        self._t0 = time.perf_counter()
        self._worker = self.compute.submit("slice", (job, pipe))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.statusBar().showMessage("Slicing\u2026")
        self._update_enabled()

    def cancel_slice(self):
        if self._worker is None:
            return
        self._worker = None
        self._blocks_task = None
        self.compute.cancel()
        self.progress.setVisible(False)
        self.statusBar().showMessage("Slicing cancelled", 4000)
        self.log("Slicing cancelled")
        self._update_enabled()
        self._update_blocks_busy()

    # ---------------------------------------------------- compute messages
    def _on_compute_log(self, tid, msg):
        if tid in (self._worker, self._blocks_task):
            self.log(msg)

    def _on_compute_progress(self, tid, f):
        if tid == self._worker:
            self.progress.setValue(int(f * 100))

    def _on_compute_done(self, tid, result):
        if tid == self._cam_pick_task:
            self._cam_pick_task = None
            if self.workflow == wf.CAM:
                if getattr(self, "_cam_pick_kind", "").startswith("tab"):
                    self.stock_editor.tabs.accept_pick(result)
                elif self.cam_editor.operation() is self._cam_pick_operation:
                    self.cam_editor.accept_pick(result)
            return
        if tid == self._cam_highlight_task:
            self._cam_highlight_task = None
            if self.workflow == wf.CAM:
                self.model_viewer.set_cam_selection(result['faces'], result['edges'], result.get('stock_faces', []),
                                                    result.get('stock_edges', []), result.get('reference_edges', []))
                self.model_viewer.set_reference_geometry(result.get('reference_geometry', []))
                self.model_viewer.set_tab_bounds(result.get('tabs', []))
                self.viewer.set_tab_bounds(result.get('tabs', []))
                if result.get('tab_error'):
                    self.stock_editor.tabs.status.setText(result['tab_error'])
                else:
                    self.stock_editor.tabs.status.setText(f"{len(result.get('tabs', []))} enabled holding tabs. "
                        "Height is measured from stock bottom; use Place tabs and click side walls to add more.")
                self.cam_editor.depth_summary.setText(result['depths'])
                self.cam_editor.cutting_summary.setText(result.get('cutting',''))
                self.cam_editor.set_calculated(result.get('cutting_values',{}))
            return
        if tid == self._worker:
            self._slice_done(result)
        elif tid == self._blocks_task:
            self._blocks_done(result)

    def _on_compute_failed(self, tid, tb):
        if tid in (self._cam_pick_task, self._cam_highlight_task):
            self._cam_pick_task = self._cam_highlight_task = None
            self.log(tb)
            self.statusBar().showMessage("CAM selection failed; see log", 5000)
            return
        if tid == self._worker:
            self._slice_failed(tb)
        elif tid == self._blocks_task:
            self._blocks_task = None
            self._update_blocks_busy()
            self.log(tb)
            self.notify("auto_generate_failed", "error", "Auto-generate failed", tb.strip().splitlines()[-1])

    def _slice_done(self, out):
        self.progress.setVisible(False)
        self._worker = None
        if out["program"] is None:
            self.log("The pipeline produced no G-code (is an output stage enabled?)")
            self._update_enabled()
            return
        self.cam_warnings = out.get("warnings", [])
        self.model_viewer.set_tab_bounds(out.get("tab_bounds", []))
        self.viewer.set_tab_bounds(out.get("tab_bounds", []))
        self.program, self.tp = out["program"], out["toolpath"]
        self._filament_mm = out["filament_mm"]
        # a big program is ~1M Python objects; Python's periodic full garbage collection
        # would scan them all (~0.2 s UI pauses). Freeze them out of the collector - they
        # hold no reference cycles, so they are still freed when the next slice replaces them.
        import gc
        gc.freeze()
        tp = self.tp
        self.viewer.set_toolpath(tp)            # camera unchanged: same view as Prepare
        self.text_panel.set_program(self.program)
        self.stale = False
        self.set_mode("preview")
        self._setup_layers()
        self.material_results=out.get("material_results",[])
        self.material_output.blockSignals(True)
        self.material_output.clear()
        for result in self.material_results:self.material_output.addItem(result["label"])
        if not self.material_results:self.material_output.addItem("No calculated material output")
        self.material_output.setCurrentIndex(max(0,len(self.material_results)-1))
        self.material_output.setEnabled(bool(self.material_results))
        self.material_output.blockSignals(False)
        self._on_material_output(self.material_output.currentIndex())
        self._refresh_feature_list()
        self._update_stats()
        self._update_legend()
        self._update_enabled()
        dt = time.perf_counter() - self._t0
        self.statusBar().showMessage(f"Sliced in {dt:.1f}s \u2014 {self.program.num_layers} layers, "
                                     f"{len(self.program.lines):,} lines, "
                                     f"est. {format_duration(tp.stats.get('est_time_s', 0))}", 8000)

        for warning in self.cam_warnings:
            self.messages.add("warning", warning, "CAM")
        if self.cam_warnings:
            self.notify("cam_warnings", "warning", "CAM material / engagement warnings",
                                "\n".join(self.cam_warnings[:15]) +
                                "\n\nFlagged moves are coloured Conflict / Collision in Feature colour mode. Review the toolpath and full log before machining; these checks are approximate 2.5D, not a full collision simulation.",
                        record=False)

    def _slice_failed(self, tb):
        self.progress.setVisible(False)
        self._worker = None
        self._update_enabled()
        self.log(tb)
        self._update_enabled()
        self.notify("slice_failed", "error", "Slice failed", tb.strip().splitlines()[-1])

    def save_gcode(self):
        if self.program is None:
            return
        if self.workflow == wf.CAM and self.stale:
            self.notify("cam_stale_export", "warning", "Regenerate CAM paths",
                        "The model, material or setup has changed. Regenerate paths to run stock checks before exporting.")
            return
        if self.workflow == wf.CAM and self.cam_warnings:
            if QMessageBox.question(self, "Export with CAM warnings?",
                                    "CAM material/engagement warnings remain. Export anyway?") != QMessageBox.StandardButton.Yes:
                return
        ext = ".gcode" if self.workflow == wf.FDM else ".nc"
        base = Path(self.model_path).with_suffix(ext) if self.model_path else Path("out" + ext)
        path, _ = QFileDialog.getSaveFileName(self, "Save G-code", str(base), "G-code (*.gcode *.nc *.g *.tap)")
        if path:
            self.program.save(path)
            self.statusBar().showMessage(f"Saved {path}", 5000)
            self.log(f"Saved {path}")

    # viewer: layers / cursor
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

    # view panel
    def _on_color_mode(self, _i):
        if self.color_combo.currentData() is None:
            return
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
        elif mode == "engagement" and self.workflow == wf.CAM:
            self.legend.setText("Estimated radial engagement: blue = 0%, red = 100%. Full slots are hand-neutral.")
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
                if f in FEATURE_TOOLTIPS:
                    it.setToolTip(FEATURE_TOOLTIPS[f])
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
                (("CAM setup", f"{len(self.cam_editor.setup.groups)} tool changes, "
                  f"{sum(len(g.operations) for g in self.cam_editor.setup.groups)} operations")
                 if self.workflow == wf.CAM else
                 ("Process", self.cb_process.currentText() + (" (modified)" if self.dirty[self.workflow] else ""))),
                ("Layers", str(st.get("layers", prog.num_layers))),
                ("Lines", f"{st.get('lines', len(prog.lines)):,}"),
                ("Est. time (no accel.)", format_duration(st.get("est_time_s", 0)))]
        if self.workflow == wf.FDM:
            mat = self._consumable("material")
            fil = self._filament_mm
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

    def log(self, msg: str):
        self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")
        text = str(msg)
        # Pipeline/compute warnings arrive as log lines ("STOCK WARNING: ...", "LEAD WARNING: ...").
        # CAM job warnings are added once from the result instead, so skip those prefixes here.
        if "WARNING:" in text and hasattr(self, "messages"):
            head, _, body = text.strip().partition("WARNING:")
            if head.strip() not in ("STOCK", "ENGAGEMENT", "REACH", "TOOL", "LEAD"):
                self.messages.add("warning", body.strip(), head.strip().title())

    def notify(self, key, level, title, text, question=False, record=True):
        """Record in Messages/log, then pop up unless disabled in Settings > Messages."""
        if record:
            self.messages.add(level, text, title)
            self.log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {level.upper()}: {title}: {text}")
        if not app_settings.message_enabled(self.preferences, key):
            first = str(text).splitlines()[0] if text else ""
            self.statusBar().showMessage(f"{title}: {first} (see Messages)", 8000)
            return True
        before = dict(self.preferences.get("messages") or {})
        result = show_message(self, self.preferences, key, level, title, text, question=question)
        if self.preferences.get("messages") != before:
            try:
                app_settings.save(self.preferences, self.libset.root)
            except OSError as exc:
                self.messages.add("error", f"Could not save settings: {exc}", "Settings")
        return result

    def _show_help(self):
        QMessageBox.information(self, "Controls", (
            "Left drag: orbit    Right / middle drag: pan    Wheel: zoom\n"
            "Double-click: select the line under the cursor\n"
            "F / 1 2 3 4: fit / iso, top, front, right view\n"
            "Prepare view: drag the model to move it; 'Place on face', then click a face\n"
            "Ctrl+1 / Ctrl+2: Prepare / Preview view\n"
            "PgUp / PgDn: next / previous layer    Home / End: first / last layer\n"
            "Ctrl+O import model    Ctrl+R slice    Ctrl+S save G-code"))
