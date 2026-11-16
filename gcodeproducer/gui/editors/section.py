"""Section — editors subsystem."""
from __future__ import annotations
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

class Section(QWidget):
    """Collapsible section: a header button and a content widget."""
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, content: QWidget, expanded: bool = False, parent=None):
        super().__init__(parent)
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.setMinimumHeight(26)
        self.header.setObjectName("sectionHeader")
        self.header.toggled.connect(self._on_toggle)
        self.content = content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(content)
        self.set_title(title)
        self._on_toggle(expanded, emit=False)

    def set_title(self, title: str, info: str = "") -> None:
        self._title = title
        text = title.replace("&", "&&")
        if info:
            text += f"   — {info.replace('&', '&&')}"
        self.header.setText(text)

    def _on_toggle(self, on: bool, emit: bool = True):
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.content.setVisible(on)
        if emit:
            self.toggled.emit(on)


    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)
