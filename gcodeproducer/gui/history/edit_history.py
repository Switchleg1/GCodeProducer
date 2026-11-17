"""Bounded transactional undo/redo shared by windows and modal editors."""
from copy import deepcopy
from PyQt6 import sip
from PyQt6.QtCore import QObject, QEvent, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QWidget, QAbstractButton, QDialog, QAbstractSpinBox, QLineEdit
from . import widget_state
from .history_constants import HISTORY_LIMIT, INPUT_EVENTS


class EditHistory(QObject):
    changed = pyqtSignal()

    def __init__(self, root, capture=lambda: None, restore=lambda state: None, *, restore_widgets=True):
        super().__init__(root)
        self.root, self.capture_domain, self.restore_domain = root, capture, restore
        self.restore_widgets = restore_widgets
        self.busy = False
        self.entries = []
        self.index = 0
        self._wire_key = str(id(self))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)
        self.undo_action = QAction('Undo', root)
        self.undo_action.setShortcuts([QKeySequence('Ctrl+Z')])
        self.redo_action = QAction('Redo', root)
        self.redo_action.setShortcuts([QKeySequence('Ctrl+Shift+Z'), QKeySequence('Ctrl+Y')])
        for action, slot in ((self.undo_action, self.undo), (self.redo_action, self.redo)):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(slot)
            root.addAction(action)
        self.scan()
        self.current = self.snapshot()
        self._update_actions()
        QApplication.instance().installEventFilter(self)
        if isinstance(root, QDialog):
            root.finished.connect(self.dispose)

    @pyqtSlot()
    def dispose(self, *_):
        self.busy = True
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)

    def snapshot(self):
        # Template editors debounce validation. Keep their bound model and visible
        # text in the same transaction, including immediately-before-Undo input.
        from gcodeproducer.gui.editors.gcode_template_edit import GCodeTemplateEdit
        for editor in self.root.findChildren(GCodeTemplateEdit):
            if editor.window() is self.root and editor._timer.isActive():
                editor._commit()
        return (deepcopy(self.capture_domain()), widget_state.capture(self.root))

    def scan(self):
        """Connect after domain handlers; new/rebuilt controls join on their first input."""
        for w in widget_state.widgets(self.root).values():
            if w.property('_historyOwner') == self._wire_key:
                continue
            w.setProperty('_historyOwner', self._wire_key)
            names = ('visibilityChanged', 'topLevelChanged', 'actionTriggered',
                     'valueChanged', 'currentIndexChanged', 'currentRowChanged', 'currentItemChanged',
                     'itemSelectionChanged', 'itemChanged', 'toggled', 'editingFinished', 'textChanged',
                     'currentChanged')
            if isinstance(w, QAbstractButton):
                names += ('clicked',)
            for name in names:
                signal = getattr(w, name, None)
                if hasattr(signal, 'connect'):
                    signal.connect(self.schedule)

    def eventFilter(self, obj, event):
        typ = event.type()
        # Never inspect QWidget ancestry during construction/destruction events:
        # Qt can deliver those while the underlying C++ widget is only partial.
        if typ not in INPUT_EVENTS and typ != QEvent.Type.ShortcutOverride:
            return False
        if (self.busy or sip.isdeleted(self.root) or not isinstance(obj, QWidget)
                or sip.isdeleted(obj) or obj.window() is not self.root):
            return False
        if typ in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            modifiers = event.modifiers()
            ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            redo = event.key() == Qt.Key.Key_Y or bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            if ctrl and event.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y):
                # Own Ctrl+Z even in text/spin editors: one coherent application history.
                event.accept()
                if typ == QEvent.Type.KeyPress:
                    (self.redo if redo else self.undo)()
                return True
        if typ in INPUT_EVENTS:
            if typ in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
                self.flush()
            self.scan()
            self.schedule()
        return False

    @pyqtSlot()
    def schedule(self, *_):
        playback = getattr(self.root, 'playback', None)
        if playback is not None and playback.is_playing():
            return                         # automatic cursor ticks are not edits
        if not self.busy:
            self._timer.start(0)

    @pyqtSlot()
    def flush(self):
        self._timer.stop()
        if self.busy:
            return
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self.root:
            return                         # dialog edits are local until accepted
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return                         # one command for a complete drag / held spinner
        after = self.snapshot()
        if after != self.current:
            del self.entries[self.index:]
            self.entries.append((self.current, after))
            if len(self.entries) > HISTORY_LIMIT:
                del self.entries[0]
            self.index = len(self.entries)
            self.current = after
            self._update_actions()

    def _apply(self, snapshot):
        self.busy = True
        self._timer.stop()
        try:
            domain, controls = deepcopy(snapshot)
            if self.restore_widgets:
                self.restore_domain(domain)
            else:
                self.restore_domain(domain, controls)
            if self.restore_widgets:
                widget_state.restore(self.root, controls, emit=True, selections_only=True)
                widget_state.restore(self.root, controls, emit=True)
            self.scan()
            # Derived labels/locked calculations may have been recomputed by the adapter.
            self.current = self.snapshot()
        finally:
            self.busy = False
        self._update_actions()

    def commit_focus(self):
        widget = self.root.focusWidget()
        if isinstance(widget, QLineEdit) and isinstance(widget.parent(), QAbstractSpinBox):
            widget = widget.parent()
        if isinstance(widget, QAbstractSpinBox):
            widget.interpretText()
        elif isinstance(widget, QLineEdit):
            widget.editingFinished.emit()

    @pyqtSlot()
    def undo(self):
        self.commit_focus()
        self.flush()
        if self.index:
            self.index -= 1
            self._apply(self.entries[self.index][0])

    @pyqtSlot()
    def redo(self):
        self.commit_focus()
        self.flush()
        if self.index < len(self.entries):
            target = self.entries[self.index][1]
            self.index += 1
            self._apply(target)

    def _update_actions(self):
        self.undo_action.setEnabled(self.index > 0)
        self.redo_action.setEnabled(self.index < len(self.entries))
        self.changed.emit()
