"""Tool-change tree and operation-owned geometry / depth references."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
                             QPushButton, QComboBox, QDoubleSpinBox, QFormLayout, QLabel,
                             QLineEdit, QCheckBox, QGroupBox)

from ..core.cam import CAMSetup, Depth, Operation, ToolGroup, KINDS


class CAMEditor(QWidget):
    changed = pyqtSignal()
    selectionChanged = pyqtSignal()
    pickModeChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup = CAMSetup()
        self.tools = []
        self.defaults = {}            # global "default operation settings" (core.app_settings)
        self.pick_target = "geometry"
        self.last_pick = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        saved = QLabel("CAM setup — automatically saved per model")
        saved.setWordWrap(True)
        layout.addWidget(saved)
        row = QHBoxLayout()
        self.tool_combo = QComboBox()
        row.addWidget(self.tool_combo, 1)
        add = QPushButton("Add tool change")
        add.clicked.connect(self.add_tool)
        row.addWidget(add)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tool changes / operations"])
        self.tree.setMinimumHeight(130)
        self.tree.currentItemChanged.connect(self._selected)
        layout.addWidget(self.tree)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for k in KINDS:
            self.kind.addItem(k.title(), k)
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
        layout.addLayout(row)
        self.details = QGroupBox("Operation")
        form = QFormLayout(self.details)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._edit)
        form.addRow("Name", self.name)
        self.enabled = QCheckBox("Enabled")
        self.enabled.toggled.connect(self._edit)
        form.addRow(self.enabled)
        self.geom_label = QLabel("No geometry selected")
        self.geom_label.setWordWrap(True)
        form.addRow(self.geom_label)
        row = QHBoxLayout()
        self.pick = QComboBox()
        for label, mode in (("Navigate / place model", ""), ("Select faces", "face"), ("Select edges", "edge")):
            self.pick.addItem(label, mode)
        self.pick.currentIndexChanged.connect(self._pick_changed)
        row.addWidget(self.pick)
        clear = QPushButton("Clear geometry")
        clear.clicked.connect(self.clear_geometry)
        row.addWidget(clear)
        form.addRow(row)
        self.pick_source = QComboBox()
        self.pick_source.addItem("Part + material together", "both")
        self.pick_source.addItem("Part only", "part")
        self.pick_source.addItem("Material only", "stock")
        self.pick_source.setToolTip("By default pick both part and material boundaries in the same operation without switching. "
                                    "The other choices are optional picking filters; neither clears existing selections. "
                                    "For an outside pocket, a horizontal material edge defines the blank rim and selected "
                                    "part rims or face footprints are retained inner boundaries.")
        self.pick_source.currentIndexChanged.connect(self._pick_source_changed)
        form.addRow("Pick from", self.pick_source)
        self.target = QComboBox()
        self.target.addItem("Apply picks to machining geometry", "geometry")
        self.target.addItem("Pick height reference only", "height")
        form.addRow("Pick purpose", self.target)
        self.pick_status = QLabel("Click geometry to add/remove it from this operation.")
        self.pick_status.setWordWrap(True)
        form.addRow(self.pick_status)
        self.depth_controls = {}
        for key, title in (("start", "Start Z"), ("end", "End Z")):
            source = QComboBox()
            for label, val in (("Model top + offset", "top"), ("Model bottom + offset", "bottom"),
                               ("Absolute Z", "absolute"), ("Selected geometry + offset", "geometry"),
                               ("Material surface + offset", "stock_top"),
                               ("Machining selection + offset", "selection")):
                source.addItem(label, val)
            val = self.spin(-10000, 10000, 0)
            extreme = QComboBox()
            extreme.addItem("Maximum Z", "max")
            extreme.addItem("Minimum Z", "min")
            use = QPushButton("Use last pick")
            use.setToolTip("Use the last clicked face/edge as a live height reference (then add an offset)")
            use.clicked.connect(lambda _=False, k=key: self.use_depth(k))
            source.currentIndexChanged.connect(self._edit)
            val.valueChanged.connect(self._edit)
            extreme.currentIndexChanged.connect(self._edit)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(source)
            r = QHBoxLayout()
            r.addWidget(val)
            r.addWidget(extreme)
            r.addWidget(use)
            v.addLayout(r)
            form.addRow(title, box)
            self.depth_controls[key] = (source, val, extreme)
        self.depth_summary = QLabel("")
        self.depth_summary.setWordWrap(True)
        form.addRow(self.depth_summary)
        self.b_selection_depths = QPushButton("Use pocket selection depths")
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
        for key,label,maximum in (("rpm","Spindle RPM",100000), ("feed","Normal cut base feed",50000),
                                  ("lead_feed","Lead / plunge base feed",50000)):
            unlock = QCheckBox("Unlock " + label)
            unlock.toggled.connect(self._edit)
            value = self.spin(1,maximum,18000 if key=="rpm" else 800 if key=="feed" else 300)
            value.valueChanged.connect(self._edit)
            form.addRow(unlock,value)
            self.rate_controls[key]=(unlock,value)
            if key == "feed":
                form.addRow(self.doc_override,self.stepdown)
        self.lead_in = QCheckBox("Lead-in ramp along selected contour")
        self.lead_out = QCheckBox("Lead-out along cleared contour")
        self.lead_in.toggled.connect(self._edit)
        self.lead_out.toggled.connect(self._edit)
        form.addRow(self.lead_in)
        form.addRow(self.lead_out)
        self.lead_length = self.spin(0,1000,0)
        self.lead_length.setSpecialValueText("Auto length / 10° ramp")
        self.lead_length.valueChanged.connect(self._edit)
        form.addRow("Lead length (mm)",self.lead_length)
        self.stepover = self.spin(1, 100, 40)
        self.area_order = QComboBox()
        self.area_order.addItem("Each area to full depth", "area")
        self.area_order.addItem("Each depth across all areas", "depth")
        self.area_order.setToolTip("Separate pocket regions are areas; all contours around a pocket and its islands stay together. "
                                   "Finish one area before moving to the next, or visit all areas at each depth. "
                                   "Default for new operations comes from Settings → Default operation settings.")
        self.side = QComboBox()
        for k in ("outside", "inside", "on"):
            self.side.addItem(k.title(), k)
        self.stock = self.spin(0, 100, 0)
        self.stock.setToolTip("Roughing clearance: material left on every selected wall/island for a later finishing pass.")
        self.overcut = self.spin(0, 1000, 0)
        self.overcut.setToolTip("Pocket only: grow the removal region outward by this distance into void material (stock that is not "
                                "part of the model at any pass depth). Part cross-sections plus roughing clearance are never entered. "
                                "Lets this pocket overlap the next operation so no thin wall remains between them.")
        self.material_limit = self.spin(-1000, 1000, 0)
        self.material_limit.setToolTip("Pocket only, where the region reaches the blank edge: how far the cutter's outer edge may go "
                                       "relative to that edge. 0 touches it, -1 leaves 1 mm of material, +1 passes 1 mm beyond. "
                                       "Default comes from Settings → Default operation settings.")
        self.strategy = QComboBox()
        self.strategy.addItem("Wall-parallel contours", "contour")
        self.strategy.addItem("Raster lines", "raster")
        self.direction = QComboBox()
        self.direction.setToolTip("M3: choose hand from remaining material. A full-width first slot has no unique climb/conventional hand.")
        for label, key in (("Machine default", "machine"), ("Climb", "climb"),
                           ("Conventional", "conventional"), ("Meander", "meander")):
            self.direction.addItem(label, key)
        for label, w in (("Area order", self.area_order), ("Pocket stepover (%)", self.stepover),
                         ("Profile side", self.side), ("Roughing clearance / stock to leave (mm)", self.stock),
                         ("Pocket overcut into void (mm)", self.overcut),
                         ("Material boundary limit (mm)", self.material_limit),
                         ("Pocket strategy", self.strategy), ("Cutting direction", self.direction)):
            form.addRow(label, w)
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._edit)
            else:
                w.valueChanged.connect(self._edit)
        self.stay_down = QCheckBox("Stay down between contours")
        self.stay_down.setToolTip("Use short cutting-feed links inside the cutter-clearance region. Retract when no direct safe link exists.")
        self.stay_down.toggled.connect(self._edit)
        form.addRow(self.stay_down)
        self.feed_controls = {}
        feeds = QGroupBox("Engagement feeds (% of tool feed)")
        ff = QFormLayout(feeds)
        for key, label in (("low_engagement_feed", "HSM"),
                           ("standard_engagement_feed", "Cut"),
                           ("high_engagement_feed", "High engagement"),
                           ("slotting_feed", "Slot")):
            sb = self.spin(0, 300, 0)
            sb.setDecimals(0)
            sb.setSpecialValueText("Machine default" if key in ("high_engagement_feed","slotting_feed") else "Tool default")
            sb.setSuffix(" %")
            sb.setToolTip(("HSM = low horizontal (radial) engagement. " if key == "low_engagement_feed" else "")
                          + "0 inherits the tool profile. 100% is base tool feed; values above 100% increase it, subject to machine max feed.")
            sb.valueChanged.connect(self._edit)
            self.feed_controls[key] = sb
            ff.addRow(label, sb)
        feed_note = QLabel("Planar estimate, not machine telemetry. Full slots and balanced frontal entries have no unique cutting hand.")
        feed_note.setWordWrap(True)
        ff.addRow(feed_note)
        form.addRow(feeds)
        layout.addWidget(self.details)
        warning = QLabel("2.5D CAM • Conservative original-stock checks only; no stock-removal, "
                         "holder or fixture simulation. Verify clearance and air-cut before machining.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.rebuild()

    def _pick_changed(self, *_):
        mode = self.pick.currentData()
        if mode and self.pick_source.currentData() == "stock":
            mode = "stock_"+mode
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
                item = QTreeWidgetItem([f"{op.kind.title()}: {op.name}" + (" (off)" if not op.enabled else "")])
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
        op = Operation(name=kind.title(), kind=kind, auto_stepdown=True, stepdown=float(tool.get("max_doc", 1) or 1) if tool else 1,
                       area_order=self.defaults.get("default_area_order", "area"),
                       material_limit=float(self.defaults.get("default_material_limit", 0.0)),
                       overcut=float(self.defaults.get("default_overcut", 0.0)) if kind == "pocket" else 0.0)
        if kind == "pocket":
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
        self.details.setEnabled(op is not None)
        self.b_selection_depths.setVisible(op is not None and op.kind == "pocket")
        if op:
            self.name.setText(op.name)
            self.enabled.setChecked(op.enabled)
            self.geom_label.setText(f"{len(op.geometry)} geometry references")
            self.pick_status.setText("Pick part and material boundaries together. For an outside pocket, select a part rim and a material edge.")
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
                flag = "unlock_rpm" if key=="rpm" else "unlock_feed" if key=="feed" else "unlock_lead_feed"
                unlock.setChecked(getattr(op,flag))
                value.setValue(getattr(op,key))
                value.setEnabled(unlock.isChecked())
            self.lead_in.setChecked(op.lead_in)
            self.lead_out.setChecked(op.lead_out)
            self.lead_length.setValue(op.lead_length)
            self.stepover.setValue(op.stepover)
            self.area_order.setCurrentIndex(self.area_order.findData(op.area_order))
            self.side.setCurrentIndex(self.side.findData(op.side))
            self.stock.setValue(op.stock)
            self.overcut.setValue(op.overcut)
            self.overcut.setEnabled(op.kind == "pocket")
            self.material_limit.setValue(op.material_limit)
            self.material_limit.setEnabled(op.kind == "pocket")
            self.strategy.setCurrentIndex(self.strategy.findData(op.strategy))
            self.direction.setCurrentIndex(self.direction.findData(op.cut_direction))
            self.stay_down.setChecked(op.stay_down)
            self.stay_down.setEnabled(op.kind == "pocket" and op.strategy == "contour")
            for key, sb in self.feed_controls.items():
                sb.setValue(getattr(op, key))
                sb.setEnabled(op.kind != "drill")
            self.strategy.setEnabled(op.kind == "pocket")
            self.direction.setEnabled(op.kind in ("pocket", "profile"))
            self.stepover.setEnabled(op.kind == "pocket")
            self.side.setEnabled(op.kind == "profile")
        self._loading = False
        self.selectionChanged.emit()

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
            flag = "unlock_rpm" if key=="rpm" else "unlock_feed" if key=="feed" else "unlock_lead_feed"
            setattr(op,flag,unlock.isChecked())
            setattr(op,key,value.value())
            value.setEnabled(unlock.isChecked())
        op.lead_in,op.lead_out = self.lead_in.isChecked(),self.lead_out.isChecked()
        op.lead_length = self.lead_length.value()
        op.side, op.stock = self.side.currentData(), self.stock.value()
        op.overcut = self.overcut.value()
        op.material_limit = self.material_limit.value()
        op.strategy, op.cut_direction = self.strategy.currentData(), self.direction.currentData()
        op.stay_down = self.stay_down.isChecked()
        for key, sb in self.feed_controls.items():
            setattr(op, key, sb.value())
        self.stay_down.setEnabled(op.kind == "pocket" and op.strategy == "contour")
        item = self.tree.currentItem()
        item.setText(0, f"{op.kind.title()}: {op.name}" + (" (off)" if not op.enabled else ""))
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
        if self.target.currentData() == "geometry":
            if ref in op.geometry:
                op.geometry.remove(ref)
            else:
                op.geometry.append(ref)
        self.geom_label.setText(f"{len(op.geometry)} geometry references")
        self.pick_status.setText(f"Picked {ref.kind.replace('stock_', 'material ')}: Z {result['z_min']:.3f} … {result['z_max']:.3f} mm")
        self.changed.emit()

    def use_depth(self, key):
        op = self.operation()
        if op and self.last_pick:
            _, _, extreme = self.depth_controls[key]
            setattr(op, key, Depth("geometry", 0, self.last_pick["reference"], extreme.currentData()))
            source, val, _ = self.depth_controls[key]
            self._loading = True
            source.setCurrentIndex(source.findData("geometry"))
            val.setValue(0)
            self._loading = False
            self.changed.emit()

    def set_calculated(self,values):
        for key,(unlock,value) in self.rate_controls.items():
            if not unlock.isChecked() and key in values:
                value.blockSignals(True);value.setValue(values[key]);value.blockSignals(False)
        if not self.doc_override.isChecked() and "stepdown" in values:
            self.stepdown.blockSignals(True);self.stepdown.setValue(values["stepdown"]);self.stepdown.blockSignals(False)

    def use_selection_depths(self):
        op = self.operation()
        if op is None or op.kind != "pocket":
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

    def clear_geometry(self):
        op = self.operation()
        if op:
            op.geometry.clear()
            self.geom_label.setText("No geometry selected")
            self.changed.emit()
