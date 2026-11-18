"""Widget mementos, including selection and check states, across rebuilt forms."""
from PyQt6.QtCore import QSignalBlocker, Qt, QModelIndex, QItemSelectionModel
from PyQt6.QtWidgets import (QWidget, QAbstractButton, QComboBox, QSpinBox, QDoubleSpinBox,
                            QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTreeWidget,
                            QTabBar, QScrollBar, QMenu, QDialog, QMainWindow, QAbstractItemView)
from .history_constants import DIRECT_RESTORE_SETTERS, SELECTION_STATES, SIMPLE_WIDGET_STATES


def widgets(root):
    """Stable structural addresses; never descend into a control's Qt internals."""
    def walk(parent, path):
        counts = {}
        for child in parent.children():
            if not isinstance(child, QWidget) or isinstance(child, (QMenu, QScrollBar, QDialog)):
                continue
            if child.property('historyIgnore'):
                continue
            # Dock tab bars are QMainWindow implementation details. restoreState()
            # replaces them using deferred deletion; recording the obsolete bars
            # would invent an edit on the next event-loop turn and destroy Redo.
            if isinstance(parent, QMainWindow) and isinstance(child, QTabBar):
                continue
            tag = (type(child).__name__, child.objectName())
            index = counts.get(tag, 0)
            counts[tag] = index + 1
            key = path + ((tag, index),)
            yield key, child
            if not isinstance(child, (QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit,
                                      QPlainTextEdit, QTextEdit, QAbstractItemView, QTabBar)):
                yield from walk(child, key)
    return dict(walk(root, ()))


def tree_items(tree):
    def walk(parent, path=()):
        for i in range(parent.childCount()):
            item = parent.child(i)
            key = path + (i,)
            yield key, item
            yield from walk(item, key)
    return dict(walk(tree.invisibleRootItem()))


def index_path(index):
    path = ()
    while index.isValid():
        path = ((index.row(), index.column()),) + path
        index = index.parent()
    return path


def model_index(model, path):
    index = QModelIndex()
    for row, column in path:
        index = model.index(row, column, index)
    return index


def capture(root):
    out = {}
    for key, w in widgets(root).items():
        for types, kind, getter in SIMPLE_WIDGET_STATES:
            if isinstance(w, types):
                out[key] = (kind, getattr(w, getter)())
                break
        else:
            value = _capture_complex(w)
            if value is not None:
                out[key] = value
    return out


def _capture_complex(w):
    if isinstance(w, QAbstractButton) and w.isCheckable():
        return ('check', w.isChecked())
    if isinstance(w, QLineEdit) and not w.isReadOnly():
        return ('text', w.text())
    if isinstance(w, (QPlainTextEdit, QTextEdit)) and not w.isReadOnly():
        return ('plain', w.toPlainText())
    if isinstance(w, QListWidget):
        return ('list', w.currentRow(), tuple((i.isSelected(), i.checkState().value)
                    for i in (w.item(j) for j in range(w.count()))))
    if isinstance(w, QTreeWidget):
        items = tree_items(w)
        return ('tree', next((p for p, it in items.items() if it is w.currentItem()), None),
                tuple((p, it.isSelected(), it.isExpanded(), tuple(it.checkState(c).value
                       for c in range(w.columnCount()))) for p, it in items.items()))
    if isinstance(w, QAbstractItemView) and w.selectionModel() is not None:
        return ('view', index_path(w.currentIndex()),
                tuple(index_path(i) for i in w.selectionModel().selectedIndexes()))
    return None


def restore(root, state, *, emit=False, selections_only=False):
    """Selections first: their callbacks may replace forms. Values then target the new form."""
    controls = widgets(root)
    for key, value in state.items():
        kind, *data = value
        if selections_only != (kind in SELECTION_STATES):
            continue
        w = (widgets(root) if selections_only else controls).get(key)
        if w is None:
            continue
        blocker = None if emit else QSignalBlocker(w)
        try:
            setter = DIRECT_RESTORE_SETTERS.get(kind)
            if setter is not None:
                getattr(w, setter)(data[0])
            elif kind == 'check':
                w.setChecked(data[0])
                if not emit and w.objectName() in ('sectionHeader', 'subsectionHeader'):
                    w.parent()._on_toggle(data[0])
            elif kind == 'text':
                w.setText(data[0])
                if emit:
                    w.editingFinished.emit()
            elif kind == 'plain':
                if w.toPlainText() != data[0]:
                    w.setPlainText(data[0])
            elif kind == 'list':
                w.setCurrentRow(data[0])
                for j, (selected, check) in enumerate(data[1][:w.count()]):
                    w.item(j).setSelected(selected)
                    w.item(j).setCheckState(Qt.CheckState(check))
            elif kind == 'view' and w.model() is not None:
                w.setCurrentIndex(model_index(w.model(), data[0]))
                selection = w.selectionModel()
                selection.clearSelection()
                for path in data[1]:
                    selection.select(model_index(w.model(), path), QItemSelectionModel.SelectionFlag.Select)
            elif kind == 'tree':
                items = tree_items(w)
                w.setCurrentItem(items.get(data[0]))
                for path, selected, expanded, checks in data[1]:
                    item = items.get(path)
                    if item is not None:
                        item.setSelected(selected)
                        item.setExpanded(expanded)
                        for c, check in enumerate(checks):
                            item.setCheckState(c, Qt.CheckState(check))
        finally:
            del blocker
