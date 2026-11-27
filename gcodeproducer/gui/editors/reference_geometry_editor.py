"""Model-owned reference outlines: draw, select, move, resize and delete."""
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QWidget)
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.reference_geometry import plane_point
from .editors_constants import REFERENCE_DRAW_MODES, REFERENCE_MODES, REFERENCE_HINTS
from .section import Section
from gcodeproducer.gui.controls import NumberBox


def default_confirm(parent, text):
    return QMessageBox.question(parent, "Delete reference geometry", text,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


class ReferenceGeometryEditor(Section):
    """A collapsible pane in the Model dock (CAM). Modes are viewport click tools.

    *Draw*, *Move* and *Resize* are checkable: the active one is highlighted,
    clicking it again or pressing Esc in the view ends it. Only one tool is active.
    """
    changed = pyqtSignal()
    modeRequested = pyqtSignal(str)
    anchorChanged = pyqtSignal(object)
    selectionChanged = pyqtSignal()

    def __init__(self, setup, parent=None):
        super().__init__("Reference geometry", parent=parent, key="model.reference_geometry")
        self.setup = setup
        self.mode = ""                  # "", "draw", "move", "resize"
        self.first = None
        self._loading = False
        # ``confirm(parent, text) -> bool``; the main window replaces it with a
        # message that can be remembered (Settings -> Messages).
        self.confirm = default_confirm
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(form)
        self.method = QComboBox()
        for label, *_ in REFERENCE_DRAW_MODES:
            self.method.addItem(label)
        self.method.currentIndexChanged.connect(self._cancel_drawing)
        form.addRow("New shape", self.method)
        self.z = NumberBox(-10000, 10000, suffix=" mm",
                           tooltip="Z of new shapes. Fixed CAM work coordinates: references do not follow later "
                                   "model placement.")
        self.z.valueChanged.connect(self._cancel_drawing)
        form.addRow("Drawing plane Z", self.z)
        self.items = QListWidget()
        self.items.setMaximumHeight(95)
        self.items.currentRowChanged.connect(self._selected)
        self.body.addWidget(self.items)
        row = QHBoxLayout()
        self.buttons = {}
        for mode, (label, tip) in REFERENCE_MODES.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.toggled.connect(lambda on, m=mode: self._toggle(m, on))
            self.buttons[mode] = button
            row.addWidget(button)
        self.draw = self.buttons["draw"]
        self.delete = QPushButton("Delete selected")
        self.delete.clicked.connect(self.remove)
        row.addWidget(self.delete)
        self.body.addLayout(row)
        # Numeric move / resize of the selected shape
        self.editor = QWidget()
        edit = QFormLayout(self.editor)
        edit.setContentsMargins(0, 0, 0, 0)
        self.fields = {}

        def spin(key, lo):
            sb = NumberBox(lo, 10000, tracking=False)
            sb.valueChanged.connect(self._edit)
            self.fields[key] = sb
            return sb
        centre = QHBoxLayout()
        for key, prefix in (("x", "X "), ("y", "Y "), ("z", "Z ")):
            centre.addWidget(spin(key, -10000))
            self.fields[key].setPrefix(prefix)
        edit.addRow("Center", centre)
        size = QHBoxLayout()
        for key, prefix in (("a", "W "), ("b", "H ")):
            size.addWidget(spin(key, .001))
            self.fields[key].setPrefix(prefix)
        self.size_label = QLabel("Size")
        edit.addRow(self.size_label, size)
        self.body.addWidget(self.editor)
        self.status = QLabel(REFERENCE_HINTS["idle"])
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.set_setup(setup)

    # -------------------------------------------------------------- state
    @property
    def drawing(self):
        return self.mode == "draw"

    def set_setup(self, setup):
        self.end_mode()
        self.setup = setup
        self.refresh()
        self.status.setText(REFERENCE_HINTS["idle"])

    def refresh(self, select=None):
        current = self.current()
        select = select if select is not None else (current.id if current else None)
        self.items.blockSignals(True)
        self.items.clear()
        for shape in self.setup.reference_shapes:
            item = QListWidgetItem(shape.summary())
            item.setData(Qt.ItemDataRole.UserRole, shape.id)
            self.items.addItem(item)
            if shape.id == select:
                self.items.setCurrentItem(item)
        self.items.blockSignals(False)
        self._selected()

    def current(self):
        item = self.items.currentItem()
        ident = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return next((s for s in self.setup.reference_shapes if s.id == ident), None)

    def _selected(self, *_):
        shape = self.current()
        if not self._loading:
            self.selectionChanged.emit()
        self.editor.setEnabled(shape is not None)
        self.delete.setEnabled(shape is not None)
        for mode in ("move", "resize"):
            self.buttons[mode].setEnabled(shape is not None)
        if shape is None:
            if self.mode in ("move", "resize"):
                self.cancel()
            return
        center, size = shape.dimensions()
        circle = shape.kind == "circle"
        self._loading = True
        for key, value in (("x", center[0]), ("y", center[1]), ("z", shape.z),
                           ("a", 2*size if circle else 2*size[0]), ("b", 0 if circle else 2*size[1])):
            self.fields[key].setValue(value)
        self.fields["a"].setPrefix("D " if circle else "W ")
        self.fields["b"].setVisible(not circle)
        self.size_label.setText("Diameter" if circle else "Size")
        self._loading = False

    # ---------------------------------------------------------- modes
    def _toggle(self, mode, on):
        if self._loading:
            return
        if on:
            self.start(mode)
        elif self.mode == mode:
            self.cancel()

    def start(self, mode="draw"):
        if mode != "draw" and self.current() is None:
            self._set_checked("")
            return
        self.end_mode()
        self.mode = mode
        self._set_checked(mode)
        if mode == "draw":
            _, kind, method, first, _ = REFERENCE_DRAW_MODES[self.method.currentIndex()]
            self.status.setText(f"Click {first} at Z{self.z.value():g}. "+REFERENCE_HINTS["leave"])
            self.modeRequested.emit(f"sketch_draw_{kind}_{method}")
        else:
            self.status.setText(REFERENCE_HINTS[mode]+" "+REFERENCE_HINTS["leave"])
            self.modeRequested.emit("sketch_"+mode)

    def _set_checked(self, mode):
        self._loading = True
        for key, button in self.buttons.items():
            button.setChecked(key == mode)
        self._loading = False

    def end_mode(self):
        """Leave any tool without emitting (the caller changes the view mode itself)."""
        if self.mode:
            self.status.setText(REFERENCE_HINTS["idle"])
        self.mode = ""
        self.first = None
        self._set_checked("")
        self.anchorChanged.emit(None)

    def cancel(self):
        self.end_mode()
        self.modeRequested.emit("")

    def _cancel_drawing(self, *_):
        if self.mode == "draw":
            self.cancel()

    # ---------------------------------------------------------- viewport clicks
    def accept_ray(self, origin, direction):
        if self.mode in ("move", "resize"):
            return self._reshape(origin, direction)
        if self.mode != "draw":
            return
        point = plane_point(origin, direction, self.z.value())
        if point is None:
            self.status.setText(REFERENCE_HINTS["edge_on"])
            return
        _, kind, method, first, second = REFERENCE_DRAW_MODES[self.method.currentIndex()]
        if self.first is None:
            self.first = tuple(point[:2])
            self.anchorChanged.emit(point)
            self.status.setText(f"First point {point[0]:.3f}, {point[1]:.3f}. Click {second}.")
            return
        number = len(self.setup.reference_shapes)+1
        names = {s.name for s in self.setup.reference_shapes}
        while f"{kind.title()} {number}" in names:
            number += 1
        try:
            shape = ReferenceShape(kind, method, self.first, tuple(point[:2]), self.z.value(), f"{kind.title()} {number}")
            shape.segment_count()  # scalar guard; polygon creation stays in the compute process
        except ValueError as exc:
            self.status.setText(str(exc)+"; choose another second point.")
            return
        self.setup.reference_shapes.append(shape)
        self.first = None
        self.anchorChanged.emit(None)
        self.refresh(shape.id)
        self.status.setText(shape.summary()+f". Click {first} for another; Draw or Esc to finish.")
        self.changed.emit()

    def _reshape(self, origin, direction):
        shape = self.current()
        if shape is None:
            return self.cancel()
        point = plane_point(origin, direction, shape.z)
        if point is None:
            self.status.setText(REFERENCE_HINTS["edge_on"])
            return
        center, _ = shape.dimensions()
        try:
            if self.mode == "move":
                shape.set_geometry(center=point[:2])
            elif shape.kind == "circle":
                shape.set_geometry(size=float(np.linalg.norm(point[:2]-center)))
            else:
                shape.set_geometry(size=np.abs(point[:2]-center))
        except ValueError as exc:
            self.status.setText(f"{exc}; click another point.")
            return
        self.refresh(shape.id)
        self.status.setText(shape.summary()+". "+REFERENCE_HINTS[self.mode]+" "+REFERENCE_HINTS["leave"])
        self.changed.emit()

    # ---------------------------------------------------------- numeric edit
    def _edit(self, *_):
        shape = self.current()
        if self._loading or shape is None:
            return
        f = {key: sb.value() for key, sb in self.fields.items()}
        size = f["a"]/2 if shape.kind == "circle" else (f["a"]/2, f["b"]/2)
        try:
            shape.set_geometry((f["x"], f["y"]), size, f["z"])
        except ValueError as exc:
            self.status.setText(str(exc))
            self._selected()
            return
        self.refresh(shape.id)
        self.changed.emit()

    # ---------------------------------------------------------- delete
    def _in_use(self, reference):
        for group in self.setup.groups:
            for operation in group.operations:
                refs = operation.geometry + operation.height_references
                refs += [d.reference for d in (operation.start, operation.end) if d.source == "geometry"]
                if reference in refs:
                    return True
        return False

    def remove(self):
        shape = self.current()
        if shape is None:
            return
        if self.mode:
            self.cancel()
        reference = Reference("drawing", [shape.id])
        if self._in_use(reference):
            self.status.setText("This reference is used by an operation. Remove its picks and unlink Start/End before deletion.")
            return
        if not self.confirm(self, f"Delete unused reference '{shape.name or shape.kind}'? This cannot be undone."):
            return
        # A queued compute result can add a pick while the confirmation runs its event loop.
        if self._in_use(reference):
            self.status.setText("This reference is now used by an operation; deletion cancelled.")
            return
        self.setup.reference_shapes[:] = [s for s in self.setup.reference_shapes if s.id != shape.id]
        self.refresh()
        self.status.setText("Reference removed; other reference IDs are unchanged.")
        self.changed.emit()
