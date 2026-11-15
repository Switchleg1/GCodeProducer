"""CAM stock controls, hosted in the same UI slot as FDM Support."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QGroupBox, QFormLayout, QLineEdit, QDoubleSpinBox,
                             QPushButton, QLabel)


class StockEditor(QGroupBox):
    changed = pyqtSignal()
    autoRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Material / stock", parent)
        self.stock = None
        self.fields = {}
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._edit)
        form.addRow("Material", self.name)
        for key, label, lo, hi, unit in (
            ("density", "Density", 0, 100, " g/cm³"),
            ("margin", "Auto margin (sides / bottom)", 0, 1000, " mm"),
            ("x", "Minimum X", -10000, 10000, " mm"),
            ("y", "Minimum Y", -10000, 10000, " mm"),
            ("top", "Surface Z", -10000, 10000, " mm"),
            ("width", "Width X", 0, 10000, " mm"),
            ("depth", "Depth Y", 0, 10000, " mm"),
            ("height", "Thickness Z", 0, 10000, " mm"),
        ):
            sb = QDoubleSpinBox()
            sb.setRange(lo, hi)
            sb.setDecimals(3)
            sb.setSuffix(unit)
            sb.setKeyboardTracking(False)
            sb.valueChanged.connect(self._edit)
            self.fields[key] = sb
            form.addRow(label, sb)
        self.auto = QPushButton("Auto — fit material to part")
        self.auto.clicked.connect(self.autoRequested)
        form.addRow(self.auto)
        self.info = QLabel("Auto keeps the stock surface at Z0 (or above a raised part), "
                           "adds margin on each XY side and beneath the part. "
                           "Density is descriptive; feeds and speeds remain on the tools.")
        self.info.setWordWrap(True)
        form.addRow(self.info)
        self.size_info = QLabel("")
        self.size_info.setWordWrap(True)
        form.addRow(self.size_info)

    def set_stock(self, stock):
        self.stock = stock
        self.name.setText(stock.material)
        for key, sb in self.fields.items():
            sb.blockSignals(True)
            sb.setValue(getattr(stock, key))
            sb.blockSignals(False)
        self._summary()

    def _summary(self):
        s = self.stock
        if s and s.allocated:
            volume = s.width * s.depth * s.height / 1000
            self.size_info.setText(f"{volume:g} cm³ • {volume*s.density:g} g • bottom Z{s.top-s.height:g}")
        else:
            self.size_info.setText("No material allocated — use Auto or enter dimensions.")

    def _edit(self, *_):
        if self.stock is None:
            return
        self.stock.material = self.name.text()
        for key, sb in self.fields.items():
            setattr(self.stock, key, sb.value())
        self._summary()
        self.changed.emit()
