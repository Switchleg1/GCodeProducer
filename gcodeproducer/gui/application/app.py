"""GUI entry point."""
from __future__ import annotations
from .application_constants import THEME_COLORS, THEME_ROLES, THEME_STYLESHEET
import sys


def apply_theme(app) -> None:
    """Apply the application's dark Fusion theme."""
    from PyQt6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in THEME_ROLES.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(*THEME_COLORS[color]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(*THEME_COLORS["disabled"]))
    app.setPalette(palette)
    app.setStyleSheet(THEME_STYLESHEET)


def run_gui(path: str | None = None) -> int:
    import multiprocessing
    multiprocessing.freeze_support()          # slicing runs in a spawned process (also when frozen)
    from PyQt6.QtGui import QSurfaceFormat
    from PyQt6.QtWidgets import QApplication

    from gcodeproducer.gui.rendering.gcode_viewer import default_surface_format

    QSurfaceFormat.setDefaultFormat(default_surface_format())
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("GCodeProducer")
    app.setOrganizationName("GCodeProducer")
    apply_theme(app)

    from gcodeproducer.gui.application.main_window import MainWindow
    win = MainWindow(resume_session=not path)

    def excepthook(etype, value, tb):
        import traceback
        txt = "".join(traceback.format_exception(etype, value, tb))
        sys.stderr.write(txt)
        try:
            win.log(txt)
            win.statusBar().showMessage(f"Error: {value}", 8000)
        except Exception:
            pass
    sys.excepthook = excepthook
    win.show()
    if path:
        win.open_model(path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_gui(sys.argv[1] if len(sys.argv) > 1 else None))
