import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        from gcodeproducer.gui.application.app import run_gui
        sys.exit(run_gui(sys.argv[2] if len(sys.argv) > 2 else None))
    from gcodeproducer.cli import main
    sys.exit(main())
