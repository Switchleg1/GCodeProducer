"""GUI entry point."""
from __future__ import annotations

import sys


def apply_theme(app) -> None:
    """Dark Fusion theme shared with GCodeTools."""
    from PyQt6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    pal = QPalette()
    dark, base, text = QColor(45, 47, 52), QColor(32, 34, 38), QColor(220, 222, 226)
    for role, col in ((QPalette.ColorRole.Window, dark), (QPalette.ColorRole.WindowText, text),
                      (QPalette.ColorRole.Base, base), (QPalette.ColorRole.AlternateBase, dark),
                      (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, dark),
                      (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.ToolTipBase, base),
                      (QPalette.ColorRole.ToolTipText, text), (QPalette.ColorRole.Highlight, QColor(60, 120, 200)),
                      (QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))):
        pal.setColor(role, col)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(120, 120, 120))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(120, 120, 120))
    app.setPalette(pal)
    app.setStyleSheet(
        "QToolButton#sectionHeader { background: #3a3d44; border: none; border-radius: 3px;"
        "  padding: 3px 6px; text-align: left; font-weight: bold; color: #dde; }"
        "QToolButton#sectionHeader:hover { background: #454952; }"
        "QToolButton#sectionHeader:checked { background: #34557f; color: white; }"
        "QFrame#sectionBody { background: #2b2d32; border-radius: 3px; }"
        "QToolButton#modeButton { background: #34373d; border: 1px solid #44474e; padding: 5px 14px;"
        "  font-weight: bold; color: #ccd; }"
        "QToolButton#modeButton:checked { background: #3c78c8; color: white; border-color: #3c78c8; }"
        "QToolButton#modeButton:disabled { color: #666; }"
        "QPushButton:checked { background: #3c78c8; color: white; border: 1px solid #5a8fd8; }"
        "QGroupBox { font-weight: bold; } QGroupBox QWidget { font-weight: normal; }")


def run_gui(path: str | None = None) -> int:
    from PyQt6.QtGui import QSurfaceFormat
    from PyQt6.QtWidgets import QApplication

    from .viewer import default_surface_format

    QSurfaceFormat.setDefaultFormat(default_surface_format())
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("GCodeProducer")
    app.setOrganizationName("GCodeProducer")
    apply_theme(app)

    from .main_window import MainWindow
    win = MainWindow()

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
