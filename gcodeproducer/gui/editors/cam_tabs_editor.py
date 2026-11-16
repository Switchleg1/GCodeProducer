"""Model-owned holding tab controls, hosted with CAM Material / stock."""

from .editors_constants import TAB_DIRECTIONS
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
)
from gcodeproducer.core.cam.holding_tab import HoldingTab
from .section import Section


class CAMTabsEditor(Section):
    changed = pyqtSignal()
    modeRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Holding tabs", parent=parent, key="model.holding_tabs")
        self.setup = None
        self._loading = False
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(form)
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        self.list.currentRowChanged.connect(self._selected)
        form.addRow(self.list)
        row = QHBoxLayout()
        self.place = QPushButton("Place tabs")
        self.remove = QPushButton("Remove tabs")
        for button, mode in ((self.place, "tab"), (self.remove, "tab_remove")):
            button.setCheckable(True)
            button.toggled.connect(lambda on, m=mode: self._mode(m, on))
            row.addWidget(button)
        self.delete = QPushButton("Delete selected")
        self.delete.clicked.connect(self.delete_selected)
        row.addWidget(self.delete)
        form.addRow(row)
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)
        self.enabled.toggled.connect(self._edit)
        form.addRow(self.enabled)
        self.width = self.spin(4)
        self.height = self.spin(4)
        self.width.valueChanged.connect(self._edit)
        self.height.valueChanged.connect(self._edit)
        self.direction = QComboBox()
        for label, key in TAB_DIRECTIONS:
            self.direction.addItem(label, key)
        self.direction.currentIndexChanged.connect(self._edit)
        form.addRow("Width (mm)", self.width)
        form.addRow("Height above stock bottom (mm)", self.height)
        form.addRow("Extend to material edge", self.direction)
        self.status = QLabel("Click a side wall to place a rail to an X/Y material edge. "
                             "Width/height/direction also set the next tab. Esc leaves placement.")
        self.status.setWordWrap(True)
        form.addRow(self.status)

    @staticmethod
    def spin(value):
        w = QDoubleSpinBox()
        w.setRange(.05, 10000)
        w.setDecimals(3)
        w.setValue(value)
        w.setKeyboardTracking(False)
        return w

    def set_setup(self, setup):
        if self.setup is setup:
            return
        self.end_mode()
        self.setup = setup
        self.rebuild()

    def _mode(self, mode, on):
        other = self.remove if mode == "tab" else self.place
        if on:
            other.blockSignals(True); other.setChecked(False); other.blockSignals(False)
        self.modeRequested.emit(mode if on else "")

    def end_mode(self):
        for b in (self.place, self.remove):
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def rebuild(self, selected=-1):
        self.list.blockSignals(True)
        self.list.clear()
        for i, tab in enumerate(self.setup.tabs if self.setup else []):
            self.list.addItem(f"Tab {i+1}: {tab.width:g} × {tab.height:g} mm, {tab.direction}"
                              + (" (off)" if not tab.enabled else ""))
        self.list.setCurrentRow(selected)
        self.list.blockSignals(False)
        self.delete.setEnabled(selected >= 0)

    def _selected(self, index):
        self.delete.setEnabled(index >= 0)
        if self.setup is None or not 0 <= index < len(self.setup.tabs):
            return
        tab = self.setup.tabs[index]
        self._loading = True
        self.width.setValue(tab.width)
        self.height.setValue(tab.height)
        self.direction.setCurrentIndex(self.direction.findData(tab.direction))
        self.enabled.setChecked(tab.enabled)
        self._loading = False

    def _edit(self, *_):
        index = self.list.currentRow()
        if self._loading or self.setup is None or not 0 <= index < len(self.setup.tabs):
            return
        tab = self.setup.tabs[index]
        tab.width, tab.height = self.width.value(), self.height.value()
        tab.direction, tab.enabled = self.direction.currentData(), self.enabled.isChecked()
        self.rebuild(index)
        self.changed.emit()

    def accept_pick(self, result):
        if self.setup is None:
            return
        if not result:
            self.status.setText("Nothing hit. Click a visible side wall to add, or a tab rail to remove.")
            return
        if "error" in result:
            self.status.setText(result["error"])
            return
        if "remove" in result:
            index = result["remove"]
            if 0 <= index < len(self.setup.tabs):
                del self.setup.tabs[index]
                self.rebuild()
        else:
            tab = HoldingTab(result["triangle"], result["barycentric"], self.width.value(), self.height.value(),
                             self.direction.currentData(), True)
            self.setup.tabs.append(tab)
            self.rebuild(len(self.setup.tabs)-1)
            self._selected(len(self.setup.tabs)-1)
        self.status.setText("Holding tabs saved with this model. Each enabled rail is protected in every operation.")
        self.changed.emit()

    def delete_selected(self):
        i = self.list.currentRow()
        if self.setup and 0 <= i < len(self.setup.tabs):
            del self.setup.tabs[i]
            self.rebuild()
            self.changed.emit()
