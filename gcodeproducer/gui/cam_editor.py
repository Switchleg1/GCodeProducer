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
        self.pick.currentIndexChanged.connect(lambda: self.pickModeChanged.emit(self.pick.currentData()))
        row.addWidget(self.pick)
        clear = QPushButton("Clear geometry")
        clear.clicked.connect(self.clear_geometry)
        row.addWidget(clear)
        form.addRow(row)
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
        self.b_selection_depths.setToolTip("Start at material surface; end at the lowest selected face/edge Z. Replaces both depth definitions.")
        self.b_selection_depths.clicked.connect(self.use_selection_depths)
        form.addRow(self.b_selection_depths)
        self.stepdown = self.spin(0.001, 1000, 1)
        self.stepover = self.spin(1, 100, 40)
        self.side = QComboBox()
        for k in ("outside", "inside", "on"):
            self.side.addItem(k.title(), k)
        self.stock = self.spin(0, 100, 0)
        self.strategy = QComboBox()
        self.strategy.addItem("Wall-parallel contours", "contour")
        self.strategy.addItem("Raster lines", "raster")
        self.direction = QComboBox()
        self.direction.setToolTip("M3: choose hand from remaining material. A full-width first slot has no unique climb/conventional hand.")
        for label, key in (("Machine default", "machine"), ("Climb", "climb"),
                           ("Conventional", "conventional"), ("Meander", "meander")):
            self.direction.addItem(label, key)
        for label, w in (("Stepdown (mm)", self.stepdown), ("Pocket stepover (%)", self.stepover),
                         ("Profile side", self.side), ("Stock to leave (mm)", self.stock),
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
        for key, label in (("low_engagement_feed", "Low (<40%)"),
                           ("standard_engagement_feed", "Standard (40–70%)"),
                           ("high_engagement_feed", "High (>70%, below slot)"),
                           ("slotting_feed", "Slotting (95–100%)")):
            sb = self.spin(0, 300, 0)
            sb.setDecimals(0)
            sb.setSpecialValueText("Tool default")
            sb.setSuffix(" %")
            sb.setToolTip("0 inherits the tool profile. 100% is base tool feed; values above 100% increase it, subject to machine max feed.")
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
        op = Operation(name=kind.title(), kind=kind, stepdown=float(tool.get("max_doc", 1) or 1) if tool else 1)
        if kind == "pocket":
            op.start = Depth("stock_top")
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
        self.last_pick = None
        self.details.setEnabled(op is not None)
        self.b_selection_depths.setVisible(op is not None and op.kind == "pocket")
        if op:
            self.name.setText(op.name)
            self.enabled.setChecked(op.enabled)
            self.geom_label.setText(f"{len(op.geometry)} geometry references")
            self.pick_status.setText("Face picking is active. Click the pocket floor, or choose Select edges for its bounds.")
            self.depth_summary.setText("")
            for key, (source, val, extreme) in self.depth_controls.items():
                d = getattr(op, key)
                source.setCurrentIndex(source.findData(d.source))
                val.setValue(d.value)
                extreme.setCurrentIndex(extreme.findData(d.extreme))
            self.stepdown.setValue(op.stepdown)
            self.stepover.setValue(op.stepover)
            self.side.setCurrentIndex(self.side.findData(op.side))
            self.stock.setValue(op.stock)
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
        op.stepdown, op.stepover = self.stepdown.value(), self.stepover.value()
        op.side, op.stock = self.side.currentData(), self.stock.value()
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
        self.last_pick = result
        ref = result["reference"]
        if self.target.currentData() == "geometry":
            if ref in op.geometry:
                op.geometry.remove(ref)
            else:
                op.geometry.append(ref)
        self.geom_label.setText(f"{len(op.geometry)} geometry references")
        self.pick_status.setText(f"Picked {ref.kind}: Z {result['z_min']:.3f} … {result['z_max']:.3f} mm")
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

    def use_selection_depths(self):
        op = self.operation()
        if op is None or op.kind != "pocket":
            return
        op.start, op.end = Depth("stock_top"), Depth("selection", extreme="min")
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
