"""Section — the one collapsible pane used by every panel (process, model, CAM, view, dialogs)."""
from __future__ import annotations
import os
from PyQt6.QtCore import QSettings, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QSizePolicy, QToolButton, QVBoxLayout, QWidget
from .editors_constants import SECTION_BODY_MARGINS, SECTION_STATE_PREFIX


def _settings():
    return QSettings("GCodeProducer", os.environ.get("GCODEPRODUCER_SETTINGS", "GCodeProducer"))


class Section(QWidget):
    """Collapsible pane: a full-width header button and a body.

    Styled by the application sheet (``sectionHeader`` / ``sectionBody``). Pass a
    ready body widget as ``content``, or omit it and fill :attr:`body` (a
    ``QVBoxLayout``). With a ``key`` the expanded state is remembered in the
    application's Qt settings (the namespace honours ``GCODEPRODUCER_SETTINGS``),
    so a pane reopens the way the user left it.
    """
    toggled = pyqtSignal(bool)

    def __init__(self, title: str, content: QWidget | None = None, expanded: bool = True,
                 parent=None, key: str | None = None, info: str = "", level: int = 0):
        super().__init__(parent)
        self.key = key
        if key:
            saved = _settings().value(SECTION_STATE_PREFIX+key)
            if saved is not None:
                expanded = str(saved).lower() in ("true", "1")
        self.header = QToolButton()
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        # A long title (with its summary) must never widen the dock: it is clipped instead.
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.header.setMinimumWidth(60)
        self.header.setMinimumHeight(26)
        # level 1 = a pane nested in another pane: same behaviour, quieter header
        self.header.setObjectName("sectionHeader" if level == 0 else "subsectionHeader")
        self.header.toggled.connect(self._on_toggle)
        if content is None:
            content = QFrame()
            self.body = QVBoxLayout(content)
            self.body.setContentsMargins(*SECTION_BODY_MARGINS)
        else:
            self.body = content.layout()
        if not content.objectName():
            content.setObjectName("sectionBody" if level == 0 else "subsectionBody")
        self.content = content
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(content)
        self.set_title(title, info)
        self._on_toggle(expanded, emit=False)

    def title(self) -> str:
        return self._title

    def set_title(self, title: str, info: str = "") -> None:
        self._title = title
        text = title.replace("&", "&&")
        if info:
            text += f"   — {info.replace('&', '&&')}"
        self.header.setText(text)

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def _on_toggle(self, on: bool, emit: bool = True):
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.content.setVisible(on)
        if emit:
            if self.key:
                _settings().setValue(SECTION_STATE_PREFIX+self.key, bool(on))
            self.toggled.emit(on)

    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)
