"""Model-owned reference outlines: draw, select, move, resize and delete."""
import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QWidget)
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.cam import registration_pins as pins
from gcodeproducer.core.cam.cam_constants import PIN_CORNERS
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
    previewChanged = pyqtSignal(object, str)   # outline line pairs and readout of the shape at the mouse
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
        self.centre_label = QLabel("Center")
        edit.addRow(self.centre_label, centre)
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
        seen = set()
        selected_group = next((s.group for s in self.setup.reference_shapes if s.id == select), None)
        for shape in self.setup.reference_shapes:
            if shape.group:
                if shape.group in seen:
                    continue
                seen.add(shape.group)
            item = QListWidgetItem("Pins" if shape.group else shape.summary())
            item.setData(Qt.ItemDataRole.UserRole, shape.id)
            self.items.addItem(item)
            if shape.id == select or (shape.group and shape.group == selected_group):
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
        if shape.group:
            group = pins.members(self.setup.reference_shapes, shape.group)
            centers = np.array([pin.dimensions()[0] for pin in group])
            center = np.ptp(centers, axis=0)  # full centre-to-centre spacing, not one corner's XY
        self.centre_label.setText("Pin spacing" if shape.group else "Center")
        for key in ('x', 'y'):
            self.fields[key].setMinimum(.001 if shape.group else -10000)
            self.fields[key].setToolTip('Centre-to-centre distance between pins (mm)' if shape.group else '')
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
        self.previewChanged.emit((), "")

    def cancel(self):
        self.end_mode()
        self.modeRequested.emit("")

    def _cancel_drawing(self, *_):
        if self.mode == "draw":
            self.cancel()

    # ---------------------------------------------------------- viewport hover
    def hover_ray(self, origin, direction):
        """Preview what a click here would make: its outline in the view, its position and size as text."""
        shapes, readout = self.preview(origin, direction)
        shapes = [] if shapes is None else shapes if isinstance(shapes, list) else [shapes]
        edges = [np.stack((line[:-1], line[1:]), axis=1).reshape(-1, 3) for line in (s.polyline() for s in shapes)]
        self.previewChanged.emit(np.vstack(edges) if edges else (), readout)

    def preview(self, origin, direction):
        """(shape a click at this ray would make or None, readout text)."""
        if self.mode == "draw":
            point = plane_point(origin, direction, self.z.value())
            if point is None:
                return None, ""
            _, kind, method, first, second = REFERENCE_DRAW_MODES[self.method.currentIndex()]
            if kind == "pins":
                return self._preview_pins(point)
            if self.first is None:
                return None, f"{first.capitalize()}: X{point[0]:.3f} Y{point[1]:.3f} Z{self.z.value():g}"
            try:
                shape = ReferenceShape(kind, method, self.first, tuple(point[:2]), self.z.value(), "preview")
                shape.segment_count()
            except ValueError:
                return None, f"{second.capitalize()}: X{point[0]:.3f} Y{point[1]:.3f} (too small)"
            return shape, self.readout(shape)
        current = self.current()
        if self.mode not in ("move", "resize") or current is None:
            return None, ""
        point = plane_point(origin, direction, current.z)
        if point is None:
            return None, ""
        import copy
        # (A pin's whole set follows it: preview all four.)
        shapes = [copy.copy(s) for s in self.setup.reference_shapes if s is current or (current.group and s.group == current.group)]
        shape = next(s for s in shapes if s.id == current.id)
        center, _ = shape.dimensions()
        try:
            if self.mode == "move":
                shape.set_geometry(center=point[:2])
            elif shape.kind == "circle":
                shape.set_geometry(size=float(np.linalg.norm(point[:2]-center)))
            else:
                shape.set_geometry(size=np.abs(point[:2]-center))
            if shape.group:
                pins.sync(shapes, shape, pins.stock_centre(self.setup))
                return shapes, self.pin_readout(shapes)
        except ValueError:
            return None, ""
        return shape, self.readout(shape)

    def _preview_pins(self, point):
        """Registration pins: first the box about the stock's centre, then the four circles."""
        centre = pins.stock_centre(self.setup)
        if centre is None:
            return None, REFERENCE_HINTS["no_stock"]
        z = self.z.value()
        try:
            if self.first is None:
                box = ReferenceShape("rectangle", "center", tuple(centre), tuple(point[:2]), z, "preview")
                _, size = box.dimensions()
                return box, (f"Pin box about the stock centre X{centre[0]:.3f} Y{centre[1]:.3f} \u2022 "
                             f"Width {2*size[0]:.3f} \u00d7 Height {2*size[1]:.3f} mm")
            shapes = pins.make_pins(centre, self.first, self._pin_radius(centre, point), z)
            box = ReferenceShape("rectangle", "center", tuple(centre), self.first, z, "preview")
            return [box, *shapes], self.pin_readout(shapes)
        except ValueError:
            return None, ""

    def _pin_radius(self, centre, point):
        """The pin size the mouse gives: its distance from the nearest corner of the pin box."""
        half = np.abs(np.asarray(self.first, float)-centre)
        corners = centre+half*np.asarray(PIN_CORNERS, float)
        return float(np.min(np.linalg.norm(corners-np.asarray(point[:2], float), axis=1)))

    def pin_readout(self, shapes):
        centre = pins.stock_centre(self.setup)
        hx, hy, radius = pins.box_of(shapes, centre)
        return (f"4 pins \u2022 Diameter {2*radius:.3f} mm \u2022 Box {2*hx:.3f} \u00d7 {2*hy:.3f} mm "
                f"about the stock centre X{centre[0]:.3f} Y{centre[1]:.3f} Z{shapes[0].z:g}")

    @staticmethod
    def readout(shape):
        """Position and size of a shape: centre, then diameter (circle) or width x height (rectangle)."""
        center, size = shape.dimensions()
        where = f"Center X{center[0]:.3f} Y{center[1]:.3f} Z{shape.z:g}"
        if shape.kind == "circle":
            return f"{where} \u2022 Diameter {2*size:.3f} mm"
        return f"{where} \u2022 Width {2*size[0]:.3f} \u00d7 Height {2*size[1]:.3f} mm"

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
        if kind == "pins":
            return self._accept_pins(point, first)
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
        self.previewChanged.emit((), "")
        self.refresh(shape.id)
        self.status.setText(shape.summary()+f". Click {first} for another; Draw or Esc to finish.")
        self.changed.emit()

    def _accept_pins(self, point, first):
        """Two clicks: a corner of the box about the stock's centre, then the pin size."""
        centre = pins.stock_centre(self.setup)
        if centre is None:
            self.status.setText(REFERENCE_HINTS["no_stock"])
            return
        if self.first is None:
            if not np.all(np.abs(point[:2]-centre) > 1e-6):
                self.status.setText("The pin box needs a width and a height; click away from the stock's centre lines.")
                return
            self.first = tuple(point[:2])
            self.anchorChanged.emit(point)
            self.status.setText("Pin box set. Move out from a corner and click to set the pin size.")
            return
        try:
            shapes = pins.make_pins(centre, self.first, self._pin_radius(centre, point), self.z.value(),
                                    pins.next_number(self.setup.reference_shapes))
            for shape in shapes:
                shape.segment_count()
        except ValueError as exc:
            self.status.setText(str(exc)+"; click further from the corner.")
            return
        self.setup.reference_shapes.extend(shapes)
        self.first = None
        self.anchorChanged.emit(None)
        self.previewChanged.emit((), "")
        self.refresh(shapes[0].id)
        self.status.setText(self.pin_readout(shapes)+f". Edit one pin's diameter or position to change all four. "
                            f"Click {first} for another set; Draw or Esc to finish.")
        self.changed.emit()

    def _sync_pins(self, shape):
        """A pin's set follows it (raises ValueError, shape unchanged by the caller, if it cannot)."""
        if shape.group:
            pins.sync(self.setup.reference_shapes, shape, pins.stock_centre(self.setup))

    def _reshape(self, origin, direction):
        shape = self.current()
        if shape is None:
            return self.cancel()
        point = plane_point(origin, direction, shape.z)
        if point is None:
            self.status.setText(REFERENCE_HINTS["edge_on"])
            return
        center, size = shape.dimensions()
        try:
            if self.mode == "move":
                shape.set_geometry(center=point[:2])
            elif shape.kind == "circle":
                shape.set_geometry(size=float(np.linalg.norm(point[:2]-center)))
            else:
                shape.set_geometry(size=np.abs(point[:2]-center))
            try:
                self._sync_pins(shape)
            except ValueError:
                shape.set_geometry(center=center, size=size)
                raise
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
        before = (*shape.dimensions(), shape.z)
        try:
            at = (f['x'], f['y'])
            if shape.group:
                centre = pins.stock_centre(self.setup)
                if centre is None:
                    raise ValueError(REFERENCE_HINTS['no_stock'])
                at = centre + np.asarray(PIN_CORNERS[0])*np.asarray(at)/2
            shape.set_geometry(at, size, f["z"])
            try:
                self._sync_pins(shape)
            except ValueError:
                shape.set_geometry(*before)
                raise
        except ValueError as exc:
            self.status.setText(str(exc))
            self._selected()
            return
        self.refresh(shape.id)
        self.changed.emit()

    # ---------------------------------------------------------- delete
    def _in_use(self, reference):
        for group in [*self.setup.groups, *getattr(self.setup, "other_groups", [])]:   # both sides
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
        # A registration pin goes with its whole set.
        doomed = [s for s in self.setup.reference_shapes if s is shape or (shape.group and s.group == shape.group)]
        in_use = lambda: any(self._in_use(Reference("drawing", [s.id])) for s in doomed)
        if in_use():
            self.status.setText("This reference is used by an operation. Remove its picks and unlink Start/End before deletion.")
            return
        what = (f"the {len(doomed)} registration pins of this set" if len(doomed) > 1
                else f"unused reference '{shape.name or shape.kind}'")
        if not self.confirm(self, f"Delete {what}? This cannot be undone."):
            return
        # A queued compute result can add a pick while the confirmation runs its event loop.
        if in_use():
            self.status.setText("This reference is now used by an operation; deletion cancelled.")
            return
        gone = {s.id for s in doomed}
        self.setup.reference_shapes[:] = [s for s in self.setup.reference_shapes if s.id not in gone]
        self.refresh()
        self.status.setText("Reference removed; other reference IDs are unchanged.")
        self.changed.emit()
