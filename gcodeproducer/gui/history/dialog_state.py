"""Small domain adapters for modal editors; Cancel never commits their history."""
import copy
from gcodeproducer.core.libraries.libraries_constants import KINDS
from gcodeproducer.core.libraries.profile import Profile
from gcodeproducer.core.pipeline.slice_pipeline import SlicePipeline
from .edit_history import EditHistory
from .window_state import WindowState


def settings_history(dialog):
    def capture():
        return copy.deepcopy(dialog.values)

    def restore(values):
        dialog.values = copy.deepcopy(values)
        dialog.editor.values.update({k: v for k, v in values.items() if k in dialog.editor.values})
    return EditHistory(dialog, capture, restore)


def pipeline_history(dialog):
    def restore(state):
        dialog.pipeline = SlicePipeline.from_dict(state)
        dialog._reload(dialog.lst.currentRow())
    return EditHistory(dialog, lambda: dialog.pipeline.to_dict(), restore)


def library_history(dialog):
    def capture():
        return ({k: [p.to_dict() for p in dialog.libset[k].all()] for k in KINDS},
                [p.to_dict() for p in dialog._deleted], dialog.kind(),
                dialog._current().id if dialog._current() else None)

    def restore(state):
        libraries, deleted, kind, selected = state
        previous = dialog.editor_area.takeWidget()
        if previous is not None:
            previous.hide()
            previous.deleteLater()
        for k in KINDS:
            WindowState.restore_library(dialog.libset[k], libraries[k], Profile, save=False)
        dialog._deleted = [Profile.from_dict(p) for p in deleted]
        dialog.tabs.blockSignals(True)
        dialog.tabs.setCurrentIndex(KINDS.index(kind))
        dialog.tabs.blockSignals(False)
        dialog._reload(selected)
    return EditHistory(dialog, capture, restore)
