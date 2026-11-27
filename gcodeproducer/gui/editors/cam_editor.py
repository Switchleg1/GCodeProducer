"""Tool-change tree and operation-owned geometry / depth references."""
from __future__ import annotations

from .section import Section
from .editors_constants import (
    PICK_MODES,
    DEPTH_ROWS,
    OPERATION_SIDES,
    CUTTING_STRATEGIES,
    CUT_DIRECTIONS,
    DIRECTED_KINDS,
    CAPPED_COLOUR,
    ENGAGEMENT_CONTROLS,
    MACHINE_FEED_DEFAULTS,
    RATE_FIELDS,
    DEPTH_SOURCES,
    SECTION_BODY_MARGINS,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QFrame,
)
from gcodeproducer.core.cam.cam_setup import CAMSetup
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.operation import Operation
from gcodeproducer.core.cam.strategy import cutting_strategy
from gcodeproducer.core.cam.tool_group import ToolGroup
from gcodeproducer.core.cam.cam_constants import KINDS, KIND_LABELS, LEAD_ANGLE_RANGE, LEAD_MODES, LEAD_OUT_ANGLE_RANGE, RAMP_ANGLE, SURFACE_KINDS
from gcodeproducer.core.settings.settings_constants import DEFAULTS


class CAMEditor(QWidget):
    changed = pyqtSignal()
    selectionChanged = pyqtSignal()
    pickModeChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup = CAMSetup()
        operation_defaults = Operation()
        self.tools = []
        self.defaults = {}            # global "default operation settings" (core.app_settings)
        self.last_pick = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        saved = QLabel("CAM setup — automatically saved per model")
        saved.setWordWrap(True)
        layout.addWidget(saved)
        tools = Section("Tool changes & operations", key="cam.tool_changes")
        layout.addWidget(tools)
        row = QHBoxLayout()
        self.tool_combo = QComboBox()
        row.addWidget(self.tool_combo, 1)
        add = QPushButton("Add tool change")
        add.clicked.connect(self.add_tool)
        row.addWidget(add)
        tools.body.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tool changes / operations"])
        self.tree.setMinimumHeight(130)
        self.tree.currentItemChanged.connect(self._selected)
        tools.body.addWidget(self.tree)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(KIND_LABELS[k], k)
        row.addWidget(self.kind)
        add_op = QPushButton("Add operation")
        add_op.clicked.connect(self.add_operation)
        row.addWidget(add_op)
        for text, callback in (("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)),
                               ("Delete", self.delete)):
            b = QPushButton(text)
            b.setFixedWidth(60 if text == "Delete" else 28)
            b.clicked.connect(callback)
            row.addWidget(b)
        tools.body.addLayout(row)
        self.details = QFrame()
        self.operation_form = form = QFormLayout(self.details)
        form.setContentsMargins(*SECTION_BODY_MARGINS)
        # Narrow docks: long labels put their field on the next line instead of forcing a scrollbar.
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.details_section = Section("Operation", self.details, key="cam.operation")
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._edit)
        self.name.textEdited.connect(self._edit)
        form.addRow("Name", self.name)
        self.enabled = QCheckBox("Enabled")
        self.enabled.toggled.connect(self._edit)
        form.addRow(self.enabled)
        self.geom_label = QLabel("No geometry selected")
        self.geom_label.setWordWrap(True)
        form.addRow(self.geom_label)
        self.pick_source = QComboBox()
        self.pick_source.addItem("Part + material + references", "both")
        self.pick_source.addItem("Part only", "part")
        self.pick_source.addItem("Material only", "stock")
        self.pick_source.addItem("Reference geometry only", "reference")
        self.pick_source.setToolTip("By default pick part, material and drawn reference boundaries together. "
                                    "Use Reference geometry only to disambiguate overlapping outlines. "
                                    "The other choices are optional picking filters; neither clears existing selections. "
                                    "For an outside pocket, a horizontal material edge defines the blank rim and selected "
                                    "part rims or face footprints are retained inner boundaries.")
        self.pick_source.currentIndexChanged.connect(self._pick_source_changed)
        form.addRow("Pick from", self.pick_source)
        self.selections = QTreeWidget()
        self.selections.setHeaderLabels(["Selection", "Use for machining"])
        self.selections.setRootIsDecorated(False)
        self.selections.setMaximumHeight(150)
        self.selections.setToolTip("Purpose is per selection. Uncheck an edge/face to keep it only as a height reference. "
                                   "Select its row, then use it for Start Z or End Z below.")
        self.selections.itemChanged.connect(self._selection_purpose_changed)
        self.selections.currentItemChanged.connect(lambda *_: self.b_remove_ref.setEnabled(
            self.selections.currentItem() is not None))
        form.addRow(self.selections)                 # full width: one row per picked reference
        # Actions for the list sit directly under it, as in every pane.
        row = QHBoxLayout()
        self.pick = QComboBox()
        for label, mode in PICK_MODES:
            self.pick.addItem(label, mode)
        self.pick.currentIndexChanged.connect(self._pick_changed)
        row.addWidget(self.pick, 1)
        self.b_remove_ref = QPushButton("Remove")
        self.b_remove_ref.setToolTip("Remove the selected reference from this operation (machining and height-only)")
        self.b_remove_ref.setEnabled(False)
        self.b_remove_ref.clicked.connect(self.remove_selected_reference)
        row.addWidget(self.b_remove_ref)
        clear = QPushButton("Clear geometry")
        clear.setToolTip("Remove every machining reference of this operation (height-only references and "
                         "Start/End links stay)")
        clear.clicked.connect(self.clear_geometry)
        row.addWidget(clear)
        form.addRow(row)
        self.pick_status = QLabel("Click geometry to add/remove it from this operation.")
        self.pick_status.setWordWrap(True)
        form.addRow(self.pick_status)
        self.depth_controls = {}
        for key, title in DEPTH_ROWS:
            source = QComboBox()
            for label, val in DEPTH_SOURCES:
                source.addItem(label, val)
            val = self.spin(-10000, 10000, 0)
            extreme = QComboBox()
            extreme.addItem("Maximum Z", "max")
            extreme.addItem("Minimum Z", "min")
            use = QPushButton("Use selected reference")
            use.setToolTip("Use the selected reference row (or last viewport pick) as a live height reference, with an offset")
            use.clicked.connect(lambda _=False, k=key: self.use_depth(k))
            source.currentIndexChanged.connect(self._edit)
            val.valueChanged.connect(self._edit)
            extreme.currentIndexChanged.connect(self._edit)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(source)
            r = QHBoxLayout()
            r.addWidget(val, 1)
            r.addWidget(extreme, 1)
            v.addLayout(r)
            v.addWidget(use)
            form.addRow(title, box)
            self.depth_controls[key] = (source, val, extreme)
        self.depth_summary = QLabel("")
        self.depth_summary.setWordWrap(True)
        form.addRow(self.depth_summary)
        self.b_selection_depths = QPushButton("Use selection depths")
        self.b_selection_depths.setToolTip("Start at the highest selected face/edge Z; end at the lowest. Replaces both depth definitions. "
                                           "With 'Remove air cutting' (Settings) the start also drops below material removed by earlier operations.")
        self.b_selection_depths.clicked.connect(self.use_selection_depths)
        form.addRow(self.b_selection_depths)
        self.doc_override = QCheckBox("Unlock depth of cut")
        self.doc_override.setToolTip("Override this operation's axial depth per pass in mm. Unchecked uses the tool/material "
                                     "Slot/Pocket/Profile axial default. Tool Max depth/pass still caps the request.")
        self.doc_override.toggled.connect(self._edit)
        self.stepdown = self.spin(0.001, 1000, 1)
        self.stepdown.setSuffix(" mm/pass")
        self.stepdown.setToolTip(self.doc_override.toolTip())
        self.stepdown.valueChanged.connect(self._edit)
        self.cutting_summary = QLabel("")
        self.cutting_summary.setWordWrap(True)
        form.addRow(self.cutting_summary)
        self.rate_controls = {}
        for key, (label, maximum, _flag) in RATE_FIELDS.items():
            unlock = QCheckBox("Unlock " + label)
            unlock.toggled.connect(self._edit)
            value = self.spin(1, maximum, getattr(operation_defaults, key))
            value.valueChanged.connect(self._edit)
            form.addRow(unlock,value)
            self.rate_controls[key]=(unlock,value)
            if key == "feed":
                form.addRow(self.doc_override,self.stepdown)
        self.direction_override = QCheckBox("Unlock cutting direction")
        self.direction_override.setToolTip("Unchecked inherits the machine cutting direction. Checked overrides it for this operation.")
        self.direction_override.toggled.connect(self._edit)
        self.direction = QComboBox()
        self.direction.setPlaceholderText("Machine default")
        self.direction.setToolTip("M3: choose hand from remaining material. A full-width first slot has no unique climb/conventional hand. "
                                  "Raster lines: Meander cuts them both ways, joined without lifting; Climb and Conventional "
                                  "cut every line the same way.")
        for label, key in CUT_DIRECTIONS:
            self.direction.addItem(label, key)
        self.direction.currentIndexChanged.connect(self._edit)
        form.addRow(self.direction_override, self.direction)
        self.lead_in = QComboBox()
        self.lead_out = QComboBox()
        for box in (self.lead_in, self.lead_out):
            for key, label in LEAD_MODES:
                box.addItem(label, key)
            box.currentIndexChanged.connect(self._edit)
        self.lead_in.setToolTip("Ramp along the path (helix around a closed path, zigzag along an open one) when an entry "
                                "meets remaining material: on every entry, only the first entry of each layer (depth), or "
                                "never (entries then plunge at the plunge feed). Already-clear entries never ramp. "
                                "The same rule for flat and surface-following paths.")
        self.lead_out.setToolTip("After cutting, follow an already-cut part of the path before retracting: on every exit, "
                                 "only the last exit of each layer, or never. Retracts instead where remaining material "
                                 "makes the exit uncertain.")
        form.addRow("Lead-in", self.lead_in)
        form.addRow("Lead-out", self.lead_out)
        self.lead_length = self.spin(0,1000,0)
        self.lead_length.setSpecialValueText("Auto length")
        self.lead_length.valueChanged.connect(self._edit)
        form.addRow("Lead length (mm)",self.lead_length)
        self.lead_angle = self.spin(*LEAD_ANGLE_RANGE, RAMP_ANGLE)
        self.lead_angle.setToolTip("Maximum descent angle of the lead-in ramp. Shallower angles need more horizontal travel.")
        self.lead_angle.valueChanged.connect(self._edit)
        form.addRow("Lead-in angle (°)", self.lead_angle)
        self.lead_out_angle = self.spin(*LEAD_OUT_ANGLE_RANGE, RAMP_ANGLE)
        self.lead_out_angle.setToolTip("Climb angle of the lead-out: it follows the already-cut path back while rising "
                                       "at this angle, lifting the cutter off the floor and wall as it leaves. "
                                       "0 keeps the lead-out level on the path.")
        self.lead_out_angle.valueChanged.connect(self._edit)
        form.addRow("Lead-out angle (°)", self.lead_out_angle)
        self.stepover = self.spin(.1, 100, 40)
        self.stepover.setToolTip("Distance between neighbouring passes, as a percentage of the cutter diameter. "
                                 "With Adaptive clearing it is the engagement limit instead: the most of the "
                                 "cutter's width (measured square to its travel) any cut may engage; the "
                                 "spacing of the passes follows from the material. Does not apply to the lead-in.")
        self.area_order = QComboBox()
        self.area_order.addItem("Each area to full depth", "area")
        self.area_order.addItem("Each depth across all areas", "depth")
        self.area_order.setToolTip("Separate pocket regions are areas; all contours around a pocket and its islands stay together. "
                                   "Finish one area before moving to the next, or visit all areas at each depth. "
                                   "Default for new operations comes from Settings → Default operation settings.")
        self.side = QComboBox()
        self.side.setPlaceholderText("Legacy: On")
        self.side.setToolTip("Profile only: Outside or Inside. A legacy On value keeps its saved centreline until you explicitly choose a side.")
        for k in OPERATION_SIDES:
            self.side.addItem(k.title(), k)
        self.stock = self.spin(0, 100, 0)
        self.stock.setToolTip("Pocket/Profile/3D Pocket: radial material left on walls/islands. 3D Contour: axial stock above the surface.")
        self.overcut = self.spin(0, 1000, 0)
        self.overcut.setToolTip("Pocket / 3D Pocket: extend the removal region outward into stock that is not part of the model "
                                "at the sampled pass depths, within the material boundary limit. "
                                "Use this to overlap the next operation and avoid leaving a thin wall.")
        self.material_limit = self.spin(-1000, 1000, 0)
        self.material_limit.setToolTip("Pocket / 3D Pocket / 3D Contour, where the region reaches the blank edge: how far the cutter's outer edge may go "
                                       "relative to that edge. 0 touches it, -1 leaves 1 mm of material, +1 passes 1 mm beyond. "
                                       "Default comes from Settings → Default operation settings.")
        self.strategy = QComboBox()
        self.strategy.setPlaceholderText("Choose a cutting strategy")
        for label, w in (("Area order", self.area_order), ("Stepover (%)", self.stepover),
                         ("Profile side", self.side), ("Roughing clearance (mm)", self.stock),
                         ("Overcut (mm)", self.overcut),
                         ("Material boundary (mm)", self.material_limit),
                         ("Cutting strategy", self.strategy)):
            form.addRow(label, w)
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._edit)
            else:
                w.valueChanged.connect(self._edit)
        self.stay_down = QCheckBox("Stay down between contours")
        self.stay_down.setToolTip("Use short cutting-feed links inside the cutter-clearance region. Retract when no direct safe link exists. "
                                  "3D Contour cut one way (Climb/Conventional): come back along the line just cut instead of "
                                  "lifting back to the start of the next (off by default). 3D Contour spiral: where it "
                                  "runs into the edge of the area, walk along the edge to where it comes back in.")
        self.stay_down.toggled.connect(self._edit)
        form.addRow(self.stay_down)
        self.follow_surface = QCheckBox("Follow the surface within each depth")
        self.follow_surface.setToolTip("3D Pocket: each depth also works the area up to the depth above, riding up the "
                                       "model surface instead of stopping at it, so slopes are not left as steps.")
        self.follow_surface.toggled.connect(self._edit)
        form.addRow(self.follow_surface)
        self.feed_controls = {}
        feeds_body = QFrame()
        ff = QFormLayout(feeds_body)
        ff.setContentsMargins(*SECTION_BODY_MARGINS)
        feeds = Section("Engagement feeds (% of tool feed)", feeds_body, expanded=False,
                        key="cam.engagement_feeds", level=1)
        for key, label in ENGAGEMENT_CONTROLS:
            sb = self.spin(0, 300, 0)
            sb.setDecimals(0)
            sb.setSpecialValueText("Machine default" if key in MACHINE_FEED_DEFAULTS else "Tool default")
            sb.setSuffix(" %")
            sb.setToolTip(("HSM = low horizontal (radial) engagement. " if key == "low_engagement_feed" else "")
                          + ("Lead-in ramps, arcs and lead-outs. " if key == "lead_in_feed_modifier" else "")
                          + ("Straight down into material; steeper descents blend toward it. "
                             if key == "plunge_feed_modifier" else "")
                          + f"0 inherits the {'machine' if key in MACHINE_FEED_DEFAULTS else 'tool'} default. "
                          "100% is base tool feed; values above 100% increase it, subject to machine max feed. "
                          "Unlocked lead-in / plunge feeds above override these.")
            sb.valueChanged.connect(self._edit)
            self.feed_controls[key] = sb
            ff.addRow(label, sb)
        feed_note = QLabel("Approximate remaining-material estimate, not machine telemetry. Full slots have no unique cutting hand.")
        feed_note.setWordWrap(True)
        ff.addRow(feed_note)
        form.addRow(feeds)
        layout.addWidget(self.details_section)
        warning = QLabel("Approximate 2.5D / 3-axis checks only; no holder or fixture simulation. "
                         "Verify clearance and air-cut before machining.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
        for label in self.details.findChildren(QLabel):
            label.setWordWrap(True)
        # Wrapped QLabel size hints can reserve a needlessly narrow label column
        # despite spare room before the field. Keep these short labels intact;
        # WrapLongRows can still move their fields below them in a narrow dock.
        for field in (self.stock, self.material_limit):
            form.labelForField(field).setWordWrap(False)
        self.rebuild()

    def _pick_changed(self, *_):
        mode = self.pick.currentData()
        if mode and self.pick_source.currentData() in ("stock", "reference"):
            mode = self.pick_source.currentData()+"_"+mode
        self.pickModeChanged.emit(mode)

    def _pick_source_changed(self, *_):
        if not self.pick.currentData() and self.operation() is not None:
            self.pick.setCurrentIndex(self.pick.findData("face"))
        else:
            self._pick_changed()

    @staticmethod
    def spin(lo, hi, value):
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setDecimals(3)
        w.setValue(value)
        return w

    def set_tools(self, tools):
        self.tools = list(tools)
        self.tool_combo.clear()
        for t in tools:
            self.tool_combo.addItem(f"T{t.get('tool_number', 1)} — {t.name}", t.id)
        self.rebuild()

    def set_setup(self, setup):
        self.setup = setup
        self.last_pick = None
        self.pick.setCurrentIndex(0)
        self.pick_source.blockSignals(True)
        self.pick_source.setCurrentIndex(self.pick_source.findData("both"))
        self.pick_source.blockSignals(False)
        first = next(((gi, 0) for gi, g in enumerate(setup.groups) if g.operations), (None, None))
        self.rebuild(first)

    def indices(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else (None, None)

    def operation(self):
        g, o = self.indices()
        return self.setup.groups[g].operations[o] if g is not None and o is not None else None

    def rebuild(self, select=None):
        select = select if select is not None else self.indices()
        self.tree.blockSignals(True)
        self.tree.clear()
        tools = {t.id: t for t in self.tools}
        for gi, group in enumerate(self.setup.groups):
            tool = tools.get(group.tool_id)
            title = f"T{tool.get('tool_number', 1)} — {tool.name}" if tool else f"Missing tool: {group.tool_id}"
            root = QTreeWidgetItem([title])
            root.setData(0, Qt.ItemDataRole.UserRole, (gi, None))
            self.tree.addTopLevelItem(root)
            if select == (gi, None):
                self.tree.setCurrentItem(root)
            for oi, op in enumerate(group.operations):
                item = QTreeWidgetItem([f"{KIND_LABELS.get(op.kind, op.kind.title())}: {op.name}" + (" (off)" if not op.enabled else "")])
                item.setData(0, Qt.ItemDataRole.UserRole, (gi, oi))
                root.addChild(item)
                if select == (gi, oi):
                    self.tree.setCurrentItem(item)
            root.setExpanded(True)
        self.tree.blockSignals(False)
        self._selected()

    def add_tool(self):
        tool_id = self.tool_combo.currentData()
        if not tool_id:
            return
        self.setup.groups.append(ToolGroup(tool_id))
        self.rebuild((len(self.setup.groups) - 1, None))
        self.changed.emit()

    def add_operation(self):
        gi, _ = self.indices()
        if gi is None:
            return
        kind = self.kind.currentData()
        tool = next((t for t in self.tools if t.id == self.setup.groups[gi].tool_id), None)
        op = Operation(name=KIND_LABELS[kind], kind=kind, strategy="raster_x" if kind == "contour3d" else "contour",
                       auto_stepdown=True, stepdown=float(tool.get("max_doc", 1) or 1) if tool else 1,
                       area_order=self.defaults.get("default_area_order", DEFAULTS["default_area_order"]),
                       material_limit=float(self.defaults.get("default_material_limit", DEFAULTS["default_material_limit"])),
                       overcut=float(self.defaults.get("default_overcut", DEFAULTS["default_overcut"])) if kind in ("pocket", "waterfall") else 0.0)
        if kind == "pocket" or kind in SURFACE_KINDS:
            op.start = Depth("selection", extreme="max")
            op.end = Depth("selection", extreme="min")
        elif kind == "engrave":
            op.end = Depth("top", -0.2)
        self.setup.groups[gi].operations.append(op)
        self.rebuild((gi, len(self.setup.groups[gi].operations) - 1))
        self.changed.emit()

    def delete(self):
        gi, oi = self.indices()
        if gi is None:
            return
        if oi is None:
            del self.setup.groups[gi]
        else:
            del self.setup.groups[gi].operations[oi]
        self.rebuild((None, None))
        self.changed.emit()

    def move(self, delta):
        gi, oi = self.indices()
        if gi is None:
            return
        seq, i = (self.setup.groups, gi) if oi is None else (self.setup.groups[gi].operations, oi)
        j = i + delta
        if 0 <= j < len(seq):
            seq[i], seq[j] = seq[j], seq[i]
            self.rebuild((j, None) if oi is None else (gi, j))
            self.changed.emit()

    def _selected(self, *_):
        self._loading = True
        op = self.operation()
        self.pick.setCurrentIndex(self.pick.findData("face") if op is not None else 0)
        self._pick_changed()
        self.last_pick = None
        self._refresh_selections()
        self.details.setEnabled(op is not None)
        choices = CUTTING_STRATEGIES.get(op.kind, ()) if op else ()
        self.operation_form.setRowVisible(self.strategy, bool(choices))
        # Area order is decided by the operation (3D Pocket works each depth across all areas).
        self.operation_form.setRowVisible(self.area_order, False)
        self.operation_form.setRowVisible(self.side, op is not None and op.kind == "profile")
        self.operation_form.setRowVisible(self.overcut, op is not None and op.kind in ("pocket", "waterfall"))
        self.operation_form.setRowVisible(self.follow_surface, op is not None and op.kind == "waterfall")
        self.strategy.clear()
        for label, value in choices:
            self.strategy.addItem(label, value)
        self.b_selection_depths.setVisible(op is not None and (op.kind == "pocket" or op.kind in SURFACE_KINDS))
        if op:
            self.name.setText(op.name)
            self.enabled.setChecked(op.enabled)
            self.geom_label.setText(f"{len(op.geometry)} geometry references")
            self.pick_status.setText("Pick part, material or drawn reference boundaries. For an outside pocket, select an inner rim and a material edge.")
            self.depth_summary.setText("")
            for key, (source, val, extreme) in self.depth_controls.items():
                d = getattr(op, key)
                source.setCurrentIndex(source.findData(d.source))
                val.setValue(d.value)
                extreme.setCurrentIndex(extreme.findData(d.extreme))
            self.doc_override.setChecked(not op.auto_stepdown)
            self.stepdown.setValue(op.stepdown)
            self.stepdown.setEnabled(not op.auto_stepdown)
            for key,(unlock,value) in self.rate_controls.items():
                flag = RATE_FIELDS[key][2]
                unlock.setChecked(getattr(op,flag))
                value.setValue(getattr(op,key))
                value.setEnabled(unlock.isChecked())
            self.lead_in.setCurrentIndex(self.lead_in.findData(Operation.lead_mode(op.lead_in)))
            self.lead_out.setCurrentIndex(self.lead_out.findData(Operation.lead_mode(op.lead_out)))
            self.lead_length.setValue(op.lead_length)
            self.lead_angle.setValue(op.lead_angle)
            self.lead_out_angle.setValue(op.lead_out_angle)
            self.stepover.setValue(op.stepover)
            self.area_order.setCurrentIndex(self.area_order.findData(op.area_order))
            self.side.setCurrentIndex(self.side.findData(op.side))
            self.stock.setValue(op.stock)
            self.overcut.setValue(op.overcut)
            self.material_limit.setValue(op.material_limit)
            self.material_limit.setEnabled(op.kind in ("pocket", "waterfall", "contour3d"))
            self.strategy.setCurrentIndex(self.strategy.findData(cutting_strategy(op.kind, op.strategy)))
            self.direction_override.setChecked(op.cut_direction != "machine")
            self.direction.setCurrentIndex(self.direction.findData(op.cut_direction))
            # (3D Contour keeps its own flag, off by default: the saved clearing flag was never its choice.)
            self.stay_down.setChecked(op.stay_down_lines if op.kind == "contour3d" else op.stay_down)
            self.follow_surface.setChecked(op.follow_surface)
            self._update_stay_down(op)
            for key, sb in self.feed_controls.items():
                sb.setValue(getattr(op, key))
                sb.setEnabled(op.kind != "drill")
            self.strategy.setEnabled(bool(choices))
            self.direction_override.setEnabled(op.kind in DIRECTED_KINDS)
            self.direction.setEnabled(op.kind in DIRECTED_KINDS and self.direction_override.isChecked())
            self.stepover.setEnabled(op.kind in ("pocket", "waterfall", "contour3d"))
            self.side.setEnabled(op.kind == "profile")
        self._loading = False
        self.selectionChanged.emit()

    def _update_stay_down(self, op):
        self.stay_down.setEnabled((op.kind in ("pocket", "waterfall") and op.strategy in ("contour", "adaptive"))
                                  or op.kind == "contour3d")

    def _edit(self, *_):
        if self._loading:
            return
        op = self.operation()
        if not op:
            return
        op.name, op.enabled = self.name.text(), self.enabled.isChecked()
        for key, (source, val, extreme) in self.depth_controls.items():
            d = getattr(op, key)
            d.source, d.value, d.extreme = source.currentData(), val.value(), extreme.currentData()
        op.auto_stepdown = not self.doc_override.isChecked()
        self.stepdown.setEnabled(not op.auto_stepdown)
        op.stepdown, op.stepover = self.stepdown.value(), self.stepover.value()
        op.area_order = self.area_order.currentData()
        for key,(unlock,value) in self.rate_controls.items():
            flag = RATE_FIELDS[key][2]
            setattr(op,flag,unlock.isChecked())
            setattr(op,key,value.value())
            value.setEnabled(unlock.isChecked())
        op.lead_in,op.lead_out = self.lead_in.currentData() or "every",self.lead_out.currentData() or "every"
        op.lead_length = self.lead_length.value()
        op.lead_angle = self.lead_angle.value()
        op.lead_out_angle = self.lead_out_angle.value()
        if op.kind == "profile" and self.side.currentData() is not None:
            op.side = self.side.currentData()
        op.stock = self.stock.value()
        op.overcut = self.overcut.value()
        op.material_limit = self.material_limit.value()
        if op.kind in CUTTING_STRATEGIES and self.strategy.currentData() is not None:
            op.strategy = self.strategy.currentData()
        if self.direction_override.isChecked() and self.direction.currentIndex() < 0:
            self.direction.blockSignals(True)
            self.direction.setCurrentIndex(0)
            self.direction.blockSignals(False)
        op.cut_direction = self.direction.currentData() if self.direction_override.isChecked() else "machine"
        self.direction.setEnabled(op.kind in DIRECTED_KINDS and self.direction_override.isChecked())
        if op.kind == "contour3d":
            op.stay_down_lines = self.stay_down.isChecked()
        else:
            op.stay_down = self.stay_down.isChecked()
        op.follow_surface = self.follow_surface.isChecked()
        for key, sb in self.feed_controls.items():
            setattr(op, key, sb.value())
        self._update_stay_down(op)
        item = self.tree.currentItem()
        item.setText(0, f"{KIND_LABELS.get(op.kind, op.kind.title())}: {op.name}" + (" (off)" if not op.enabled else ""))
        self.changed.emit()

    def _refresh_selections(self, selected=None):
        op = self.operation()
        current = self.selections.currentItem()
        if selected is None and current is not None:
            selected = current.data(0, Qt.ItemDataRole.UserRole)
        refs = [] if op is None else list(op.geometry) + list(op.height_references)
        if op is not None:
            for depth in (op.start, op.end):
                if depth.source == "geometry" and depth.reference is not None and depth.reference not in refs:
                    refs.append(depth.reference)
        self.selections.blockSignals(True)
        self.selections.clear()
        for ref in refs:
            machining = ref in op.geometry
            label = ref.kind.replace("stock_", "material ") + " " + ", ".join(map(str, ref.indices))
            if ref.kind == "drawing":
                shape = next((s for s in self.setup.reference_shapes if [s.id] == ref.indices), None)
                label = "Reference: " + (shape.name or shape.kind if shape is not None else "missing")
            item = QTreeWidgetItem([label, "Machining" if machining else "Height only"])
            item.setData(0, Qt.ItemDataRole.UserRole, ref)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(1, Qt.CheckState.Checked if machining else Qt.CheckState.Unchecked)
            self.selections.addTopLevelItem(item)
            if ref == selected:
                self.selections.setCurrentItem(item)
        self.selections.resizeColumnToContents(0)
        self.selections.blockSignals(False)
        self.b_remove_ref.setEnabled(self.selections.currentItem() is not None)

    def _selection_purpose_changed(self, item, column):
        op = self.operation()
        if self._loading or op is None or column != 1:
            return
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        if item.checkState(1) == Qt.CheckState.Checked:
            if ref not in op.geometry:
                op.geometry.append(ref)
            if ref in op.height_references:
                op.height_references.remove(ref)
        else:
            if ref in op.geometry:
                op.geometry.remove(ref)
            if ref not in op.height_references:
                op.height_references.append(ref)
        self.selections.blockSignals(True)
        item.setText(1, "Machining" if ref in op.geometry else "Height only")
        self.selections.blockSignals(False)
        self.geom_label.setText(f"{len(op.geometry)} geometry references")
        self.changed.emit()

    def accept_pick(self, result):
        op = self.operation()
        if not op:
            return
        if result is None:
            self.pick_status.setText("Nothing selectable here. Click a visible face or switch to Select edges and click near a rim.")
            return
        if "error" in result:
            self.pick_status.setText(result["error"])
            return
        self.last_pick = result
        ref = result["reference"]
        if ref in op.geometry:
            op.geometry.remove(ref)
        elif ref in op.height_references:
            op.height_references.remove(ref)
        else:
            op.geometry.append(ref)
        self._refresh_selections(ref)
        self.geom_label.setText(f"{len(op.geometry)} geometry references")
        self.pick_status.setText(f"Picked {ref.kind.replace('stock_', 'material ')}: Z {result['z_min']:.3f} … {result['z_max']:.3f} mm")
        self.changed.emit()

    def use_depth(self, key):
        op = self.operation()
        item = self.selections.currentItem()
        ref = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else (
            self.last_pick["reference"] if self.last_pick else None)
        if op and ref is not None:
            _, _, extreme = self.depth_controls[key]
            setattr(op, key, Depth("geometry", 0, ref, extreme.currentData()))
            source, val, _ = self.depth_controls[key]
            self._loading = True
            source.setCurrentIndex(source.findData("geometry"))
            val.setValue(0)
            self._loading = False
            self._refresh_selections(ref)
            self.changed.emit()

    def set_calculated(self,values):
        if not self.direction_override.isChecked() and "cut_direction" in values:
            self.direction.blockSignals(True)
            self.direction.setCurrentIndex(self.direction.findData(values["cut_direction"]))
            self.direction.blockSignals(False)
        for key,(unlock,value) in self.rate_controls.items():
            if not unlock.isChecked() and key in values:
                value.blockSignals(True);value.setValue(values[key]);value.blockSignals(False)
        if not self.doc_override.isChecked() and "stepdown" in values:
            self.stepdown.blockSignals(True);self.stepdown.setValue(values["stepdown"]);self.stepdown.blockSignals(False)
        if "stepdown" in values:
            self.flag_stepdown_cap(values.get("requested_stepdown", values["stepdown"]), values["stepdown"])

    def flag_stepdown_cap(self, requested, used):
        """Orange depth of cut, with the reason in its tooltip, when the tool's Max depth/pass cuts it down."""
        capped = requested > used + 1e-9
        self.stepdown.setStyleSheet(f"QDoubleSpinBox {{ color: {CAPPED_COLOUR}; }}" if capped else "")
        self.stepdown.setToolTip(
            f"Capped by the tool: this operation asks for {requested:g} mm per pass, but the tool's Max depth/pass "
            f"is {used:g} mm, so passes are {used:g} mm deep. Raise or clear (0) Max depth/pass in the tool "
            f"library to cut deeper." if capped else self.doc_override.toolTip())

    def use_selection_depths(self):
        op = self.operation()
        if op is None or not (op.kind == "pocket" or op.kind in SURFACE_KINDS):
            return
        op.start, op.end = Depth("selection", extreme="max"), Depth("selection", extreme="min")
        self._loading = True
        for key, (source, val, extreme) in self.depth_controls.items():
            d = getattr(op, key)
            source.setCurrentIndex(source.findData(d.source))
            val.setValue(d.value)
            extreme.setCurrentIndex(extreme.findData(d.extreme))
        self._loading = False
        self.changed.emit()

    def remove_selected_reference(self):
        """Drop the selected row's reference from the operation.

        A reference that still defines Start or End Z is kept (it cannot silently
        change the depth); unlink the depth first.
        """
        op = self.operation()
        item = self.selections.currentItem()
        if op is None or item is None:
            return
        ref = item.data(0, Qt.ItemDataRole.UserRole)
        linked = [name for name, d in (("Start", op.start), ("End", op.end))
                  if d.source == "geometry" and d.reference == ref]
        if linked:
            self.pick_status.setText(f"This reference defines {' and '.join(linked)} Z. Choose another depth source "
                                     "first, then remove it.")
            return
        if ref in op.geometry:
            op.geometry.remove(ref)
        if ref in op.height_references:
            op.height_references.remove(ref)
        self._refresh_selections()
        self.geom_label.setText(f"{len(op.geometry)} geometry references")
        self.pick_status.setText("Reference removed from this operation.")
        self.changed.emit()

    def clear_geometry(self):
        op = self.operation()
        if op:
            op.geometry.clear()
            self._refresh_selections()
            self.geom_label.setText("No geometry selected")
            self.changed.emit()
