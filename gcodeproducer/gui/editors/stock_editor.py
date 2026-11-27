"""CAM stock controls, hosted in the same UI slot as FDM Support."""

from .editors_constants import STOCK_FIELDS
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
)
from gcodeproducer.gui.controls import NumberBox


class StockEditor(QWidget):
    """Two collapsible panes: Material / stock and Holding tabs."""
    changed = pyqtSignal()
    autoRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from .section import Section
        self.stock = None
        self.fields = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(3)
        self.section = Section("Material / stock", key="model.material_stock")
        outer.addWidget(self.section)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.section.body.addLayout(form)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._edit)
        self.name.textEdited.connect(self._edit)
        form.addRow("Material description", self.name)
        from gcodeproducer.core.cam.cam_constants import MATERIALS
        self.category = QComboBox()
        for key,label,_,_ in MATERIALS:self.category.addItem(label,key)
        self.category.currentIndexChanged.connect(self._edit)
        form.addRow("Machining material",self.category)
        for key, label, lo, hi, unit in STOCK_FIELDS:
            sb = NumberBox(lo, hi, suffix=unit, tracking=False)
            sb.valueChanged.connect(self._edit)
            self.fields[key] = sb
            form.addRow(label, sb)
        self.auto = QPushButton("Auto — fit material to part")
        self.auto.clicked.connect(self.autoRequested)
        form.addRow(self.auto)
        self.info = QLabel("Auto keeps the stock surface at Z0 (or above a raised part), "
                           "adds margin on each XY side and beneath the part. "
                           "Density is descriptive; the machining category selects per-tool SFM, chip load and axial defaults.")
        self.info.setWordWrap(True)
        form.addRow(self.info)
        self.size_info = QLabel("")
        self.size_info.setWordWrap(True)
        form.addRow(self.size_info)
        from gcodeproducer.gui.editors.cam_tabs_editor import CAMTabsEditor
        self.tabs = CAMTabsEditor()
        outer.addWidget(self.tabs)

    def set_stock(self, stock):
        self.stock = stock
        self.name.setText(stock.material)
        self.category.blockSignals(True)
        self.category.setCurrentIndex(self.category.findData(stock.category))
        self.category.blockSignals(False)
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
        self.stock.category = self.category.currentData()
        for key, sb in self.fields.items():
            setattr(self.stock, key, sb.value())
        self._summary()
        self.changed.emit()
