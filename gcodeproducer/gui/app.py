"""Compatibility exports. Implementation: gcodeproducer.gui.application.app."""
from gcodeproducer.gui.application.app import apply_theme, run_gui


if __name__ == "__main__":
    import sys
    sys.exit(run_gui(sys.argv[1] if len(sys.argv) > 1 else None))
