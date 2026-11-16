"""Two-click construction of model-owned reference outlines."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QComboBox, QDoubleSpinBox,
                             QPushButton, QLabel, QListWidget, QListWidgetItem, QMessageBox)
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.reference_geometry import plane_point
from .editors_constants import REFERENCE_DRAW_MODES


class ReferenceGeometryEditor(QGroupBox):
    changed = pyqtSignal()
    modeRequested = pyqtSignal(str)
    anchorChanged = pyqtSignal(object)

    def __init__(self, setup, parent=None):
        super().__init__("Reference geometry (model-owned)", parent)
        self.setup = setup
        self.drawing = False
        self.first = None
        layout = QVBoxLayout(self)
        self.method = QComboBox()
        for label, *_ in REFERENCE_DRAW_MODES:
            self.method.addItem(label)
        self.method.currentIndexChanged.connect(self._cancel_on_change)
        layout.addWidget(self.method)
        row = QHBoxLayout()
        row.addWidget(QLabel("Drawing plane Z (mm)"))
        self.z = QDoubleSpinBox()
        self.z.setRange(-10000,10000)
        self.z.setDecimals(3)
        self.z.setToolTip("Fixed CAM work coordinates. Reference geometry does not move with later model placement.")
        self.z.valueChanged.connect(self._cancel_on_change)
        row.addWidget(self.z)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.draw = QPushButton("Draw reference")
        self.draw.clicked.connect(self.start)
        row.addWidget(self.draw)
        stop = QPushButton("Stop / cancel")
        stop.clicked.connect(self.cancel)
        row.addWidget(stop)
        delete = QPushButton("Delete selected")
        delete.clicked.connect(self.remove)
        row.addWidget(delete)
        layout.addLayout(row)
        self.items = QListWidget()
        self.items.setMaximumHeight(95)
        layout.addWidget(self.items)
        self.status = QLabel("Draw on the XY plane, then use Select edges/faces to pick the outline. Esc cancels.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.set_setup(setup)

    def set_setup(self, setup):
        self.end_mode()
        self.setup = setup
        self.refresh()
        self.status.setText("Draw on the XY plane, then use Select edges/faces to pick the outline. Esc cancels.")

    def refresh(self):
        self.items.clear()
        for shape in self.setup.reference_shapes:
            item = QListWidgetItem(shape.summary())
            item.setData(Qt.ItemDataRole.UserRole,shape.id)
            self.items.addItem(item)

    def start(self):
        self.end_mode()
        self.drawing = True
        _,kind,method,first,_ = REFERENCE_DRAW_MODES[self.method.currentIndex()]
        self.status.setText(f"Click {first} at Z{self.z.value():g}. Pan/orbit are still available; Esc cancels.")
        self.modeRequested.emit(f"draw_{kind}_{method}")

    def end_mode(self):
        if self.drawing:
            self.status.setText("Drawing stopped. Pick references using Select edges/faces.")
        self.drawing = False
        self.first = None
        self.anchorChanged.emit(None)

    def cancel(self):
        self.end_mode()
        self.status.setText("Drawing stopped. Pick reference geometry using Select edges/faces.")
        self.modeRequested.emit("")

    def _cancel_on_change(self, *_):
        if self.drawing:
            self.cancel()

    def accept_ray(self, origin, direction):
        if not self.drawing:
            return
        point = plane_point(origin,direction,self.z.value())
        if point is None:
            self.status.setText("Drawing plane is edge-on or behind the camera; change the view and click again.")
            return
        _,kind,method,first,second = REFERENCE_DRAW_MODES[self.method.currentIndex()]
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
            shape = ReferenceShape(kind,method,self.first,tuple(point[:2]),self.z.value(),
                                   f"{kind.title()} {number}")
            shape.segment_count()  # scalar guard; polygon creation stays in the compute process
        except ValueError as exc:
            self.status.setText(str(exc)+"; choose another second point.")
            return
        self.setup.reference_shapes.append(shape)
        self.first = None
        self.anchorChanged.emit(None)
        self.refresh()
        self.status.setText(shape.summary()+f". Click {first} for another, or Stop / Esc to select.")
        self.changed.emit()

    def _in_use(self, reference):
        for group in self.setup.groups:
            for operation in group.operations:
                refs = operation.geometry + operation.height_references
                refs += [d.reference for d in (operation.start,operation.end) if d.source == "geometry"]
                if reference in refs:
                    return True
        return False

    def remove(self):
        item = self.items.currentItem()
        if item is None:
            return
        if self.drawing:
            self.cancel()
        ident = item.data(Qt.ItemDataRole.UserRole)
        reference = Reference("drawing",[ident])
        if self._in_use(reference):
            self.status.setText("This reference is used by an operation. Remove its picks and unlink Start/End before deletion.")
            return
        if QMessageBox.question(self, "Delete reference geometry", "Delete this unused reference? This cannot be undone.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        # A queued compute result can add a pick while the confirmation runs its event loop.
        if self._in_use(reference):
            self.status.setText("This reference is now used by an operation; deletion cancelled.")
            return
        self.setup.reference_shapes[:] = [s for s in self.setup.reference_shapes if s.id != ident]
        self.refresh()
        self.status.setText("Reference removed; other reference IDs are unchanged.")
        self.changed.emit()
