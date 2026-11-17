"""Library editor: machines, materials, nozzles and tools (each its own library)."""
from __future__ import annotations

from gcodeproducer.gui.dialogs.dialogs_constants import _HINT
from dataclasses import replace
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabBar,
    QVBoxLayout,
    QWidget,
)
import gcodeproducer.core.workflows.validation as wf
from gcodeproducer.core.libraries.libraries_constants import KIND_LABEL, KINDS
from gcodeproducer.core.libraries.library_set import LibrarySet
from gcodeproducer.core.libraries.profile import Profile
from gcodeproducer.core.libraries.schemas import schema
from gcodeproducer.gui.editors.param_editor import ParamEditor


class LibraryDialog(QDialog):
    def __init__(self, libset: LibrarySet, parent=None, kind: str = "machine", profile_id: str | None = None):
        super().__init__(parent)
        self.libset = libset
        self.setWindowTitle("Libraries")
        self.resize(820, 620)
        self._deleted: list = []

        lay = QVBoxLayout(self)
        self.tabs = QTabBar()
        for k in KINDS:
            self.tabs.addTab(KIND_LABEL[k] + "s")
        self.tabs.currentChanged.connect(lambda _i: self._reload())
        lay.addWidget(self.tabs)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#9aa;")
        lay.addWidget(self.hint)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.lst = QListWidget()
        self.lst.currentRowChanged.connect(self._select)
        ll.addWidget(self.lst, 1)
        row = QHBoxLayout()
        for text, fn in (("New\u2026", self._new), ("Duplicate", self._dup), ("Rename\u2026", self._rename),
                         ("Delete", self._del)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        split.addWidget(left)
        self.editor_area = QScrollArea()
        self.editor_area.setWidgetResizable(True)
        split.addWidget(self.editor_area)
        split.setSizes([260, 560])
        lay.addWidget(split, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.tabs.setCurrentIndex(KINDS.index(kind) if kind in KINDS else 0)
        self._reload(profile_id)
        from gcodeproducer.gui.history.dialog_state import library_history
        self.history = library_history(self)

    def kind(self) -> str:
        return KINDS[self.tabs.currentIndex()]

    def _commit_editor(self):
        editor = self.editor_area.widget()
        if isinstance(editor, ParamEditor):
            editor.commit()

    def _reload(self, select_id: str | None = None):
        self._commit_editor()
        kind = self.kind()
        self.hint.setText(_HINT.get(kind, ""))
        self.lst.blockSignals(True)
        self.lst.clear()
        row = 0
        for i, p in enumerate(self.libset[kind].all()):
            tag = f"   [{wf.short(p.workflow)}]" if kind == "machine" else ""
            it = QListWidgetItem(p.name + tag)
            it.setData(Qt.ItemDataRole.UserRole, p.id)
            self.lst.addItem(it)
            if p.id == select_id:
                row = i
        if self.lst.count():
            self.lst.setCurrentRow(row)
            self.lst.blockSignals(False)
            self._select(row)       # create once, after the complete list is ready
        else:
            self.lst.blockSignals(False)
            self.editor_area.setWidget(QLabel("  No profiles yet \u2014 click New\u2026"))

    def _current(self) -> Profile | None:
        it = self.lst.currentItem()
        if not it:
            return None
        return self.libset[self.kind()].get(it.data(Qt.ItemDataRole.UserRole))

    def _select(self, _row):
        self._commit_editor()   # still bound to the previous profile, not the new list row
        previous = self.editor_area.widget()
        if isinstance(previous, ParamEditor):
            previous.changed.disconnect()  # late focus-out signals must not overwrite the replacement form
        p = self._current()
        if p is None:
            return
        ctx = {"workflow": p.workflow}   # template boxes offer this workflow's variables
        if p.kind == "machine":       # allowed_* multiselects list the consumable libraries
            for k in ("material", "nozzle", "tool"):
                ctx[k] = [q.id for q in self.libset[k].all()]
        params = schema(p.kind, p.workflow)
        if p.kind == "tool":
            from gcodeproducer.core.cam.cam_constants import MATERIALS
            parent = self.parent()
            setup = getattr(getattr(parent, "cam_editor", None), "setup", None)
            active = setup.stock.category if setup is not None and getattr(parent, "workflow", None) == wf.CAM else None
            labels = {m[0]: m[1] for m in MATERIALS}
            if active in labels:
                prefix = active+"_"
                params = [replace(q, group=q.group+" — active CAM material")
                          if q.group.startswith("Cut data:") and q.name.startswith(prefix) else q for q in params]
                self.hint.setText(_HINT["tool"] + f" Active CAM material: {labels[active]}. Its table is marked; "
                                  "materials stay in softest-to-hardest order. Auto depth uses the stock's machining category.")
            else:
                self.hint.setText(_HINT["tool"] + " Cutting tables are per material. Auto depth uses the category "
                                  "selected in CAM Material / stock, not always the first table.")
        editor = ParamEditor(params, p.resolved(), context=ctx)
        editor.changed.connect(lambda vals, pr=p: pr.values.update(vals))
        self.editor_area.setWidget(editor)

    def _new(self):
        self._commit_editor()
        kind = self.kind()
        workflow = wf.FDM
        if kind == "machine":
            labels = [wf.label(w) for w in wf.ALL]
            sel, ok = QInputDialog.getItem(self, "New machine", "Workflow:", labels, 0, False)
            if not ok:
                return
            workflow = wf.ALL[labels.index(sel)]
        name, ok = QInputDialog.getText(self, f"New {kind}", "Name:")
        if ok and name.strip():
            p = self._unique(Profile(kind, name.strip(), workflow=workflow,
                                     values={"auto_cutting_data": True} if kind == "tool" else {}))
            self.libset[kind].add(p)
            self._reload(p.id)

    def _dup(self):
        self._commit_editor()
        p = self._current()
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Duplicate", "New name:", text=p.name + " copy")
        if ok and name.strip():
            q = self._unique(Profile(p.kind, name.strip(), values=dict(p.values), workflow=p.workflow))
            self.libset[p.kind].add(q)
            self._reload(q.id)

    def _rename(self):
        self._commit_editor()
        p = self._current()
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Rename", "Name:", text=p.name)
        if ok and name.strip():
            p.name = name.strip()          # id (file name) stays, so machine references keep working
            self._reload(p.id)

    def _del(self):
        p = self._current()
        if p and QMessageBox.question(self, "Delete", f"Delete '{p.name}'?") == QMessageBox.StandardButton.Yes:
            self.libset[p.kind].remove(p.id)
            self._deleted.append(p)
            self._reload()

    def _unique(self, p: Profile) -> Profile:
        lib = self.libset[p.kind]
        base, n = p.id, 2
        while p.id in lib.ids():
            p.id = f"{base}-{n}"
            n += 1
        return p

    def accept(self):
        self._commit_editor()
        for p in self._deleted:
            lib = self.libset[p.kind]
            if lib.directory:
                f = lib.directory / f"{p.id}.json"
                if f.exists():
                    f.unlink()
        super().accept()
